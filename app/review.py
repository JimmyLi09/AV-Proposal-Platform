"""第 6 步：审核关与 Rev 锁定。

提交审核时锁定 6 样东西（确认后的输入、规则版本、产品库版本、BOQ 快照、模板版本、生成的文件），
审核中、已批准都不能修改；批准可以自审，记录审核人和时间；退回要写原因，解锁回到已计算；
已批准的 Rev 要改就开新 Rev。锁定的 Rev 永远用锁定时的版本，不跟着新的规则、产品库、模板变。
"""
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import proposal_doc
from . import workspace as ws
from .api import current_user, get_db, iso, require_user
from .i18n import current, tr
from .models import Project, Proposal, Revision, User, utcnow
from .storage import safe_name

router = APIRouter(prefix="/proposals")

COPIED = ("inputs", "input_meta", "cabinet_id", "boq_edits", "drawing_edits", "overrides", "annotations")


def _log(rev: Revision, action: str, user: User, note: str = "") -> None:
    rev.history = [*(rev.history or []), {"action": action, "by": user.name, "at": iso(utcnow()), "note": note}]


def blockers(rev: Revision, out: dict) -> list[str]:
    """提交审核前必须清掉的问题。"""
    items = []
    if out["pending"]:
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
    L = rev.locked or {}
    return {"rev_no": rev.rev_no, "status": rev.status, "latest": latest,
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
        "readonly": not latest or rev.status in ws.LOCKED,
        "blockers": [] if rev.status in ws.LOCKED else blockers(rev, out),
        "history": [h | {"note": h["note"].get(current(), h["note"]["zh"]) if isinstance(h["note"], dict) else h["note"]}
                    for h in rev.history or []],
        "reviewer": rev.reviewer.name if rev.reviewer else None,
        "reviewed_at": iso(rev.reviewed_at),
        "locked": {k: rev.locked[k] for k in ("rules_version", "library_version", "template_version", "files")}
        if rev.locked else None,
        "snapshot_ok": snap_ok,
    }


class NoteIn(BaseModel):
    note: str = Field("", max_length=1000)


@router.post("/{proposal_id}/submit")
def submit(proposal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """提交审核：没有待确认字段、没有阻断项才能提交；提交时锁定。"""
    prop = ws.get_proposal(db, proposal_id)
    rev = ws.editable(prop)
    ws.refresh_status(db, prop)
    out = ws.view(db, prop, rev)
    if items := blockers(rev, out):
        raise HTTPException(409, tr("还不能提交审核：", "Cannot submit for review yet: ") + "；".join(items))
    rev.locked = snapshot(db, prop, rev, out)
    rev.status = "review"
    _log(rev, "submit", user)
    db.commit()
    return ws.view(db, prop, rev)


def _in_review(prop: Proposal) -> Revision:
    rev = prop.revisions[-1]
    if rev.status != "review":
        raise HTTPException(409, tr("这个 Rev 不在审核中", "This Rev is not in review"))
    return rev


@router.post("/{proposal_id}/approve")
def approve(proposal_id: int, body: NoteIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """批准（可以自审）：记录审核人和时间。批准后才能正式导出。"""
    prop = ws.get_proposal(db, proposal_id)
    rev = _in_review(prop)
    rev.status, rev.reviewer_id, rev.reviewed_at = "approved", user.id, utcnow()
    _log(rev, "approve", user, body.note.strip())
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
    ws.refresh_status(db, prop)
    db.commit()
    return ws.view(db, prop, rev)


@router.post("/{proposal_id}/revisions", status_code=201)
def new_revision(proposal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """从已批准的 Rev 开新 Rev：复制输入、手动修改、BOQ / 图纸调整和标注，按最新版本重新计算。"""
    prop = ws.get_proposal(db, proposal_id)
    base = prop.revisions[-1]
    if base.status != "approved":
        raise HTTPException(409, tr("只有已批准的 Rev 才能开新 Rev；现在这个 Rev 还可以直接改",
                                   "A new Rev starts from an approved Rev; this Rev can still be edited directly"))
    rev = Revision(proposal_id=prop.id, rev_no=base.rev_no + 1, author_id=user.id,
                   **{k: getattr(base, k) for k in COPIED})
    db.add(rev)
    _log(rev, "created", user, {"zh": f"从 Rev {base.rev_no} 开新 Rev", "en": f"Started from Rev {base.rev_no}"})
    db.flush()
    db.refresh(prop)
    ws.refresh_status(db, prop)
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
}


def export_file(db: Session, request: Request, prop: Proposal, rev: Revision, kind: str, lang: str, render,
                user: User | None):
    """没批准：每次按当前内容生成草稿（带 DRAFT）。已批准：第一次导出时生成并存进资料目录，记进 Rev 锁定的「生成的文件」，
    之后同一个 Rev、同一种格式和语言一律给这一份，永不重新生成。"""
    label, ext, media, _ = FORMATS.get(kind, (kind, kind, "application/octet-stream", None))
    project = db.get(Project, prop.project_id)
    approved = rev.status == "approved"
    name = (f"{safe_name(project.name)}_{safe_name(prop.name)}_{label}_{lang.upper()}_Rev{rev.rev_no}"
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


@router.get("/{proposal_id}/proposal.{fmt}")
def export_proposal(proposal_id: int, fmt: Literal["pdf", "docx", "boards"], request: Request,
                    lang: Literal["zh", "en"] = "zh", rev: int | None = None,
                    user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    prop = ws.get_proposal(db, proposal_id)
    r = ws.get_rev(prop, rev)
    doc = proposal_doc.content(db, prop, r, lang, request.app.state.data_dir)
    return export_file(db, request, prop, r, fmt, lang, lambda: FORMATS[fmt][3](doc), user)
