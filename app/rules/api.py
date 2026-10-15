from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api import get_db, require_user
from ..models import ProductLibraryVersion, RuleSetVersion, User
from ..versions import check_base, history, latest, next_label, version_out
from .engine import LINES, calculate, load_seed, validate
from .expr import ExprError

router = APIRouter(prefix="/rules")


def ensure_seed(db: Session) -> None:
    """每条业务线第一次启动时写入初始规则集（方案 V1 的 v1.3）。"""
    for line in LINES:
        if db.scalar(select(RuleSetVersion.id).where(RuleSetVersion.business_line == line)) is None:
            content, _ = load_seed(line)
            db.add(RuleSetVersion(business_line=line, version="v1.3", content=content,
                                  reason="初始版本（平台方案 V1，2026-10-14）"))
    db.commit()


def checked(content: dict, base: RuleSetVersion) -> dict:
    try:
        if content.get("business_line") != base.business_line:
            raise ExprError("业务线不对")
        validate(content, base.content)
    except ExprError as e:
        raise HTTPException(422, str(e))
    except (KeyError, TypeError, AttributeError):
        raise HTTPException(422, "规则内容格式不对")
    return content


@router.get("/{line}")
def get_latest(line: str, db: Session = Depends(get_db)):
    return version_out(latest(db, RuleSetVersion, line)) | {"product_fed": LINES[line]["product_fed"]}


@router.get("/{line}/versions")
def list_versions(line: str, db: Session = Depends(get_db)):
    latest(db, RuleSetVersion, line)
    return [version_out(v, content=False) for v in history(db, RuleSetVersion, line)]


@router.get("/{line}/versions/{version_id}")
def get_version(line: str, version_id: int, db: Session = Depends(get_db)):
    v = db.get(RuleSetVersion, version_id)
    if v is None or v.business_line != line:
        raise HTTPException(404, "规则版本不存在")
    return version_out(v)


@router.get("/{line}/sample")
def get_sample(line: str, db: Session = Depends(get_db)):
    latest(db, RuleSetVersion, line)
    return load_seed(line)[1]


class SaveIn(BaseModel):
    base_id: int
    reason: str = Field(min_length=1, max_length=500)
    content: dict


@router.post("/{line}", status_code=201)
def save_version(line: str, body: SaveIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    base = latest(db, RuleSetVersion, line)
    check_base(base, body.base_id, body.content)
    v = RuleSetVersion(business_line=line, version=next_label(base.version), content=checked(body.content, base),
                       reason=body.reason.strip(), created_by=user.id)
    db.add(v)
    db.commit()
    return version_out(v)


class RunIn(BaseModel):
    inputs: dict
    version_id: int | None = None  # 不填 = 最新版本
    content: dict | None = None  # 试算未保存的修改


@router.post("/{line}/run")
def run_rules(line: str, body: RunIn, db: Session = Depends(get_db)):
    base = latest(db, RuleSetVersion, line)
    if body.content is not None:
        content = checked(body.content, base)
    elif body.version_id is not None:
        content = get_version(line, body.version_id, db)["content"]
    else:
        content = base.content
    library = latest(db, ProductLibraryVersion, line)
    return calculate(content, library.content, body.inputs) | {"library_version": library.version}
