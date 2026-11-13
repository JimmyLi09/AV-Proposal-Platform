"""CR-9 方案流程，和 PM Platform 的 AV 流程对齐：01 立项询价 → 02–04 图纸 · 解析 · 校核 → 05 方案配置 → 06 图纸与 BOQ → 07 审批与导出。

步骤条（项目页顶上）和 AV 工作台问的是同一个问题——这个方案走到了哪一步、卡在哪里——所以只在这里算一次。
- 草稿与正式版本：编辑都自动存在最新的草稿 Rev 上；在 05 / 06 点「下一步」时，草稿和最近的正式版本不一样，
  要先「保存为正式版本 vN」；正式版本内容不再改，再改就自动开下一个草稿（app/workspace.py · editable）。
- 04 → 05：点「下一步」把确认后的输入带进 05（Rev.pulled）；之后 04 再改，05 不静默跟着变，顶部提示是否重新带入。
- 走到过的最远一步记在 Proposal.reached（0 = 01 … 4 = 07）；锁住的步骤点不进去，「下一步」不能走时写原因。
"""
import copy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import workspace as ws
from .api import get_db, iso, require_user
from .i18n import tr
from .models import Project, Proposal, Revision, User, utcnow
from .rules.engine import calculate
from .versions import latest

router = APIRouter()

STEPS = ("01", "02-04", "05", "06", "07")
APPROVED = 5  # 工作台：已批准，不计入 5 个阶段


def formal(prop: Proposal, before: Revision | None = None) -> Revision | None:
    """最近的正式版本（before 之前的）。"""
    revs = [r for r in prop.revisions if r.saved_at is not None and (before is None or r.rev_no < before.rev_no)]
    return revs[-1] if revs else None


def content(rev: Revision) -> dict:
    return {k: getattr(rev, k) for k in ws.COPIED}


def is_dirty(prop: Proposal) -> bool:
    """最新的是草稿，而且和最近的正式版本不一样（还没有正式版本时：录入过或走到 05 以后就算）。"""
    rev = prop.revisions[-1]
    if rev.saved_at is not None:
        return False
    base = formal(prop, rev)
    return bool(rev.inputs) or prop.reached >= 2 if base is None else content(rev) != content(base)


def returned(rev: Revision) -> bool:
    return (rev.history or [{}])[-1].get("action") == "send_back"


def version_label(prop: Proposal) -> str:
    """工作台和顶栏的版本：v2（草稿）/ v1 / v3 待审批 / v4 已批准 / v1 已退回；还没开始做方案的写 —。"""
    rev = prop.revisions[-1]
    if rev.saved_at is not None:
        return version_label_of(rev)
    if is_dirty(prop):
        return f"v{rev.rev_no}" + tr("（草稿）", " (draft)")
    base = formal(prop, rev)
    return version_label_of(base) if base else "—"


def version_label_of(rev: Revision) -> str:
    status = {"review": tr(" 待审批", " pending approval"), "approved": tr(" 已批准", " approved")}.get(rev.status, "")
    return f"v{rev.rev_no}" + (status or (tr(" 已退回", " returned") if returned(rev) else ""))


def info_missing(project: Project) -> list[str]:
    """01 立项必填（和 PM 一样）：项目名、客户、期望交付；业务线建项时就选了。"""
    return [label for key, label in (("name", tr("项目名称", "Project name")), ("client", tr("客户", "Client")),
                                     ("delivery", tr("期望交付", "Expected delivery"))) if not getattr(project, key)]


def stage(prop: Proposal, project: Project) -> int:
    """工作台的阶段（0 = 01 立项中 … 4 = 07 待审批，5 = 已批准）。
    有提交在等审批就是 07；有没保存的草稿最多到 06（要在 05 / 06 保存新版本）；
    还没上传文件、没录入、立项信息又不全的，算立项中。"""
    revs = prop.revisions
    if revs[-1].status == "approved":
        return APPROVED
    if any(r.status == "review" for r in revs):
        return 4
    n = min(prop.reached, 3) if is_dirty(prop) else prop.reached
    if n <= 1 and info_missing(project) and not project.files and not revs[-1].inputs:
        return 0
    return max(n, 1)


def line_label(prop: Proposal, rev: Revision | None = None) -> str:
    inputs = (rev or prop.revisions[-1]).inputs or {}
    multi = inputs.get("shape") not in (None, "", "single")
    if prop.business_line == "PJ":
        return tr("多面投影", "Multi-face projection") if multi else tr("投影", "Projection")
    return tr("多面 LED", "Multi-face LED") if multi else "LED"


# ---- 「下一步」的关卡：不能走时写原因 ----

def _input_label(defs: dict, name: str) -> str:
    return defs.get(name, name)


def gate_inputs(db: Session, prop: Proposal, rev: Revision, out: dict) -> str:
    """02–04 → 05：确认后的输入齐了、没有待确认的字段、尺寸是模组整数倍（选了吸附值）、多面屏几份资料对得上。"""
    if not rev.inputs:
        return tr("先上传图纸或手填尺寸", "Upload drawings or fill in the size first")
    if n := len(ws.pending(rev)):
        return tr(f"还有 {n} 个字段没确认", f"{n} fields not confirmed")
    result = out["result"]
    if rev.pulled and rev.pulled["inputs"] != rev.inputs:  # 04 改过还没带进 05：按现在的输入检查
        used = ws.used_versions(db, prop, rev)
        result = calculate(used["rules"].content, used["library"].content, rev.inputs, rev.cabinet_id)
    if result is None:
        return ""
    defs = {d["name"]: d["label"] for d in out["input_defs"]}
    for name in result.get("choices") or {}:
        return tr(f"{_input_label(defs, name)} {rev.inputs.get(name)} 不是模组整数倍，先选吸附值",
                  f"{_input_label(defs, name)} {rev.inputs.get(name)} is not a module multiple: pick a snap value first")
    if conflicts := (result.get("multi") or {}).get("conflicts"):
        return tr(f"{len(conflicts)} 处尺寸几份资料对不上，先选定", f"{len(conflicts)} sizes differ between sources: pick one first")
    if block := (result.get("recommendation") or {}).get("block"):  # 选不出箱体：说真正的原因，不说「还缺箱体尺寸」
        return block
    names = set((result.get("recommendation") or {}).get("missing") or [])
    names |= {m for r in result.get("rules") or [] for m in r.get("missing") or [] if m in defs}
    if names:
        return tr("还缺：", "Still missing: ") + "、".join(_input_label(defs, n) for n in sorted(names))
    return ""


def overload(drawing: dict | None) -> str:
    if not drawing:
        return ""
    circuits = sum(1 for c in drawing["circuits"] if c["over"])
    cables = sum(1 for c in drawing["cables"] if c["over"])
    parts = []
    if circuits:
        parts.append(tr(f"{circuits} 个回路超出带载，加回路或改参数", f"{circuits} circuits over capacity: add circuits or change parameters"))
    if cables:
        parts.append(tr(f"{cables} 根网线超出带载，加网口或改参数", f"{cables} data cables over capacity: add ports or change parameters"))
    return tr("；", "; ").join(parts)


def gate_design(rev: Revision, out: dict) -> str:
    """05 → 06：算完了，没有阻断（控制器带载、多面屏检查），接线没有超载。
    接线只看自动分组：06 里手动换回路 / 网线造成的超载留在 06 改（标红、06 → 07 走不了、不能批准），不挡 05 → 06。
    否则还没在 05 点过「下一步」就进了 06 的方案，一调超载 06 就被锁住，回到 05 又改不回来。"""
    from .review import blockers
    auto = out.get("drawing_auto", out.get("drawing"))
    if why := overload(auto):
        return why
    items = blockers(rev, out | {"drawing": auto}, inputs=False)  # 04 的待确认字段在 04 提示，不挡 05
    return items[0] if items else ""


def gates(db: Session, prop: Proposal, rev: Revision, out: dict) -> dict[str, str]:
    return {"01": "", "02-04": gate_inputs(db, prop, rev, out), "05": gate_design(rev, out), "06": overload(out.get("drawing")),
            "07": ""}


def steps(prop: Proposal, project: Project, rev: Revision, g: dict) -> list[dict]:
    """步骤条：每段的状态 done / draft / pending / lock / todo 和一句话（why：锁住的原因，鼠标停留时显示）；「当前」由页面自己标。"""
    reached, dirty, last = prop.reached, is_dirty(prop), prop.revisions[-1]
    review = next((r for r in prop.revisions if r.status == "review"), None)
    base = formal(prop)
    todo = lambda i: ("todo", tr("已开始", "Started") if i == reached else tr("未开始", "Not started"))  # noqa: E731
    out = []
    for i, key in enumerate(STEPS):
        why = ""
        if i > reached and i >= 2 and g["02-04"]:
            state, why = "lock", g["02-04"]
            note = tr("04 还有字段没确认", "04 has unconfirmed fields") if ws.pending(rev) else tr("先完成 02–04", "Finish 02–04 first")
        elif i > reached and i >= 3 and g["05"]:
            state, note, why = "lock", tr("先完成 05", "Finish 05 first"), g["05"]
        elif key in ("05", "06") and dirty and i <= reached:
            state, note = "draft", tr("草稿 · 未保存正式版", "Draft · not saved as official")
        elif key == "01":
            missing = info_missing(project)
            state, note = ("draft", tr("缺", "Missing: ") + "、".join(missing)) if missing else ("done", tr("✓ 完成", "✓ Done"))
        elif key == "07":
            state, note = (("done", tr("已批准", "Approved")) if last.status == "approved"
                           else ("pending", tr(f"v{review.rev_no} 待审批", f"v{review.rev_no} pending approval")) if review
                           else ("draft", tr(f"v{base.rev_no} 已退回", f"v{base.rev_no} returned")) if base and returned(base)
                           else todo(i))
        elif key == "02-04" and (n := len(ws.pending(rev))):
            state, note = "pending", tr(f"还有 {n} 个字段没确认", f"{n} fields to confirm")
        else:
            state, note = ("done", tr("✓ 完成", "✓ Done")) if i < reached else todo(i)
        out.append({"key": key, "state": state, "note": note, "why": why})
    return out


def flow_view(db: Session, prop: Proposal, rev: Revision, out: dict) -> dict:
    """项目页要的流程信息：步骤条、各步「下一步」的关卡、版本、自动开草稿、04 有没有新的确认值没带进 05。"""
    project = db.get(Project, prop.project_id)
    g = gates(db, prop, rev, out)
    defs = {d["name"]: d["label"] for d in out["input_defs"]}
    changed = []
    if rev.pulled:
        a, b = rev.pulled["inputs"] or {}, rev.inputs or {}
        changed = [{"name": k, "label": _input_label(defs, k), "from": a.get(k), "to": b.get(k)}
                   for k in sorted(set(a) | set(b), key=lambda k: list(defs).index(k) if k in defs else 999) if a.get(k) != b.get(k)]
    latest_formal = formal(prop)
    upgrades = {}
    if not rev.locked and rev is prop.revisions[-1]:
        for part, (model, col) in ws.VERSIONED.items():
            newest = latest(db, model, prop.business_line)
            if getattr(rev, col) and newest.id != getattr(rev, col):
                upgrades[part] = newest.version
    return {"flow": {
        "steps": steps(prop, project, rev, g), "gates": g, "reached": prop.reached, "stage": stage(prop, project),
        "dirty": is_dirty(prop), "draft": rev.saved_at is None,
        "version": version_label(prop), "next_version": f"v{prop.revisions[-1].rev_no + (0 if prop.revisions[-1].saved_at is None else 1)}",
        "formal": latest_formal.rev_no if latest_formal else None,
        "opened": db.info.get("opened"),
        "pull": {"changed": changed, "ready": not g["02-04"]},
        "upgrades": upgrades,
        "line_label": line_label(prop, rev),
        "updated": {"at": iso(prop.updated_at or prop.created_at), "by": (prop.editor.name if prop.editor else None)},
    }}


# ---- 工作台 ----

@router.get("/workbench")
def workbench(db: Session = Depends(get_db)):
    """AV 工作台：每个方案一行（项目名、编号、客户、业务线、5 段进度、当前步骤、版本、最近更新）和 5 个阶段计数。"""
    rows = []
    for prop in db.scalars(select(Proposal).order_by(Proposal.id.desc())):
        project = db.get(Project, prop.project_id)
        siblings = len(project.proposals)
        rows.append({
            "id": prop.id, "project_id": project.id, "name": project.name + (f" · {prop.name}" if siblings > 1 else ""),
            "project_no": project.project_no, "client": project.client, "lead": project.project_no is None,
            "line": prop.business_line, "line_label": line_label(prop), "stage": stage(prop, project),
            "version": version_label(prop),
            "updated_at": iso(prop.updated_at or prop.created_at), "updated_by": prop.editor.name if prop.editor else None,
        })
    counts = [sum(1 for r in rows if r["stage"] == i) for i in range(5)]
    return {"counts": counts, "rows": rows}


# ---- 「下一步」、带入、升级 ----

class NextIn(BaseModel):
    step: str = Field(pattern="^(01|02-04|05|06)$")  # 从哪一步往下走
    save: bool = False  # 05 / 06：草稿有改动时，确认「保存为正式版本」


def save_version(prop: Proposal, user: User) -> None:
    """保存为正式版本：最新的草稿就是这一版，内容从此不再改。还没从 04 带过输入的，记下现在用的输入。"""
    rev = prop.revisions[-1]
    if rev.pulled is None:
        rev.pulled = copy.deepcopy({"inputs": rev.inputs, "input_meta": rev.input_meta})
    rev.saved_at, rev.saver = utcnow(), user
    ws._log(rev, "saved", user)


@router.post("/proposals/{proposal_id}/next")
def next_step(proposal_id: int, body: NextIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """点「下一步」：先过这一步的关卡；04 → 05 把确认后的输入带进 05；05 / 06 有改动要保存为正式版本 vN，
    没改动的草稿丢掉（不生成新版本）。"""
    prop = ws.get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    out = ws.view(db, prop, rev)
    if why := out["flow"]["gates"][body.step]:
        raise HTTPException(409, why)
    i = STEPS.index(body.step)
    if body.step == "02-04":
        now = {"inputs": rev.inputs, "input_meta": rev.input_meta}
        if rev.pulled != now:
            rev = ws.editable(db, prop, user)
            rev.pulled = copy.deepcopy(now)
            ws.refresh_status(db, prop)
    elif body.step in ("05", "06"):
        if is_dirty(prop):
            if not body.save:
                v = out["flow"]["next_version"]
                raise HTTPException(409, tr(f"有改动，先保存为正式版本 {v}", f"There are changes: save official version {v} first"))
            save_version(prop, user)
            prop.updated_at, prop.editor = utcnow(), user
        elif rev.saved_at is None and formal(prop, rev) is not None:
            db.delete(rev)  # 和正式版本一样的草稿：不留
            db.flush()
            db.refresh(prop)
    prop.reached = max(prop.reached, i + 1)
    db.commit()
    return ws.view(db, prop)


@router.post("/proposals/{proposal_id}/pull")
def pull(proposal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """05 顶部「重新带入」：把 04 现在确认的输入带进 05。04 还有没确认的字段时不能带。"""
    prop = ws.get_proposal(db, proposal_id)
    out = ws.view(db, prop)
    if why := out["flow"]["gates"]["02-04"]:
        raise HTTPException(409, why)
    rev = ws.editable(db, prop, user)
    rev.pulled = copy.deepcopy({"inputs": rev.inputs, "input_meta": rev.input_meta})
    ws.refresh_status(db, prop)
    db.commit()
    return ws.view(db, prop)


@router.post("/proposals/{proposal_id}/keep")
def keep(proposal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """05 顶部「保留当前」：05 不变，04 的输入改回 05 正在用的值。"""
    prop = ws.get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    if not rev.pulled:
        raise HTTPException(409, tr("05 还没带入过输入", "05 has not taken any inputs yet"))
    rev = ws.editable(db, prop, user)
    rev.inputs, rev.input_meta = copy.deepcopy(rev.pulled["inputs"]), copy.deepcopy(rev.pulled["input_meta"])
    ws.refresh_status(db, prop)
    db.commit()
    return ws.view(db, prop)


class UpgradeIn(BaseModel):
    parts: list[str] = Field(default_factory=lambda: list(ws.VERSIONED), min_length=1)


@router.post("/proposals/{proposal_id}/upgrade")
def upgrade(proposal_id: int, body: UpgradeIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """手动升级到最新的规则 / 产品库 / 模板版本（建项时绑定的版本，库更新后不会自动跟着变）。改在草稿上，正式版本不变。"""
    prop = ws.get_proposal(db, proposal_id)
    if bad := set(body.parts) - set(ws.VERSIONED):
        raise HTTPException(422, tr("不认识：", "Unknown: ") + ", ".join(sorted(bad)))
    rev = ws.editable(db, prop, user)
    for part in body.parts:
        model, col = ws.VERSIONED[part]
        setattr(rev, col, latest(db, model, prop.business_line).id)
    ws.refresh_status(db, prop)
    db.commit()
    return ws.view(db, prop)


def project_brief(db: Session, prop: Proposal) -> dict:
    """01 页要的项目资料，和同一项目里的其它方案。"""
    p = db.get(Project, prop.project_id)
    return {"id": p.id, "name": p.name, "client": p.client, "project_no": p.project_no, "location": p.location,
            "delivery": p.delivery, "notes": p.notes,
            "proposals": [{"id": x.id, "name": x.name, "business_line": x.business_line, "line_label": line_label(x),
                           "version": version_label(x)} for x in p.proposals]}

