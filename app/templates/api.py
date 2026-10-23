from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api import get_db, require_user
from ..models import RuleSetVersion, TemplateVersion, User
from ..rules.engine import value_names
from ..versions import check_base, history, latest, next_label, version_out
from .content import CONTEXT, LINE_NAMES, UNITS, TemplateError, load_seed, validate

router = APIRouter(prefix="/templates")


def ensure_seed(db: Session) -> None:
    for line in LINE_NAMES:
        if db.scalar(select(TemplateVersion.id).where(TemplateVersion.business_line == line)) is None:
            db.add(TemplateVersion(business_line=line, version="v1.0", content=load_seed(line),
                                   reason="初始模板：客户版 BOQ 默认行（CR-6）"))
    db.commit()


def known(db: Session, line: str) -> set[str]:
    return value_names(latest(db, RuleSetVersion, line).content)


@router.get("/{line}")
def get_latest(line: str, db: Session = Depends(get_db)):
    v = latest(db, TemplateVersion, line)
    return version_out(v) | {"units": UNITS, "names": sorted(known(db, line) | CONTEXT)}


@router.get("/{line}/versions")
def list_versions(line: str, db: Session = Depends(get_db)):
    latest(db, TemplateVersion, line)
    return [version_out(v, content=False) for v in history(db, TemplateVersion, line)]


class SaveIn(BaseModel):
    base_id: int
    reason: str = Field(min_length=1, max_length=500)
    content: dict


@router.post("/{line}", status_code=201)
def save_version(line: str, body: SaveIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    base = latest(db, TemplateVersion, line)
    check_base(base, body.base_id, body.content)
    try:
        validate(body.content, line, known(db, line))
    except TemplateError as e:
        raise HTTPException(422, str(e))
    except (KeyError, TypeError, AttributeError):
        raise HTTPException(422, "模板内容格式不对")
    v = TemplateVersion(business_line=line, version=next_label(base.version), content=body.content,
                        reason=body.reason.strip(), created_by=user.id)
    db.add(v)
    db.commit()
    return version_out(v)
