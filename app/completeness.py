"""资料齐全度（第 8 步 · 投影）：确认输入里勾选拿到了哪些图（平面图、立面图、剖面图、天花图 RCP）。

A 级：四种都有；B 级：平面图、立面图都有，缺剖面图或天花图；C 级：缺平面图或立面图。
不是 A 级时，模板里「加入条件 = missing_drawings」的条款自动加进风险与假设，写明缺哪些图、哪些数是手填的。
不影响任何数量；没勾选的不算。
"""
from .i18n import current, tr

DOCS = [  # 输入名、图、缺了它哪些数只能手填
    ("doc_plan", lambda: tr("平面图", "plan drawing"), lambda: [tr("可用进深", "available depth"), tr("信号距离", "signal distance")]),
    ("doc_elevation", lambda: tr("立面图", "elevation drawing"), lambda: [tr("墙面尺寸", "wall size")]),
    ("doc_section", lambda: tr("剖面图", "section drawing"), lambda: [tr("天花高度", "ceiling height"), tr("镜头高度", "lens height")]),
    ("doc_rcp", lambda: tr("天花图（RCP）", "ceiling plan (RCP)"), lambda: [tr("吊点位置", "fixing points")]),
]


def completeness(inputs: dict | None) -> dict | None:
    inputs = inputs or {}
    if not any(inputs.get(name) in ("yes", "no") for name, _, _ in DOCS):
        return None
    missing = [(name, label(), affected()) for name, label, affected in DOCS if inputs.get(name) == "no"]
    names = {m[0] for m in missing}
    grade = "C" if names & {"doc_plan", "doc_elevation"} else "B" if names else "A"
    sep = "、" if current() == "zh" else ", "
    return {"grade": grade, "missing": [m[1] for m in missing], "affected": [a for m in missing for a in m[2]],
            "missing_drawings": sep.join(m[1] for m in missing), "affected_items": sep.join(a for m in missing for a in m[2])}
