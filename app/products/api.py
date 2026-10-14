from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api import get_db, require_user
from ..models import ProductLibraryVersion, User
from ..versions import check_base, history, latest, next_label, version_out
from .library import CATEGORY_LABEL, FIELDS, SCENES, STATUSES, LibraryError, load_seed, validate

router = APIRouter(prefix="/products")


def ensure_seed(db: Session) -> None:
    for line in FIELDS:
        if db.scalar(select(ProductLibraryVersion.id).where(ProductLibraryVersion.business_line == line)) is None:
            db.add(ProductLibraryVersion(business_line=line, version="v1.0", content=load_seed(line),
                                         reason="示例产品，清单 D 组填好后替换"))
    db.commit()


@router.get("/{line}")
def get_latest(line: str, db: Session = Depends(get_db)):
    v = latest(db, ProductLibraryVersion, line)
    fields = {cat: [{"name": n, "label": label, "type": kind} for n, label, kind in fs]
              for cat, fs in FIELDS[line].items()}
    return version_out(v) | {"fields": fields, "categories": CATEGORY_LABEL, "statuses": STATUSES, "scenes": SCENES}


@router.get("/{line}/versions")
def list_versions(line: str, db: Session = Depends(get_db)):
    latest(db, ProductLibraryVersion, line)
    return [version_out(v, content=False) for v in history(db, ProductLibraryVersion, line)]


class SaveIn(BaseModel):
    base_id: int
    reason: str = Field(min_length=1, max_length=500)
    content: dict


@router.post("/{line}", status_code=201)
def save_version(line: str, body: SaveIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    base = latest(db, ProductLibraryVersion, line)
    check_base(base, body.base_id, body.content)
    try:
        validate(body.content, line)
    except LibraryError as e:
        raise HTTPException(422, str(e))
    except (KeyError, TypeError, AttributeError):
        raise HTTPException(422, "产品库内容格式不对")
    v = ProductLibraryVersion(business_line=line, version=next_label(base.version), content=body.content,
                              reason=body.reason.strip(), created_by=user.id)
    db.add(v)
    db.commit()
    return version_out(v)
