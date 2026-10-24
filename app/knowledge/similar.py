"""相似以往项目（CR-8）：确认输入时列出 3 个最像的以往项目。只用人确认过的项目记录，按参数打分，再加资料里的关键词；
每一分都写明理由（不用向量模型，结果可以解释）。"""
import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import KbFile, KbProject, Project, Proposal

STOP = {"led", "wall", "screen", "video", "projection", "projector", "project", "proposal", "the", "and", "for"}


def _area(inputs: dict, w: str, h: str) -> float | None:
    faces = inputs.get("faces")
    if faces:
        parts = [(f.get("width_mm") or 0) * (f.get("height_mm") or 0) for f in faces]
        return sum(parts) / 1e6 if all(parts) else None
    return inputs[w] * inputs[h] / 1e6 if inputs.get(w) and inputs.get(h) else None


def _shape(s: str | None) -> str:
    return "flat" if s in (None, "", "single") else s  # 投影的「单面墙」和 LED 的「平面单屏」都当作平面


def _words(*texts: str) -> list[str]:
    """项目名、客户、地点、方案名里的词：英文 3 个字母以上、中文 2 个字以上，去掉太常见的词和方案编号（LED-1、PJ-2）。"""
    found = re.findall(r"[A-Za-z0-9][A-Za-z0-9&\-]{2,}|[一-鿿]{2,}", " ".join(t or "" for t in texts))
    return list(dict.fromkeys(w for w in found if w.casefold() not in STOP and not w.isdigit()
                              and not re.fullmatch(r"(?:LED|PJ)-?\d+", w, re.I)))[:8]


def _hits(db: Session, words: list[str], projects: dict[str, KbProject]) -> dict[str, list[str]]:
    """每个以往项目的资料（含文件夹名）里出现了哪些词。"""
    owner = dict(db.execute(select(KbFile.id, KbFile.project_key).where(KbFile.project_key.is_not(None),
                                                                       KbFile.missing.is_(False))).all())
    out: dict[str, list[str]] = {}
    for w in words:
        like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        keys = {owner[f] for (f,) in db.execute(text("SELECT DISTINCT file_id FROM kb_fts WHERE text LIKE :w ESCAPE '\\'"),
                                                {"w": like}) if f in owner}
        keys |= {k for k in projects if w.casefold() in k.casefold()}
        for k in keys:
            out.setdefault(k, []).append(w)
    return out


def similar(db: Session, prop: Proposal, inputs: dict, limit: int = 3) -> list[dict]:
    projects = {p.key: p for p in db.scalars(select(KbProject).where(KbProject.record.is_not(None),
                                                                    KbProject.missing.is_(False)))
                if p.record["line"] == prop.business_line}
    if not projects:
        return []
    project = db.get(Project, prop.project_id)
    hits = _hits(db, _words(project.name, project.client, project.location, prop.name), projects)
    led = prop.business_line == "LED"
    w, h = ("width_mm", "height_mm") if led else ("wall_width_mm", "wall_height_mm")
    mine = _area(inputs, w, h)
    out = []
    for key, p in projects.items():
        rec, reasons, score = p.record, [], 0.0
        theirs = _area(rec["inputs"], w, h)
        if mine and theirs:
            r = min(mine, theirs) / max(mine, theirs)
            score += 3 * r
            reasons.append({"code": "area", "mine": round(mine, 2), "theirs": round(theirs, 2)})
        if _shape(inputs.get("shape")) == _shape(rec.get("shape")):
            score += 2
            reasons.append({"code": "shape", "shape": _shape(rec.get("shape"))})
        a, b = inputs.get("pixel_pitch_mm"), rec["inputs"].get("pixel_pitch_mm")
        if led and a and b:
            if a == b:
                score += 3
                reasons.append({"code": "pitch_same", "pitch": b})
            elif abs(a - b) / max(a, b) <= 0.25:
                score += 1
                reasons.append({"code": "pitch_near", "mine": a, "theirs": b})
        for field in ("environment", "installation") if led else ("projector",):
            if inputs.get(field) and inputs.get(field) == rec["inputs"].get(field):
                score += 1
                reasons.append({"code": "same", "field": field, "value": inputs[field]})
        for word in hits.get(key, [])[:3]:
            score += 1
            reasons.append({"code": "word", "word": word})
        if score >= 1:
            out.append({"id": p.id, "key": key, "project_no": p.project_no, "score": round(score, 1), "reasons": reasons,
                        "record": {k: rec[k] for k in ("line", "shape", "inputs", "actual")},
                        "standard": p.standard_manual or p.standard_list})
    out = sorted(out, key=lambda x: -x["score"])[:limit]
    for x in out:  # 当时的方案：项目文件夹里的文件，可以直接打开对照
        x["files"] = [{"id": f.id, "name": f.rel_path.rsplit("/", 1)[-1]} for f in db.scalars(
            select(KbFile).where(KbFile.project_key == x["key"], KbFile.missing.is_(False)).order_by(KbFile.rel_path))]
    return out
