"""Proposal 工作页：确认输入（确认关）→ 产品库推荐 → 规则计算 → 客户版 BOQ（不含价格）。"""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .api import file_out, get_db, iso, proposal_out, require_user
from . import drawing_export
from .boq import build, build_multi, to_xlsx
from .drawing import build as build_drawing
from .i18n import stored, text, tr, unit, use
from .models import (ExtractedField, ProductLibraryVersion, Project, Proposal, RuleSetVersion, TemplateVersion, User,
                     utcnow)
from .rules import multiface
from .rules.engine import LINES, calculate
from .storage import safe_name
from .templates.content import UNITS
from .versions import latest

router = APIRouter(prefix="/proposals")


def get_proposal(db: Session, proposal_id: int) -> Proposal:
    p = db.get(Proposal, proposal_id)
    if p is None:
        raise HTTPException(404, tr("方案不存在", "Proposal not found"))
    return p


RANK = {"high": 0, "medium": 1, "low": 2}


def pending(rev) -> list[str]:
    """确认关：从文件读到、置信度为 medium / low，或几份文件读到的值不一样（CR-7），还没人确认的字段。"""
    return [k for k, m in (rev.input_meta or {}).items()
            if m.get("source") == "file" and (m.get("confidence") != "high" or m.get("conflict")) and not m.get("confirmed_by")]


# 读文件认出的是通用的屏宽 / 屏高；投影方案里对应墙宽 / 墙高
FIELD_ALIAS = {"PJ": {"width_mm": "wall_width_mm", "height_mm": "wall_height_mm"}}


def field_of(prop: Proposal, field: str) -> str:
    return FIELD_ALIAS.get(prop.business_line, {}).get(field, field)


def compute(db: Session, prop: Proposal) -> tuple[dict, dict | None]:
    rev = prop.revisions[-1]
    rules = latest(db, RuleSetVersion, prop.business_line)
    library = latest(db, ProductLibraryVersion, prop.business_line)
    template = latest(db, TemplateVersion, prop.business_line)
    ready = rev.inputs and not pending(rev)  # 未确认的字段不能进入计算
    overrides = {k: o["value"] for k, o in (rev.overrides or {}).items()}  # 手动覆盖（CR-5）
    result = calculate(rules.content, library.content, rev.inputs, rev.cabinet_id, overrides) if ready else None
    return {"rules": rules, "library": library, "template": template}, result


def client_boq(db: Session, prop: Proposal, used: dict, result: dict | None, edits: dict | None) -> dict | None:
    if not result or not result["rules"]:
        return None
    names = {"proposal_name": prop.name, "project_name": db.get(Project, prop.project_id).name}
    if result.get("faces") and prop.business_line == "LED":  # 多面屏：每面一组（CR-7）
        if not result["multi"]["totals"]:
            return None
        faces = [(f["id"], f"{f['id']} · {f.get('name') or ''}".strip(" ·"), f["boq_context"] | names) for f in result["faces"]]
        return build_multi(used["template"].content, faces, tr("共用", "Shared"), result["values"] | names, multiface.POOLED)
    return build(used["template"].content, result["values"] | names, edits, set(result["manual"]))


def candidates(db: Session, prop: Proposal) -> dict[str, list]:
    """项目文件里认出的候选值，按置信度排（同置信度按文件上传顺序）。"""
    out: dict[str, list] = {}
    for f in db.get(Project, prop.project_id).files:
        for x in f.extracted:
            out.setdefault(field_of(prop, x.field), []).append(
                {"id": x.id, "value": x.value, "confidence": x.confidence, "file_id": f.id, "filename": f.filename,
                 "location": stored(x.location), "snippet": x.snippet, "crop": bool(x.crop_path)})
    for items in out.values():
        items.sort(key=lambda c: RANK[c["confidence"]])
    return out


def refresh_status(db: Session, prop: Proposal) -> None:
    rev = prop.revisions[-1]
    if pending(rev):
        rev.status = "confirming"
        return
    _, result = compute(db, prop)
    if result and result.get("multi", {}).get("conflicts"):  # 多面屏 S7：资料对不上，选定前不能计算
        rev.status = "confirming"
        return
    complete = result and result["rules"] and not any(r["missing"] or r["error"] for r in result["rules"])
    rev.status = "calculated" if complete else "draft"


BASIS_RULES = ["F3", "F4", "F5", "F6", "F7", "F9"]


def drawing_of(used: dict, result: dict | None, edits: dict | None) -> dict | None:
    """拼接与线路图（CR-3），带计算依据表；和技术方案、DXF 说明栏用同一份数据。"""
    if not result or not result["rules"]:
        return None
    params = {p["name"]: p["value"] for p in used["rules"].content["params"]}
    d = build_drawing(result["values"], result["values"], params, edits, set(result["manual"]))
    if d:
        d["basis"] = [{"item": r["title"], "formula": r["trace"], "rule": r["id"],
                       "result": r["display"] + (tr("（手动）", " (manual)") if r["manual"] else "")}
                      for r in result["rules"] if r["id"] in BASIS_RULES]
    return d


def view(db: Session, prop: Proposal) -> dict:
    rev = prop.revisions[-1]
    used, result = compute(db, prop)
    return {
        "proposal": proposal_out(prop),
        "project": {"id": prop.project_id},
        "rev": {"rev_no": rev.rev_no, "status": rev.status, "inputs": rev.inputs or {}, "cabinet_id": rev.cabinet_id,
                "input_meta": {k: m | ({"location": stored(m["location"])} if m.get("location") else {})
                               for k, m in (rev.input_meta or {}).items()},
                "annotations": rev.annotations or {}},
        "pending": pending(rev),
        "files": [file_out(f) for f in db.get(Project, prop.project_id).files],
        "candidates": candidates(db, prop),
        "rules_version": used["rules"].version,
        "library_version": used["library"].version,
        "template_version": used["template"].version,
        "input_defs": [d | {"label": text(d["label"]), "unit": unit(d.get("unit"))} for d in used["rules"].content["inputs"]],
        "product_fed": LINES[prop.business_line]["product_fed"],
        "result": result,
        "boq": client_boq(db, prop, used, result, rev.boq_edits),
        "drawing": drawing_of(used, result, rev.drawing_edits),
        "overridable": LINES[prop.business_line]["overridable"],
        "overrides": manual_list(rev, result),
        "shapes": multiface.SHAPES[prop.business_line],
        "shape_guess": multiface.guess_shape(prop.business_line, " ".join(
            f.read_text or "" for f in db.get(Project, prop.project_id).files)),
    }


def manual_list(rev, result: dict | None) -> list[dict]:
    """手动覆盖清单（审核时逐项列出）：规则值 → 手动值 · 原因 · 修改人 · 时间。"""
    if not result:
        return []
    out = []
    for r in result["rules"]:
        for ln in r["lines"]:
            if ln.get("manual"):
                o = rev.overrides[ln["name"]]
                out.append({"rule": r["id"], "title": r["title"], "name": ln["name"], "unit": ln.get("unit", ""),
                            "rule_value": ln["rule_value"], "rule_display": ln["rule_display"],
                            "value": ln["value"], "display": ln["display"],
                            "reason": o["reason"], "by": o["by"], "at": o["at"]})
    return out


@router.get("/{proposal_id}")
def read(proposal_id: int, db: Session = Depends(get_db)):
    return view(db, get_proposal(db, proposal_id))


class InputsIn(BaseModel):
    inputs: dict
    cabinet_id: str | None = None


def allowed_inputs(db: Session, prop: Proposal) -> set[str]:
    rules = latest(db, RuleSetVersion, prop.business_line)
    return ({i["name"] for i in rules.content["inputs"]} - set(LINES[prop.business_line]["product_fed"])) | multiface.MULTI_KEYS


def confirmed_by(user: User) -> dict:
    return {"confirmed_by": user.name, "confirmed_at": iso(utcnow())}


@router.put("/{proposal_id}/inputs")
def save_inputs(proposal_id: int, body: InputsIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """手工录入 / 改值：改过的字段记为手填，等于录入人已确认。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    if unknown := set(body.inputs) - allowed_inputs(db, prop):
        raise HTTPException(422, tr("不认识的输入：", "Unknown inputs: ") + ", ".join(sorted(unknown)))
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


def _use(rev, field: str, x: ExtractedField, items: list[dict]) -> None:
    """用文件里认出的值。几份文件读到的值不一样时标 conflict，即使置信度高也要人确认（CR-7 / Phoenix Sea）。"""
    rev.inputs = {**(rev.inputs or {}), field: x.value}
    rev.input_meta = {**(rev.input_meta or {}), field: {
        "source": "file", "confidence": x.confidence, "extracted_id": x.id, "filename": x.source_file.filename,
        "location": x.location, "snippet": x.snippet, "confirmed_by": None,
        "conflict": len({repr(c["value"]) for c in items}) > 1}}


@router.post("/{proposal_id}/fill-from-files")
def fill_from_files(proposal_id: int, _: User = Depends(require_user), db: Session = Depends(get_db)):
    """用文件里认出的值填入还空着的字段（不覆盖已填的值）；medium / low 的要逐项确认。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    allowed = allowed_inputs(db, prop)
    for field, items in candidates(db, prop).items():
        if field in allowed and (rev.inputs or {}).get(field) in (None, "", []):
            _use(rev, field, db.get(ExtractedField, items[0]["id"]), items)
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
    field = field_of(prop, x.field) if x else None
    if x is None or x.source_file.project_id != prop.project_id or field not in allowed_inputs(db, prop):
        raise HTTPException(404, tr("候选值不存在", "Candidate value not found"))
    _use(prop.revisions[-1], field, x, candidates(db, prop)[field])
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
        raise HTTPException(404, tr("这个字段没有待确认的值", "This field has no value awaiting confirmation"))
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


class OverridesIn(BaseModel):
    values: dict[str, float | None]  # 结果名 → 手动值；空 = 恢复规则值
    reason: str = Field("", max_length=500)


@router.put("/{proposal_id}/overrides")
def save_overrides(proposal_id: int, body: OverridesIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """推荐结果手动覆盖（CR-5）：填新值 + 原因（必填）；空值或改回规则值 = 恢复。规则结果本身不改，手动值随 Rev 保存。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    _, result = compute(db, prop)
    if not result or not result["rules"]:
        raise HTTPException(409, tr("还没有计算结果，算完才能手动修改", "No results yet; calculate before overriding"))
    allowed = {n for names in LINES[prop.business_line]["overridable"].values() for n in names}
    if unknown := set(body.values) - allowed:
        raise HTTPException(422, tr("这些结果不能手动修改：", "These results cannot be overridden: ") + ", ".join(sorted(unknown)))
    if any(v is not None and v < 0 for v in body.values.values()):
        raise HTTPException(422, tr("手动值不能小于 0", "A manual value cannot be below 0"))
    rule_value = {ln["name"]: ln.get("rule_value", ln["value"]) for r in result["rules"] for ln in r["lines"]}
    overrides = dict(rev.overrides or {})
    for name, value in body.values.items():
        if value is None or value == rule_value.get(name):
            overrides.pop(name, None)
            continue
        if not body.reason.strip():
            raise HTTPException(422, tr("手动修改要写原因", "A manual change needs a reason"))
        overrides[name] = {"value": _num(value), "reason": body.reason.strip(), "by": user.name, "at": iso(utcnow())}
    rev.overrides = overrides or None
    refresh_status(db, prop)
    db.commit()
    return view(db, prop)


@router.put("/{proposal_id}/boq")
def save_boq(proposal_id: int, body: BoqIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """客户版 BOQ：改描述、规格、数量，或手动添加行。改了数量要写原因，标「手动」；数量改回规则值就恢复。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    used, result = compute(db, prop)
    default = client_boq(db, prop, used, result, None)
    if default is None:
        raise HTTPException(409, tr("还没有计算结果，算完才能改 BOQ", "No results yet; calculate before editing the BOQ"))
    if default.get("readonly"):
        raise HTTPException(409, tr("多面屏的 BOQ 目前只能看，不能改", "A multi-face BOQ is read-only for now"))
    rules = {r["key"]: r for r in default["rows"]}
    old = rev.boq_edits or {}
    stamp = {"by": user.name, "at": iso(utcnow())}

    def stamped(out: dict, prev: dict) -> dict:  # 内容没变就保留原来的修改人和时间
        same = prev.get("by") and {k: v for k, v in prev.items() if k not in ("by", "at")} == out
        return out | ({"by": prev["by"], "at": prev["at"]} if same else stamp)

    rows = {}
    for key, e in body.rows.items():
        if key not in rules:
            raise HTTPException(422, tr("BOQ 里没有这一行", "This row is not in the BOQ"))
        r, out = rules[key], {}
        if e.title is not None and e.title.strip() and e.title.strip() != r["title_default"]:
            out["title"] = e.title.strip()
        specs = None if e.specs is None else [x.strip() for x in e.specs if x.strip()]
        if specs is not None and specs != r["specs_default"]:
            out["specs"] = specs
        if e.qty is not None and _num(e.qty) != r["rule_qty"]:
            if not e.reason.strip():
                raise HTTPException(422, tr(f"「{r['title_default']}」改了数量，要写原因",
                                           f"“{r['title_default']}”: a changed quantity needs a reason"))
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
        raise HTTPException(409, tr("还没有计算结果，算完才能导出 BOQ", "No results yet; calculate before exporting the BOQ"))
    project = db.get(Project, prop.project_id)
    stamp = " · ".join(([] if rev.status == "approved" else ["DRAFT"]) + [
        f"Rev {rev.rev_no}", f"Rules {used['rules'].version}", f"Product library {used['library'].version}",
        f"Template {used['template'].version}"])
    meta = {"title": f"Bill of Quantities · {prop.name}",
            "subtitle": " · ".join(x for x in (project.name, project.client, project.project_no) if x), "stamp": stamp}
    name = f"{safe_name(project.name)}_{safe_name(prop.name)}_BOQ_Rev{rev.rev_no}.xlsx"
    return _file(to_xlsx(boq, meta), name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---- 拼接与线路图（CR-3） ----

class DrawingIn(BaseModel):
    power: dict[str, int] = {}
    data: dict[str, int] = {}


@router.put("/{proposal_id}/drawing")
def save_drawing(proposal_id: int, body: DrawingIn, _: User = Depends(require_user), db: Session = Depends(get_db)):
    """手动调整回路 / 网线分组（随 Rev 保存）；空的 = 恢复自动。改完立即重新校验，超载的标红、不能批准。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    used, result = compute(db, prop)
    auto = drawing_of(used, result, None)
    if auto is None:
        raise HTTPException(409, tr("还没有计算结果，算完才能调整图纸", "No results yet; calculate before adjusting the drawing"))
    ids = {c["id"]: c for c in auto["cabinets"]}
    for kind, n in (("power", len(auto["circuits"])), ("data", len(auto["cables"]))):
        for cid, no in getattr(body, kind).items():
            if cid not in ids or not 1 <= no <= n:
                raise HTTPException(422, tr(f"没有箱体 {cid}，或编号超出 1–{n}", f"No cabinet {cid}, or number outside 1–{n}"))
    rev.drawing_edits = {  # 和自动结果一样的不存
        "power": {k: v for k, v in body.power.items() if v != ids[k]["circuit"]},
        "data": {k: v for k, v in body.data.items() if v != ids[k]["cable"]},
    }
    db.commit()
    return view(db, prop)


def _drawing_export(db: Session, proposal_id: int, lang: str):
    """导出按导出时选的语言（CR-4），图上的校验、计算依据也用这个语言。"""
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    with use(lang):
        used, result = compute(db, prop)
        d = drawing_of(used, result, rev.drawing_edits)
        if d is None:
            raise HTTPException(409, tr("还没有计算结果，算完才能导出图纸", "No results yet; calculate before exporting the drawing"))
        project = db.get(Project, prop.project_id)
        draft = rev.status != "approved"
        stamp = " · ".join([f"Rev {rev.rev_no}", tr("规则 ", "Rules ") + used["rules"].version,
                            tr("产品库 ", "Product library ") + used["library"].version] + (["DRAFT"] if draft else []))
    meta = {"project": f"{project.name} · {prop.name}", "stamp": stamp, "draft": draft, "values": result["values"]}
    base = f"{safe_name(prop.name)}_{{kind}}_Rev{rev.rev_no}{'_DRAFT' if draft else ''}"
    return d, meta, base


def _file(data: bytes | str, name: str, media: str) -> Response:
    """下载文件名：filename* 带中文，filename 给不认 filename* 的浏览器一个纯 ASCII 的名字。"""
    ascii_name = name.encode("ascii", "ignore").decode().replace('"', "") or "download"
    return Response(data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


Lang = Literal["zh", "en"]


@router.get("/{proposal_id}/drawing.svg")
def export_drawing_svg(proposal_id: int, lang: Lang = "zh", layers: str | None = None, db: Session = Depends(get_db)):
    d, meta, base = _drawing_export(db, proposal_id, lang)
    shown = None if layers is None else [x for x in layers.split(",") if x in drawing_export.LAYERS]
    return _file(drawing_export.svg(d, meta, lang, shown), base.format(kind="Drawing") + ".svg", "image/svg+xml")


@router.get("/{proposal_id}/drawing.dxf")
def export_drawing_dxf(proposal_id: int, lang: Lang = "zh", db: Session = Depends(get_db)):
    d, meta, base = _drawing_export(db, proposal_id, lang)
    return _file(drawing_export.dxf(d, meta, lang), base.format(kind="Drawing") + ".dxf", "application/dxf")


@router.get("/{proposal_id}/drawing.dwg")
def export_drawing_dwg(proposal_id: int, request: Request, lang: Lang = "zh", db: Session = Depends(get_db)):
    oda = request.app.state.oda
    if not drawing_export.oda_available(oda):
        raise HTTPException(409, tr("服务器没有装 ODA File Converter，只能导出 DXF；装 ODA 后可导出 DWG",
                                   "ODA File Converter is not installed on the server; DXF only. Install ODA to export DWG"))
    d, meta, base = _drawing_export(db, proposal_id, lang)
    return _file(drawing_export.dwg(drawing_export.dxf(d, meta, lang), oda), base.format(kind="Drawing") + ".dwg",
                 "application/acad")


@router.get("/{proposal_id}/cabinets.xlsx")
def export_cabinets(proposal_id: int, lang: Lang = "zh", db: Session = Depends(get_db)):
    d, meta, base = _drawing_export(db, proposal_id, lang)
    return _file(drawing_export.cabinets_xlsx(d, meta, lang), base.format(kind="Cabinets").replace("_DRAFT", "") + ".xlsx",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/{proposal_id}/drawing.pdf")
def export_drawing_pdf(proposal_id: int, lang: Lang = "zh", db: Session = Depends(get_db)):
    d, meta, base = _drawing_export(db, proposal_id, lang)
    kind = "技术方案" if lang == "zh" else "Technical"
    return _file(drawing_export.pdf(d, meta, d["basis"], lang), base.format(kind=kind) + ".pdf", "application/pdf")
