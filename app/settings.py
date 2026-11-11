"""设置页：人员（姓名、角色、做过的方案数，可加人、改角色）、服务器与存储（只显示）、立即备份。

备份：数据库用 SQLite 的在线备份得到一致的副本（WAL 模式下直接拷文件可能不完整），连同资料目录里的原件、生成文件
打包成一个 zip，放在备份文件夹（deploy.yaml 的 backup_dir，由 IT 定）。资料库文件夹是公司共享的原资料，不打包；
备份文件夹本身也不打包。在后台线程里做，页面看进度；同一时间只做一份。恢复是手动的，步骤见 docs/服务器装机流程.md。
"""
import os
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from .api import get_db, iso, require_user, user_out
from .i18n import tr
from .models import Revision, User, utcnow

router = APIRouter()
DB_FILES = ("avp.db", "avp.db-wal", "avp.db-shm")


def backup_files(data_dir: Path, skip: list[Path]) -> list[Path]:
    """资料目录里要打包的文件：数据库文件另外处理；资料库、备份文件夹在资料目录里面时跳过。"""
    out = []
    for p in sorted(data_dir.rglob("*")):
        if not p.is_file() or (p.parent == data_dir and p.name in DB_FILES):
            continue
        if any(p.is_relative_to(s) for s in skip):
            continue
        out.append(p)
    return out


def make_backup(data_dir: Path, kb_dir: Path, backup_dir: Path, progress: dict) -> str:
    """打包成 avp-backup-年月日-时分秒.zip；先写 .part，写完再改名，备份文件夹里不会出现做了一半的 zip。"""
    backup_dir.mkdir(parents=True, exist_ok=True)
    files = backup_files(data_dir, [kb_dir, backup_dir])
    progress["total"] = len(files) + 1
    name = f"avp-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
    part = backup_dir / f"{name}.part"
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "avp.db"
            src, dst = sqlite3.connect(data_dir / "avp.db"), sqlite3.connect(copy)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            z.write(copy, "avp.db")
        progress["done"] = 1
        for p in files:
            z.write(p, p.relative_to(data_dir).as_posix())
            progress["done"] += 1
    os.replace(part, backup_dir / name)
    return name


def list_backups(backup_dir: Path) -> list[dict]:
    if not backup_dir.is_dir():
        return []
    out = []
    for p in sorted(backup_dir.glob("avp-backup-*.zip"), reverse=True):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size, "at": iso(datetime.fromtimestamp(st.st_mtime, timezone.utc))})
    return out


@router.get("/settings")
def settings(request: Request, db: Session = Depends(get_db)):
    from .drawing_export import oda_available
    state = request.app.state
    counts = dict(db.execute(select(Revision.author_id, func.count(distinct(Revision.proposal_id)))
                             .group_by(Revision.author_id)).all())
    return {
        "users": [user_out(u) | {"proposals": counts.get(u.id, 0)} for u in db.scalars(select(User).order_by(User.name))],
        "server": {"port": state.port, "data_dir": str(state.data_dir), "kb_dir": str(state.kb_dir),
                   "backup_dir": str(state.backup_dir), "project_platform": state.project_platform, "dwg": oda_available(state.oda),
                   "version": state.version},
        "backups": list_backups(state.backup_dir),
        "backup": state.backup_progress,
    }


class RoleIn(BaseModel):
    role: str = Field("", max_length=40)


@router.put("/users/{user_id}")
def set_role(user_id: int, body: RoleIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """改角色（只是标签，不管权限）。"""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, tr("名字不存在", "Name not found"))
    u.role = body.role.strip()
    db.commit()
    return user_out(u)


@router.post("/backups", status_code=202)
def start_backup(request: Request, user: User = Depends(require_user)):
    """立即备份：在后台做，GET /settings 看进度和备份列表。"""
    state = request.app.state
    if not state.backup_lock.acquire(blocking=False):
        raise HTTPException(409, tr("备份正在进行，等这一份做完", "A backup is already running"))
    progress = {"running": True, "done": 0, "total": 0, "by": user.name, "started": iso(utcnow()), "name": None, "error": None}
    state.backup_progress = progress

    def work():
        try:
            progress["name"] = make_backup(state.data_dir, state.kb_dir, state.backup_dir, progress)
        except Exception as e:  # 盘满、没有写权限、路径不存在等：写在页面上
            progress["error"] = f"{type(e).__name__}: {e}"
        finally:
            progress["running"] = False
            state.backup_lock.release()

    threading.Thread(target=work, daemon=True, name="backup").start()
    return {"backup": progress}
