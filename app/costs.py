"""单价表：人工录入（清单 E1：采购），只追加不修改；同一个 key 以最新一条为准。"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_db, iso, require_user
from .models import CostEntry, User

router = APIRouter(prefix="/costs")
VALID_DAYS = 90  # 单价默认有效期（清单 E4，示例值）

# 示例价格（来自原型 Cost & BOQ 页），SC-4 故意设成已过期，用来演示标红
SAMPLE = [("IC-25:640x480", 1200), ("IC-25:640x640", 1500), ("IC-25:module", 90), ("SC-4", 2800),
          ("SP-1", 3500), ("power_cable", 120), ("data_cable", 60), ("db_box", 900), ("install:wall", 2200)]


def ensure_seed(db: Session) -> None:
    if db.scalar(select(CostEntry.id)) is None:
        today = date.today()
        for key, amount in SAMPLE:
            expired = key == "SC-4"
            db.add(CostEntry(key=key, amount_cents=amount * 100, sample=True, note="示例价格",
                             valid_until=today - timedelta(days=14) if expired else today + timedelta(days=VALID_DAYS)))
        db.commit()


def cost_out(c: CostEntry) -> dict:
    return {"key": c.key, "amount_cents": c.amount_cents, "currency": c.currency,
            "valid_until": c.valid_until.isoformat() if c.valid_until else None, "note": c.note, "sample": c.sample,
            "entered_by": c.author.name if c.author else None, "entered_at": iso(c.entered_at)}


def current(db: Session) -> dict:
    """key → 当前单价（最新一条）。"""
    return {c.key: cost_out(c) for c in db.scalars(select(CostEntry).order_by(CostEntry.id))}


@router.get("")
def list_costs(db: Session = Depends(get_db)):
    return current(db)


class CostIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)  # S$
    valid_until: date | None = None
    note: str = Field("", max_length=500)


@router.post("", status_code=201)
def add_cost(body: CostIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = CostEntry(key=body.key, amount_cents=int(body.amount * 100), note=body.note, entered_by=user.id,
                  valid_until=body.valid_until or date.today() + timedelta(days=VALID_DAYS))
    db.add(c)
    db.commit()
    return cost_out(c)
