"""第 6 步：审核关与 Rev 锁定。

提交审核时锁定 6 样东西（确认后的输入、规则版本、产品库版本、BOQ 快照、模板版本、生成的文件），
审核中、已批准都不能修改；批准可以自审，记录审核人和时间；退回要写原因，解锁回到已计算；
锁定的 Rev 永远用锁定时的版本，不跟着新的规则、产品库、模板变。

CR-9：只有正式版本能提交（草稿先在 05 / 06 保存为正式版本）；再次提交会替换还在等待的那条提交；
提交过的版本再改，自动开下一个草稿（app/workspace.py · editable），不再需要「开新 Rev」。
"""
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import deck, proposal_doc
from . import workspace as ws
from .api import current_user, get_db, iso, require_user
from .i18n import current, tr, use
from .models import Project, Proposal, Revision, User, utcnow
from .storage import safe_name

router = APIRouter(prefix="/proposals")
_log = ws._log


def blockers(rev: Revision, out: dict, inputs: bool = True) -> list[str]:
    """提交审核前必须清掉的问题。inputs = False：不算 04 的待确认字段（05 → 06 的关卡，见 app/flow.py）。"""
    items = []
    if inputs and out["pending"]:
        items.append(tr(f"还有 {len(out['pending'])} 个字段待确认", f"{len(out['pending'])} fields still need confirming"))
    result = out["result"]
    if rev.status not in ("calculated", *ws.LOCKED) or not result:
        items.append(tr("还没有算完（有缺少的输入或计算出错）", "Not fully calculated (missing inputs or a calculation error)"))
        return items
    if block := (result.get("recommendation") or {}).get("block"):
        items.append(block)
    for r in result.get("rules") or []:
        if r.get("check") == "BLOCK":
            items.append(f"{r['id']} {r['title']}")
    for c in (result.get("multi") or {}).get("checks") or []:
        if c.get("check") == "BLOCK":
            items.append(c["text"])
    if (out.get("drawing") or {}).get("blocked"):
        items.append(tr("图纸有超载的回路或网线", "The drawing has an overloaded circuit or data cable"))
    return items


def _plain(x):
    return json.loads(json.dumps(x, default=str))


def snapshot(db: Session, prop: Proposal, rev: Revision, out: dict) -> dict:
    used = ws.used_versions(db, prop, rev)
    return {
        "rules_id": used["rules"].id, "rules_version": used["rules"].version,
        "library_id": used["library"].id, "library_version": used["library"].version,
        "template_id": used["template"].id, "template_version": used["template"].version,
        "inputs": rev.inputs, "cabinet_id": rev.cabinet_id, "overrides": rev.overrides,
        "values": _plain(out["result"]["values"]),
        "boq": _plain(out["boq"]),
        "files": [],  # 生成的文件：正式导出时记在这里
    }


def rev_out(rev: Revision, latest: bool) -> dict:
    from .flow import returned, version_label_of
    L = rev.locked or {}
    return {"rev_no": rev.rev_no, "status": rev.status, "latest": latest, "draft": rev.saved_at is None,
            "label": f"v{rev.rev_no}" + tr("（草稿）", " (draft)") if rev.saved_at is None else version_label_of(rev),
            "returned": returned(rev), "saved_by": rev.saver.name if rev.saver else None, "saved_at": iso(rev.saved_at),
            "author": rev.author.name, "created_at": iso(rev.created_at),
            "reviewer": rev.reviewer.name if rev.reviewer else None, "reviewed_at": iso(rev.reviewed_at),
            "rules_version": L.get("rules_version"), "library_version": L.get("library_version"),
            "template_version": L.get("template_version")}


def review_view(db: Session, prop: Proposal, rev: Revision, out: dict) -> dict:
    latest = rev is prop.revisions[-1]
    snap_ok = True
    if rev.locked and out["result"]:  # 锁定的 Rev 用锁定的版本重算，结果必须和锁定时一样
        snap_ok = _plain(out["result"]["values"]) == rev.locked["values"]
    return {
        "revisions": [rev_out(r, r is prop.revisions[-1]) for r in reversed(prop.revisions)],
        "viewing_latest": latest,
        "readonly": not latest,  # 最新的正式版本也能改：一改就自动开下一个草稿（CR-9）
        "blockers": [] if rev.status in ws.LOCKED else blockers(rev, out),
        "history": [h | {"note": h["note"].get(current(), h["note"]["zh"]) if isinstance(h["note"], dict) else h["note"]}
                    for h in rev.history or []],
        "reviewer": rev.reviewer.name if rev.reviewer else None,
        "reviewed_at": iso(rev.reviewed_at),
        "locked": {k: rev.locked[k] for k in ("rules_version", "library_version", "template_version", "files")}
        if rev.locked else None,
        "snapshot_ok": snap_ok,
        "deck": deck.settings_view(prop.business_line, deck.sections_of(out), rev.deck,
                                   deck.cover_defaults(db.get(Project, prop.project_id), prop, rev)),
    }


class NoteIn(BaseModel):
    note: str = Field("", max_length=1000)


@router.post("/{proposal_id}/submit")
def submit(proposal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """提交审核：只有正式版本能提交（草稿先在 05 / 06 保存）；没有待确认字段、没有阻断项才能提交；提交时锁定。
    还有别的版本在等审批的，这次提交替换它（CR-9）。"""
    from .flow import formal, is_dirty
    prop = ws.get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    if rev.saved_at is None:
        if is_dirty(prop) or formal(prop, rev) is None:
            raise HTTPException(409, tr("当前是草稿。先回 05 或 06 点「下一步」保存为正式版本，才能提交",
                                       "This is a draft. Go back to 05 or 06 and click Next to save an official version before submitting"))
        db.delete(rev)  # 和正式版本一样的草稿：不留，提交那个正式版本
        db.flush()
        db.refresh(prop)
        rev = prop.revisions[-1]
    if rev.status in ws.LOCKED:
        raise HTTPException(409, tr(f"v{rev.rev_no} 已经提交过", f"v{rev.rev_no} has already been submitted"))
    ws.refresh_status(db, prop, rev)
    out = ws.view(db, prop, rev)
    if items := blockers(rev, out):
        raise HTTPException(409, tr("还不能提交审核：", "Cannot submit for review yet: ") + "；".join(items))
    for old in prop.revisions:
        if old.status == "review":  # 再次提交替换还在等待的那条
            old.locked, old.status = None, "draft"
            _log(old, "replaced", user, {"zh": f"被 v{rev.rev_no} 替换", "en": f"Replaced by v{rev.rev_no}"})
            ws.refresh_status(db, prop, old)
    rev.locked = snapshot(db, prop, rev, out)
    rev.status = "review"
    _log(rev, "submit", user)
    prop.reached, prop.updated_at, prop.editor = 4, utcnow(), user
    db.commit()
    return ws.view(db, prop, rev)


def _in_review(prop: Proposal) -> Revision:
    rev = next((r for r in prop.revisions if r.status == "review"), None)
    if rev is None:
        raise HTTPException(409, tr("没有在等审批的版本", "No version is waiting for approval"))
    return rev


@router.post("/{proposal_id}/approve")
def approve(proposal_id: int, body: NoteIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """批准（可以自审）：记录审核人和时间。批准后才能正式导出。"""
    prop = ws.get_proposal(db, proposal_id)
    rev = _in_review(prop)
    rev.status, rev.reviewer_id, rev.reviewed_at = "approved", user.id, utcnow()
    _log(rev, "approve", user, body.note.strip())
    prop.updated_at, prop.editor = utcnow(), user
    db.commit()
    return ws.view(db, prop, rev)


@router.post("/{proposal_id}/send-back")
def send_back(proposal_id: int, body: NoteIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """退回：必须写原因；解锁，回到已计算，按最新的规则、产品库、模板重算。"""
    if not body.note.strip():
        raise HTTPException(422, tr("退回要写原因", "Sending back needs a reason"))
    prop = ws.get_proposal(db, proposal_id)
    rev = _in_review(prop)
    rev.locked, rev.status = None, "draft"
    _log(rev, "send_back", user, body.note.strip())
    ws.refresh_status(db, prop, rev)
    prop.reached, prop.updated_at, prop.editor = min(prop.reached, 3), utcnow(), user  # 改完在 05 / 06 保存新版本再提交
    db.commit()
    return ws.view(db, prop, rev)


def _display(v) -> str:
    if v is None or v == "" or v == []:
        return "—"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


@router.get("/{proposal_id}/compare")
def compare(proposal_id: int, a: int, b: int, db: Session = Depends(get_db)):
    """Rev 对比：版本、输入、计算结果、客户版 BOQ，只列不一样的地方。"""
    prop = ws.get_proposal(db, proposal_id)
    va, vb = (ws.view(db, prop, ws.get_rev(prop, n)) for n in (a, b))

    versions = [{"item": label, "a": va[k], "b": vb[k]} for k, label in (
        ("rules_version", tr("规则", "Rules")), ("library_version", tr("产品库", "Product library")),
        ("template_version", tr("模板", "Template"))) if va[k] != vb[k]]

    labels = {d["name"]: d["label"] for d in va["input_defs"] + vb["input_defs"]}
    ia, ib = va["rev"]["inputs"], vb["rev"]["inputs"]
    inputs = [{"item": labels.get(k, k), "a": _display(ia.get(k)), "b": _display(ib.get(k))}
              for k in sorted(set(ia) | set(ib), key=lambda k: list(labels).index(k) if k in labels else 999)
              if ia.get(k) != ib.get(k)]

    def lines(v):
        return {(r["id"], ln["name"]): (r["title"], f"{ln['display']} {ln.get('unit', '')}".strip()
                                        + (tr("（手动）", " (manual)") if ln.get("manual") else ""))
                for r in ((v["result"] or {}).get("rules") or []) for ln in r["lines"]}
    la, lb = lines(va), lines(vb)
    results = [{"rule": k[0], "item": (la.get(k) or lb.get(k))[0], "name": k[1],
                "a": la[k][1] if k in la else "—", "b": lb[k][1] if k in lb else "—"}
               for k in list(la) + [k for k in lb if k not in la] if la.get(k, (0, None))[1] != lb.get(k, (0, None))[1]]

    def rows(v):
        return {r["key"]: r for r in ((v["boq"] or {}).get("rows") or [])}
    ra, rb = rows(va), rows(vb)
    boq = []
    for k in list(ra) + [k for k in rb if k not in ra]:
        x, y = ra.get(k), rb.get(k)
        specs = bool(x and y and x.get("specs") != y.get("specs"))  # 规格行不一样时把规格也列出来

        def show(r):
            return "—" if not r else f"{r['qty']} {r['unit']} · {r['title']}" + (" · " + "; ".join(r.get("specs") or []) if specs else "")
        if show(x) != show(y):
            boq.append({"item": (x or y)["title"], "a": show(x), "b": show(y)})
    return {"a": a, "b": b, "versions": versions, "inputs": inputs, "results": results, "boq": boq}


# ---- 方案文档输出：PDF、Word、JPG Boards ----

FORMATS = {
    "pdf": ("Proposal", "pdf", "application/pdf", proposal_doc.pdf),
    "docx": ("Proposal", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", proposal_doc.docx),
    "boards": ("Boards", "zip", "application/zip", proposal_doc.boards),
    "pptx": ("Deck", "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", None),
}


def export_file(db: Session, request: Request, prop: Proposal, rev: Revision, kind: str, lang: str, render,
                user: User | None, name: str | None = None, media: str | None = None):
    """没批准：每次按当前内容生成草稿（带 DRAFT）。已批准：第一次导出时生成并存进资料目录，记进 Rev 锁定的「生成的文件」，
    之后同一个 Rev、同一种格式和语言一律给这一份，永不重新生成。BOQ Excel、DXF 自己定文件名（name）。"""
    label, ext, default_media, _ = FORMATS.get(kind, (kind, kind, "application/octet-stream", None))
    media = media or default_media
    project = db.get(Project, prop.project_id)
    approved = rev.status == "approved"
    name = name or (f"{safe_name(project.name)}_{safe_name(prop.name)}_{label}_{lang.upper()}_Rev{rev.rev_no}"
                    f"{'' if approved else '_DRAFT'}.{ext}")
    data_dir = request.app.state.data_dir
    if approved:
        hit = next((f for f in rev.locked.get("files") or [] if f["kind"] == kind and f["lang"] == lang), None)
        if hit and (data_dir / hit["path"]).exists():
            return ws._file((data_dir / hit["path"]).read_bytes(), hit["name"], media)
    data = render()
    if approved:
        rel = f"derived/proposals/{prop.id}/rev{rev.rev_no}/{name}"
        (data_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (data_dir / rel).write_bytes(data)
        entry = {"kind": kind, "lang": lang, "name": name, "path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                 "size": len(data), "by": user.name if user else None, "at": iso(utcnow())}
        rev.locked = {**rev.locked, "files": [*(rev.locked.get("files") or []), entry]}
        db.commit()
    return ws._file(data, name, media)


class DeckIn(BaseModel):
    cover: dict[Literal[tuple(deck.COVER_FIELDS)], str] = {}
    off: list[str] = Field(default_factory=list, max_length=20)


@router.put("/{proposal_id}/deck")
def save_deck(proposal_id: int, body: DeckIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """演示稿设置随 Rev 保存：封面字段（空 = 用默认值）和勾掉的页；封面和最后一页不能勾掉。"""
    prop = ws.get_proposal(db, proposal_id)
    rev = ws.editable(db, prop, user)
    if bad := set(body.off) & deck.FIXED or set(body.off) - set(deck.SLIDES[prop.business_line]):
        raise HTTPException(422, tr("这些页不能勾掉：", "These slides cannot be left out: ") + ", ".join(sorted(bad)))
    cover = {k: v.strip()[:200] for k, v in body.cover.items() if v.strip()}
    rev.deck = {"cover": cover, "off": sorted(set(body.off))} if cover or body.off else None
    db.commit()
    return ws.view(db, prop, rev)


@router.get("/{proposal_id}/proposal.pptx")
def export_deck(proposal_id: int, request: Request, lang: Literal["zh", "en", "bi"] = "en", rev: int | None = None,
                user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    """方案演示稿 PPT（16:9，原生文本框和表格）。lang = bi：中英双语（英文为主，标题带中文）。"""
    prop = ws.get_proposal(db, proposal_id)
    r = ws.get_rev(prop, rev)
    data_dir = request.app.state.data_dir
    doc = proposal_doc.content(db, prop, r, "en" if lang == "bi" else lang, data_dir)
    other = proposal_doc.content(db, prop, r, "zh", data_dir) if lang == "bi" else None
    with use("en" if lang == "bi" else lang):
        project = db.get(Project, prop.project_id)
        settings = deck.settings_view(prop.business_line, {s["key"] for s in doc["sections"]}, r.deck,
                                      deck.cover_defaults(project, prop, r))
    render = lambda: deck.build(doc, other, prop.business_line, settings, lang, r.author.name,  # noqa: E731
                                request.app.state.deck_template, lambda svg: proposal_doc._pngs([svg])[0])
    return export_file(db, request, prop, r, "pptx", lang, render, user)


@router.get("/{proposal_id}/proposal.{fmt}")
def export_proposal(proposal_id: int, fmt: Literal["pdf", "docx", "boards"], request: Request,
                    lang: Literal["zh", "en"] = "zh", rev: int | None = None,
                    user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    prop = ws.get_proposal(db, proposal_id)
    r = ws.get_rev(prop, rev)
    doc = proposal_doc.content(db, prop, r, lang, request.app.state.data_dir)
    return export_file(db, request, prop, r, fmt, lang, lambda: FORMATS[fmt][3](doc), user)
