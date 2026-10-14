"""Proposal 工作页：已确认输入 → 产品库推荐 → 规则计算 → BOQ 与 Cost。"""
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .api import get_db, proposal_out, require_user
from .boq import price
from .costs import current
from .models import ProductLibraryVersion, Proposal, RuleSetVersion, User
from .rules.engine import LINES, calculate
from .versions import latest

router = APIRouter(prefix="/proposals")


def get_proposal(db: Session, proposal_id: int) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if p is None:
        raise HTTPException(404, "方案不存在")
    return p


def compute(db: Session, prop: Proposal) -> tuple[dict, dict | None]:
    rev = prop.revisions[-1]
    rules = latest(db, RuleSetVersion, prop.business_line)
    library = latest(db, ProductLibraryVersion, prop.business_line)
    result = calculate(rules.content, library.content, rev.inputs, rev.cabinet_id) if rev.inputs else None
    return {"rules": rules, "library": library}, result


def view(db: Session, prop: Proposal) -> dict:
    rev = prop.revisions[-1]
    used, result = compute(db, prop)
    params = {p["name"]: p for p in used["rules"].content["params"]}
    boq = price(result["boq"], rev.manual_lines or [], current(db), date.today()) if result else None
    return {
        "proposal": proposal_out(prop),
        "project": {"id": prop.project_id},
        "rev": {"rev_no": rev.rev_no, "status": rev.status, "inputs": rev.inputs or {}, "cabinet_id": rev.cabinet_id,
                "manual_lines": rev.manual_lines or [], "sell_price_cents": rev.sell_price_cents,
                "price_display": rev.price_display or "none"},
        "rules_version": used["rules"].version,
        "library_version": used["library"].version,
        "input_defs": used["rules"].content["inputs"],
        "product_fed": LINES[prop.business_line]["product_fed"],
        "gst_rate": params.get("gst_rate", {}).get("value"),
        "gst_status": params.get("gst_rate", {}).get("status"),
        "result": result,
        "boq": boq,
    }


@router.get("/{proposal_id}")
def read(proposal_id: int, db: Session = Depends(get_db)):
    return view(db, get_proposal(db, proposal_id))


class InputsIn(BaseModel):
    inputs: dict
    cabinet_id: str | None = None


@router.put("/{proposal_id}/inputs")
def save_inputs(proposal_id: int, body: InputsIn, _: User = Depends(require_user), db: Session = Depends(get_db)):
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    rules = latest(db, RuleSetVersion, prop.business_line)
    allowed = {i["name"] for i in rules.content["inputs"]} - set(LINES[prop.business_line]["product_fed"])
    if unknown := set(body.inputs) - allowed:
        raise HTTPException(422, f"不认识的输入：{', '.join(sorted(unknown))}")
    rev.inputs, rev.cabinet_id = body.inputs, body.cabinet_id
    _, result = compute(db, prop)
    complete = result and result["rules"] and not any(r["missing"] or r["error"] for r in result["rules"])
    rev.status = "calculated" if complete else "draft"
    db.commit()
    return view(db, prop)


class ManualLine(BaseModel):
    item: str = Field(min_length=1, max_length=200)
    model: str = Field("", max_length=100)
    qty: float | None = None
    unit: str = Field("", max_length=20)
    unit_cost: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=2)  # S$
    why: str = Field("", max_length=200)


class CommercialIn(BaseModel):
    manual_lines: list[ManualLine]
    sell_price: Decimal | None = Field(None, ge=0, max_digits=12, decimal_places=2)
    price_display: Literal["none", "total", "itemised"] = "none"


@router.put("/{proposal_id}/commercial")
def save_commercial(proposal_id: int, body: CommercialIn, user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    rev.manual_lines = [m.model_dump(exclude={"unit_cost"})
                        | {"unit_cost": None if m.unit_cost is None else int(m.unit_cost * 100),
                           "why": m.why or f"{user.name} 添加"}
                        for m in body.manual_lines]
    rev.sell_price_cents = None if body.sell_price is None else int(body.sell_price * 100)
    rev.price_display = body.price_display
    db.commit()
    return view(db, prop)
