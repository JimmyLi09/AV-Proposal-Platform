import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .extract.jobs import read_files
from .extract.run import METHOD_LABEL
from .models import ExtractedField, Project, Proposal, Revision, SourceFile, User
from .storage import original_name, safe_name, save_original

router = APIRouter()
COOKIE = "avp_user"


def get_db(request: Request):
    with request.app.state.Session() as db:
        yield db


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.cookies.get(COOKIE)
    return db.get(User, int(uid)) if uid and uid.isdigit() else None


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "请先选择名字登录")
    return user


def iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "role": u.role}


def file_out(f: SourceFile) -> dict:
    return {
        "id": f.id, "filename": f.filename, "file_type": f.file_type, "grade": f.grade,
        "size": f.size, "sha256": f.sha256, "uploaded_by": f.uploader.name, "uploaded_at": iso(f.uploaded_at),
        "read_status": f.read_status, "read_method": METHOD_LABEL.get(f.read_method or "", ""),
        "read_note": f.read_note or "", "fields_found": len(f.extracted),
    }


def proposal_out(p: Proposal) -> dict:
    rev = p.revisions[-1]
    return {
        "id": p.id, "name": p.name, "business_line": p.business_line, "mode": p.mode,
        "rev_no": rev.rev_no, "status": rev.status, "author": rev.author.name, "created_at": iso(p.created_at),
    }


def project_out(p: Project) -> dict:
    return {
        "id": p.id, "name": p.name, "client": p.client, "project_no": p.project_no,
        "location": p.location, "notes": p.notes, "owner": user_out(p.owner), "created_at": iso(p.created_at),
        "files": [file_out(f) for f in p.files],
        "proposals": [proposal_out(x) for x in p.proposals],
    }


def get_project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "项目不存在")
    return p


class Stripped(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


# ---- 轻账号 ----

class UserIn(Stripped):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field("", max_length=40)


class SessionIn(BaseModel):
    user_id: int


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.name))]


@router.post("/users", status_code=201)
def add_user(body: UserIn, db: Session = Depends(get_db)):
    u = User(name=body.name, role=body.role)
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        raise HTTPException(409, "这个名字已经存在")
    return user_out(u)


@router.get("/session")
def get_session(user: User | None = Depends(current_user)):
    return user_out(user) if user else None


@router.post("/session")
def login(body: SessionIn, response: Response, db: Session = Depends(get_db)):
    u = db.get(User, body.user_id)
    if u is None:
        raise HTTPException(404, "名字不存在")
    response.set_cookie(COOKIE, str(u.id), httponly=True, samesite="lax", max_age=180 * 24 * 3600)
    return user_out(u)


@router.delete("/session", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE)


# ---- 项目 ----

class ProjectIn(Stripped):
    name: str = Field(min_length=1, max_length=200)
    client: str = Field(min_length=1, max_length=200)
    project_no: str | None = Field(None, max_length=40)
    location: str = Field("", max_length=200)
    notes: str = ""
    owner_id: int | None = None


class ProjectPatch(Stripped):
    name: str | None = Field(None, min_length=1, max_length=200)
    client: str | None = Field(None, min_length=1, max_length=200)
    project_no: str | None = Field(None, max_length=40)
    location: str | None = Field(None, max_length=200)
    notes: str | None = None
    owner_id: int | None = None


def check_owner(db: Session, owner_id: int) -> None:
    if db.get(User, owner_id) is None:
        raise HTTPException(422, "负责人不存在")


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = db.scalars(select(Project).order_by(Project.id.desc()))
    return [{k: v for k, v in project_out(p).items() if k != "files"} | {"file_count": len(p.files)} for p in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    owner_id = body.owner_id or user.id
    check_owner(db, owner_id)
    p = Project(**body.model_dump(exclude={"project_no", "owner_id"}), project_no=body.project_no or None,
                owner_id=owner_id, created_by=user.id)
    db.add(p)
    db.commit()
    return project_out(p)


@router.get("/projects/{project_id}")
def read_project(project_id: int, db: Session = Depends(get_db)):
    return project_out(get_project(db, project_id))


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectPatch, _: User = Depends(require_user), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    changes = body.model_dump(exclude_unset=True)
    if "owner_id" in changes:
        if changes["owner_id"] is None:
            raise HTTPException(422, "负责人不能为空")
        check_owner(db, changes["owner_id"])
    for key in ("name", "client"):
        if key in changes and changes[key] is None:
            raise HTTPException(422, f"{key} 不能为空")
    if "project_no" in changes:
        changes["project_no"] = changes["project_no"] or None  # 清空 = 未关联
    for key, value in changes.items():
        setattr(p, key, value)
    db.commit()
    return project_out(p)


# ---- 原件 ----

@router.post("/projects/{project_id}/files", status_code=201)
def upload_files(project_id: int, files: list[UploadFile], request: Request, background: BackgroundTasks,
                 user: User = Depends(require_user), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    root = request.app.state.data_dir
    created = []
    for up in files:
        name = original_name(up.filename)
        # 每个文件一个新目录：同名文件再传也是新的一份，原件不动
        rel = f"files/{p.id}/{uuid.uuid4().hex}/{safe_name(name)}"
        sha, size = save_original(root, rel, up.file)
        ext = name.rpartition(".")[2].lower() if "." in name else ""
        f = SourceFile(project_id=p.id, filename=name, file_type=ext[:20], stored_path=rel,
                       sha256=sha, size=size, uploaded_by=user.id, read_status="reading")
        db.add(f)
        created.append(f)
    db.commit()
    background.add_task(read_files, request.app.state, [f.id for f in created])  # 上传完成 → 提取中
    return [file_out(f) for f in created]


@router.post("/projects/{project_id}/read")
def reread_files(project_id: int, request: Request, background: BackgroundTasks,
                 _: User = Depends(require_user), db: Session = Depends(get_db)):
    """重新读取项目里的全部文件（例如装好 ODA 转换器之后）。原件不动，只替换读取结果和截图副本。"""
    p = get_project(db, project_id)
    for f in p.files:
        f.read_status = "reading"
    db.commit()
    background.add_task(read_files, request.app.state, [f.id for f in p.files])
    return [file_out(f) for f in p.files]


@router.get("/extracted/{field_id}/crop")
def extracted_crop(field_id: int, request: Request, db: Session = Depends(get_db)):
    x = db.get(ExtractedField, field_id)
    if x is None or not x.crop_path:
        raise HTTPException(404, "没有原文截图")
    return FileResponse(request.app.state.data_dir / x.crop_path)


@router.get("/files/{file_id}")
def download_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    f = db.get(SourceFile, file_id)
    if f is None:
        raise HTTPException(404, "文件不存在")
    return FileResponse(request.app.state.data_dir / f.stored_path, filename=f.filename)


# ---- Proposal 与 Rev ----

class ProposalIn(Stripped):
    name: str = Field(min_length=1, max_length=200)
    business_line: Literal["LED", "PJ"]


@router.post("/projects/{project_id}/proposals", status_code=201)
def create_proposal(project_id: int, body: ProposalIn, user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    prop = Proposal(project_id=p.id, name=body.name, business_line=body.business_line, created_by=user.id)
    prop.revisions.append(Revision(rev_no=0, author_id=user.id))
    db.add(prop)
    db.commit()
    return proposal_out(prop)
