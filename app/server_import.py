"""从服务器文件夹导入项目文件（2026-11-17 Jimmy：平台直接读服务器上的 D:\\LED Projects）。

部署配置 project_import_dir 指定根文件夹；界面里逐层打开子文件夹，选一个导入。
导入 = 把可读的文件复制成项目原件（和上传一样只读、不覆盖），服务器上的原文件不动。
同一项目里已经有相同内容（sha256）的文件跳过，重复导入不会多出一份。
"""
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .api import file_out, get_db, get_project, require_user
from .extract.jobs import read_files
from .i18n import tr
from .models import SourceFile, User
from .storage import safe_name, save_original

router = APIRouter()
# 平台会读的类型；其它文件（视频、渲染工程等）不导入
TYPES = {"pdf", "jpg", "jpeg", "png", "xlsx", "xlsm", "dxf", "dwg"}
MAX_FILES = 300  # 一次导入的上限：太多说明选的层级太高


def _root(request: Request) -> Path:
    root = request.app.state.import_dir
    if root is None:
        raise HTTPException(404, tr("没有设置服务器项目文件夹（deploy.local.yaml 的 project_import_dir）",
                                    "No server project folder is set (project_import_dir in deploy.local.yaml)"))
    if not root.is_dir():
        raise HTTPException(404, tr(f"服务器上找不到文件夹 {root}", f"Folder {root} not found on the server"))
    return root


def _folder(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    if path != root and root not in path.parents:  # 只能在设置的文件夹里面
        raise HTTPException(400, tr("只能选设置的项目文件夹里面的文件夹", "Only folders inside the project folder"))
    if not path.is_dir():
        raise HTTPException(404, tr("文件夹不存在", "Folder not found"))
    return path


def _readable(p: Path) -> bool:
    return p.is_file() and not p.name.startswith(("~$", ".")) and p.suffix[1:].lower() in TYPES


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def server_file(request: Request, rel: str) -> Path:
    """设置的文件夹里的一个文件（规格书批量导入用）。"""
    root = _root(request)
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, tr(f"文件不存在：{rel}", f"File not found: {rel}"))
    return path


@router.get("/import-folder")
def browse(request: Request, path: str = "", entries: bool = False):
    """看一层：子文件夹，以及这一层（含下面各层）有多少个可导入的文件；entries=1 时列出这一层的文件。"""
    state = request.app.state
    if state.import_dir is None:
        return {"configured": False}
    root = _root(request)
    folder = _folder(root, path)
    dirs = sorted((d for d in folder.iterdir() if d.is_dir() and not d.name.startswith(".")), key=lambda d: d.name.lower())
    files = [p for p in folder.rglob("*") if _readable(p)]
    out = {"configured": True, "root": str(root), "path": folder.relative_to(root).as_posix().strip("."),
           "folders": [d.name for d in dirs], "files": len(files), "max": MAX_FILES}
    if entries:
        out["entries"] = [{"name": p.name, "size": p.stat().st_size}
                          for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
                          if p.is_file() and not p.name.startswith(("~$", "."))][:500]
    return out


class ImportIn(BaseModel):
    path: str


@router.post("/projects/{project_id}/import-folder", status_code=201)
def import_folder(project_id: int, body: ImportIn, request: Request, background: BackgroundTasks,
                  user: User = Depends(require_user), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    root = _root(request)
    folder = _folder(root, body.path)
    found = sorted((x for x in folder.rglob("*") if _readable(x)), key=lambda x: x.as_posix().lower())
    if not found:
        raise HTTPException(422, tr("这个文件夹里没有平台能读的文件（PDF、图片、Excel、DWG、DXF）",
                                    "No readable files in this folder (PDF, image, Excel, DWG, DXF)"))
    if len(found) > MAX_FILES:
        raise HTTPException(422, tr(f"文件太多（{len(found)} 个，上限 {MAX_FILES}），请打开下一层再导入",
                                    f"Too many files ({len(found)}, limit {MAX_FILES}); open a sub-folder"))
    have = {f.sha256 for f in p.files}
    created, skipped = [], 0
    for src in found:
        if _sha(src) in have:
            skipped += 1
            continue
        name = src.relative_to(folder).as_posix()[-255:]  # 带子文件夹，知道是从哪来的
        rel = f"files/{p.id}/{uuid.uuid4().hex}/{safe_name(src.name)}"
        with open(src, "rb") as fh:
            sha, size = save_original(request.app.state.data_dir, rel, fh)
        have.add(sha)
        f = SourceFile(project_id=p.id, filename=name, file_type=src.suffix[1:].lower(), stored_path=rel,
                       sha256=sha, size=size, uploaded_by=user.id, read_status="reading")
        db.add(f)
        created.append(f)
    db.commit()
    if created:
        background.add_task(read_files, request.app.state, [f.id for f in created])
    return {"files": [file_out(f) for f in created], "skipped": skipped}
