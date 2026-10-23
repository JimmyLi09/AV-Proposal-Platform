"""Proposal 工作页：确认输入（确认关）→ 产品库推荐 → 规则计算 → 客户版 BOQ（不含价格）。"""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .api import file_out, get_db, iso, proposal_out, require_user
from .boq import build, to_xlsx
from .models import (ExtractedField, ProductLibraryVersion, Project, Proposal, RuleSetVersion, TemplateVersion, User,
                     utcnow)
from .rules.engine import LINES, calculate
from .storage import safe_name
from .templates.content import UNITS
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
    template = latest(db, TemplateVersion, prop.business_line)
    ready = rev.inputs and not pending(rev)  # 未确认的字段不能进入计算
    result = calculate(rules.content, library.content, rev.inputs, rev.cabinet_id) if ready else None
    return {"rules": rules, "library": library, "template": template}, result


def client_boq(db: Session, prop: Proposal, used: dict, result: dict | None, edits: dict | None) -> dict | None:
    if not result or not result["rules"]:
        return None
    ctx = result["values"] | {"proposal_name": prop.name, "project_name": db.get(Project, prop.project_id).name}
    return build(used["template"].content, ctx, edits)


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
    return {
        "proposal": proposal_out(prop),
        "project": {"id": prop.project_id},
        "rev": {"rev_no": rev.rev_no, "status": rev.status, "inputs": rev.inputs or {}, "cabinet_id": rev.cabinet_id,
                "input_meta": rev.input_meta or {}, "annotations": rev.annotations or {}},
        "pending": pending(rev),
        "files": [file_out(f) for f in db.get(Project, prop.project_id).files],
        "candidates": candidates(db, prop),
        "rules_version": used["rules"].version,
        "library_version": used["library"].version,
        "template_version": used["template"].version,
        "input_defs": used["rules"].content["inputs"],
        "product_fed": LINES[prop.business_line]["product_fed"],
        "result": result,
        "boq": client_boq(db, prop, used, result, rev.boq_edits),
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


class BoqRowIn(BaseModel):
    title: str | None = Field(None, max_length=300)
    specs: list[str] | None = Field(None, max_length=20)
    qty: float | None = Field(None, ge=0)
    reason: str = Field("", max_length=500)


class BoqAddedIn(BaseModel):
    key: str | None = Field(None, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    specs: list[str] = Field(default_factory=list, max_length=20)
    qty: float = Field(ge=0)
    unit: Literal[tuple(UNITS)]


class BoqIn(BaseModel):
    group: str | None = Field(None, max_length=300)
    rows: dict[str, BoqRowIn] = {}
    added: list[BoqAddedIn] = []


def _num(v: float):
    return int(v) if float(v).is_integer() else v


@router.put("/{proposal_id}/boq")
def save_boq(proposal_id: int, body: BoqIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """客户版 BOQ：改描述、规格、数量，或手动添加行。改了数量要写原因，标「手动」；数量改回规则值就恢复。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    used, result = compute(db, prop)
    default = client_boq(db, prop, used, result, None)
    if default is None:
        raise HTTPException(409, "还没有计算结果，算完才能改 BOQ")
    rules = {r["key"]: r for r in default["rows"]}
    old = rev.boq_edits or {}
    stamp = {"by": user.name, "at": iso(utcnow())}

    def stamped(out: dict, prev: dict) -> dict:  # 内容没变就保留原来的修改人和时间
        same = prev.get("by") and {k: v for k, v in prev.items() if k not in ("by", "at")} == out
        return out | ({"by": prev["by"], "at": prev["at"]} if same else stamp)

    rows = {}
    for key, e in body.rows.items():
        if key not in rules:
            raise HTTPException(422, "BOQ 里没有这一行")
        r, out = rules[key], {}
        if e.title is not None and e.title.strip() and e.title.strip() != r["title_default"]:
            out["title"] = e.title.strip()
        specs = None if e.specs is None else [x.strip() for x in e.specs if x.strip()]
        if specs is not None and specs != r["specs_default"]:
            out["specs"] = specs
        if e.qty is not None and _num(e.qty) != r["rule_qty"]:
            if not e.reason.strip():
                raise HTTPException(422, f"「{r['title_default']}」改了数量，要写原因")
            out |= {"qty": _num(e.qty), "reason": e.reason.strip()}
        if out:
            rows[key] = stamped(out, (old.get("rows") or {}).get(key, {}))
    prev_added = {a["key"]: a for a in old.get("added") or []}
    added, n = [], max([int(k[1:]) for k in prev_added if k[1:].isdigit()], default=0)
    for a in body.added:
        if a.key not in prev_added:
            n += 1
        key = a.key if a.key in prev_added else f"x{n}"
        out = {"key": key, "title": a.title.strip(), "specs": [x.strip() for x in a.specs if x.strip()],
               "qty": _num(a.qty), "unit": a.unit}
        added.append(stamped(out, prev_added.get(key, {})))
    group = (body.group or "").strip()
    rev.boq_edits = {"group": group if group and group != default["group_default"] else None,
                     "rows": rows, "added": added}
    db.commit()
    return view(db, prop)


@router.get("/{proposal_id}/boq.xlsx")
def export_boq(proposal_id: int, db: Session = Depends(get_db)):
    """导出客户版 BOQ（Excel）。文件属性里写 Rev、规则、产品库、模板版本；没批准的 Rev 标 DRAFT。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    used, result = compute(db, prop)
    boq = client_boq(db, prop, used, result, rev.boq_edits)
    if boq is None:
        raise HTTPException(409, "还没有计算结果，算完才能导出 BOQ")
    project = db.get(Project, prop.project_id)
    stamp = " · ".join(([] if rev.status == "approved" else ["DRAFT"]) + [
        f"Rev {rev.rev_no}", f"Rules {used['rules'].version}", f"Product library {used['library'].version}",
        f"Template {used['template'].version}"])
    meta = {"title": f"Bill of Quantities · {prop.name}",
            "subtitle": " · ".join(x for x in (project.name, project.client, project.project_no) if x), "stamp": stamp}
    name = f"{safe_name(project.name)}_{safe_name(prop.name)}_BOQ_Rev{rev.rev_no}.xlsx"
    return Response(to_xlsx(boq, meta),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
