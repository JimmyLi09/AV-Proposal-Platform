"""Proposal 工作页：确认输入（确认关）→ 产品库推荐 → 规则计算 → BOQ 与 Cost。"""
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .api import file_out, get_db, iso, proposal_out, require_user
from .boq import price
from .costs import current
from .models import ExtractedField, ProductLibraryVersion, Project, Proposal, RuleSetVersion, User, utcnow
from .rules.engine import LINES, calculate
from .versions import latest

router = APIRouter(prefix="/proposals")


def get_proposal(db: Session, proposal_id: int) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if p is None:
        raise HTTPException(404, "方案不存在")
    return p


RANK = {"high": 0, "medium": 1, "low": 2}


def pending(rev) -> list[str]:
    """确认关：从文件读到、置信度为 medium / low、还没人确认的字段。"""
    return [k for k, m in (rev.input_meta or {}).items()
            if m.get("source") == "file" and m.get("confidence") != "high" and not m.get("confirmed_by")]


def compute(db: Session, prop: Proposal) -> tuple[dict, dict | None]:
    rev = prop.revisions[-1]
    rules = latest(db, RuleSetVersion, prop.business_line)
    library = latest(db, ProductLibraryVersion, prop.business_line)
    ready = rev.inputs and not pending(rev)  # 未确认的字段不能进入计算
    result = calculate(rules.content, library.content, rev.inputs, rev.cabinet_id) if ready else None
    return {"rules": rules, "library": library}, result


def candidates(db: Session, prop: Proposal) -> dict[str, list]:
    """项目文件里认出的候选值，按置信度排（同置信度按文件上传顺序）。"""
    out: dict[str, list] = {}
    for f in db.get(Project, prop.project_id).files:
        for x in f.extracted:
            out.setdefault(x.field, []).append(
                {"id": x.id, "value": x.value, "confidence": x.confidence, "file_id": f.id, "filename": f.filename,
                 "location": x.location, "snippet": x.snippet, "crop": bool(x.crop_path)})
    for items in out.values():
        items.sort(key=lambda c: RANK[c["confidence"]])
    return out


def refresh_status(db: Session, prop: Proposal) -> None:
    rev = prop.revisions[-1]
    if pending(rev):
        rev.status = "confirming"
        return
    _, result = compute(db, prop)
    complete = result and result["rules"] and not any(r["missing"] or r["error"] for r in result["rules"])
    rev.status = "calculated" if complete else "draft"


def view(db: Session, prop: Proposal) -> dict:
    rev = prop.revisions[-1]
    used, result = compute(db, prop)
    params = {p["name"]: p for p in used["rules"].content["params"]}
    boq = price(result["boq"], rev.manual_lines or [], current(db), date.today()) if result else None
    return {
        "proposal": proposal_out(prop),
        "project": {"id": prop.project_id},
        "rev": {"rev_no": rev.rev_no, "status": rev.status, "inputs": rev.inputs or {}, "cabinet_id": rev.cabinet_id,
                "input_meta": rev.input_meta or {}, "manual_lines": rev.manual_lines or [],
                "sell_price_cents": rev.sell_price_cents, "price_display": rev.price_display or "none"},
        "pending": pending(rev),
        "files": [file_out(f) for f in db.get(Project, prop.project_id).files],
        "candidates": candidates(db, prop),
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


def allowed_inputs(db: Session, prop: Proposal) -> set[str]:
    rules = latest(db, RuleSetVersion, prop.business_line)
    return {i["name"] for i in rules.content["inputs"]} - set(LINES[prop.business_line]["product_fed"])


def confirmed_by(user: User) -> dict:
    return {"confirmed_by": user.name, "confirmed_at": iso(utcnow())}


@router.put("/{proposal_id}/inputs")
def save_inputs(proposal_id: int, body: InputsIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """手工录入 / 改值：改过的字段记为手填，等于录入人已确认。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    if unknown := set(body.inputs) - allowed_inputs(db, prop):
        raise HTTPException(422, f"不认识的输入：{', '.join(sorted(unknown))}")
    old, meta = rev.inputs or {}, dict(rev.input_meta or {})
    for k in set(old) | set(body.inputs):
        if body.inputs.get(k) in (None, "", []):
            meta.pop(k, None)
        elif body.inputs[k] != old.get(k):
            meta[k] = {"source": "manual", "confidence": "high"} | confirmed_by(user)
    rev.inputs, rev.input_meta, rev.cabinet_id = body.inputs, meta, body.cabinet_id
    refresh_status(db, prop)
    db.commit()
    return view(db, prop)


def _use(rev, x: ExtractedField) -> None:
    rev.inputs = {**(rev.inputs or {}), x.field: x.value}
    rev.input_meta = {**(rev.input_meta or {}), x.field: {
        "source": "file", "confidence": x.confidence, "extracted_id": x.id, "filename": x.source_file.filename,
        "location": x.location, "snippet": x.snippet, "confirmed_by": None}}


@router.post("/{proposal_id}/fill-from-files")
def fill_from_files(proposal_id: int, _: User = Depends(require_user), db: Session = Depends(get_db)):
    """用文件里认出的值填入还空着的字段（不覆盖已填的值）；medium / low 的要逐项确认。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    allowed = allowed_inputs(db, prop)
    for field, items in candidates(db, prop).items():
        if field in allowed and (rev.inputs or {}).get(field) in (None, "", []):
            _use(rev, db.get(ExtractedField, items[0]["id"]))
    refresh_status(db, prop)
    db.commit()
    return view(db, prop)


class PickIn(BaseModel):
    extracted_id: int


@router.post("/{proposal_id}/pick")
def pick(proposal_id: int, body: PickIn, _: User = Depends(require_user), db: Session = Depends(get_db)):
    """多个文件读到不同的值时，选用其中一个。"""
    prop = get_proposal(db, proposal_id)
    x = db.get(ExtractedField, body.extracted_id)
    if x is None or x.source_file.project_id != prop.project_id or x.field not in allowed_inputs(db, prop):
        raise HTTPException(404, "候选值不存在")
    _use(prop.revisions[-1], x)
    refresh_status(db, prop)
    db.commit()
    return view(db, prop)


class ConfirmIn(BaseModel):
    field: str


@router.post("/{proposal_id}/confirm")
def confirm(proposal_id: int, body: ConfirmIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """确认关：逐项确认，记录确认人和时间。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    meta = dict(rev.input_meta or {})
    if body.field not in meta:
        raise HTTPException(404, "这个字段没有待确认的值")
    meta[body.field] = meta[body.field] | confirmed_by(user)
    rev.input_meta = meta
    refresh_status(db, prop)
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
