"""资料库页面接口（CR-8）。学到的内容只是建议：采用后才在目标库生成新版本（产品库、模板）或更新项目记录；
规则参考只记录，不改规则。撤销也是另存新版本，旧版本永不修改。"""
import copy
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text as sql
from sqlalchemy.orm import Session

from ..api import get_db, iso, require_user
from ..i18n import stored, text, tr
from ..models import KbFile, KbItem, KbProject, ProductLibraryVersion, RuleSetVersion, TemplateVersion, User, utcnow
from ..products.library import FIELDS, LibraryError, load_reference
from ..products.library import validate as validate_library
from ..rules.engine import value_names
from ..storage import safe_name, save_original
from ..templates.content import TemplateError
from ..templates.content import validate as validate_template
from ..versions import latest, next_label
from . import learn
from .scan import TYPES, enabled_types, put_setting, refresh, scan, setting, type_dirs

router = APIRouter(prefix="/kb")
KINDS = ("product", "template", "project", "rule")
ACTUAL = {"area_m2": ("面积", "Area"), "circuits": ("回路", "Circuits"), "power_cables": ("电源线", "Power cables"),
          "data_runs": ("数据线（工作）", "Data cables (working)"), "data_cables": ("数据线（含备用）", "Data cables (incl. spare)"),
          "controller_qty": ("控制器", "Controllers"), "spare_modules": ("备用模组", "Spare modules"),
          "projectors": ("投影机", "Projectors"), "video_lines": ("视频线", "Video lines"),
          "control_lines": ("控制线", "Control lines")}


def labels(db: Session, line: str) -> dict[str, str]:
    """项目记录和规则对比里用到的名字 → 当前语言的标签。"""
    out = {i["name"]: text(i["label"]) for i in latest(db, RuleSetVersion, line).content["inputs"]}
    return out | {"projector": tr("投影机型号", "Projector model")} | {k: tr(*v) for k, v in ACTUAL.items()}


def _file(f: KbFile | None) -> dict | None:
    return f and {"id": f.id, "name": f.rel_path.rsplit("/", 1)[-1], "rel_path": f.rel_path, "doc_type": f.doc_type,
                  "missing": f.missing}


@router.get("")
def overview(request: Request, db: Session = Depends(get_db)):
    state = request.app.state
    dirs, types = type_dirs(state.kb_dir), enabled_types(db)
    counts = dict(db.execute(select(KbFile.doc_type, func.count()).where(KbFile.missing.is_(False))
                             .group_by(KbFile.doc_type)).all())
    status = dict(db.execute(select(KbFile.read_status, func.count()).where(KbFile.missing.is_(False))
                             .group_by(KbFile.read_status)).all())
    failed = db.scalars(select(KbFile).where(KbFile.read_status == "failed", KbFile.missing.is_(False)).limit(20))
    return {"folder": str(state.kb_dir), "exists": state.kb_dir.is_dir(), "scan_at": state.kb_scan_at,
            "types": [{"key": t, "folder": dirs[t].name, "enabled": t in types, "files": counts.get(t, 0)} for t in TYPES],
            "counts": {"files": sum(counts.values()), "read": status.get("read", 0), "failed": status.get("failed", 0),
                       "pending": db.scalar(select(func.count()).where(KbItem.status == "pending"))},
            "last_scan": setting(db, "last_scan", None), "progress": state.kb_progress,
            "failed": [_file(f) | {"note": stored(f.read_note)} for f in failed]}


class TypesIn(BaseModel):
    types: list[Literal["projects", "specs", "drawings", "boq", "templates"]]


@router.put("/types")
def set_types(body: TypesIn, request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    put_setting(db, "types", {"types": [t for t in TYPES if t in body.types], "by": user.name})
    db.commit()
    return overview(request, db)


def _start(request: Request, tasks: BackgroundTasks, user: User) -> None:
    if request.app.state.kb_lock.locked():
        raise HTTPException(409, tr("正在扫描，请等这次扫完", "A scan is already running; wait for it to finish"))
    tasks.add_task(scan, request.app.state, user.id)


@router.post("/scan", status_code=202)
def start_scan(request: Request, tasks: BackgroundTasks, user: User = Depends(require_user)):
    _start(request, tasks, user)
    return {"started": True}


@router.post("/upload", status_code=202)
def upload(request: Request, tasks: BackgroundTasks, files: list[UploadFile], doc_type: str = Form(...),
           project: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """上传的文件存进资料库文件夹对应的子文件夹（以往项目要写项目名，存进它的子文件夹），同名不覆盖，另起名字。"""
    if doc_type not in TYPES:
        raise HTTPException(422, tr("资料类型不对", "Unknown document type"))
    if doc_type == "projects" and not project.strip():
        raise HTTPException(422, tr("以往项目要写项目名（例：143-Royal Plaza）", "Past projects need a project name (e.g. 143-Royal Plaza)"))
    root = request.app.state.kb_dir
    folder = type_dirs(root)[doc_type] / (safe_name(project.strip()) if doc_type == "projects" else "")
    for up in files:
        name, n = safe_name(up.filename or "file"), 1
        stem, dot, ext = name.rpartition(".")
        while (folder / name).exists():
            n += 1
            name = f"{stem} ({n}).{ext}" if dot else f"{name} ({n})"
        rel = (folder / name).relative_to(root).as_posix()
        digest, size = save_original(root, rel, up.file)
        db.add(KbFile(rel_path=rel, doc_type=doc_type, size=size, mtime_ns=(root / rel).stat().st_mtime_ns,
                      sha256=digest, uploaded_by=user.id))
    types = enabled_types(db)
    if doc_type not in types:  # 上传了哪类资料，就把这类加进扫描
        put_setting(db, "types", {"types": [t for t in TYPES if t in types or t == doc_type], "by": user.name})
    db.commit()
    _start(request, tasks, user)
    return {"started": True}


@router.get("/search")
def search(q: str = "", doc_type: str | None = None, db: Session = Depends(get_db)):
    """按关键词查所有资料：每个词都要出现（文字或文件名里）。3 个字以上走全文索引，更短的逐行比。"""
    words = q.split()[:6]
    if not words:
        return []
    esc = lambda w: "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"  # noqa: E731
    params = {f"w{i}": esc(w) for i, w in enumerate(words)} | {"t": doc_type}
    cond = " AND ".join(f"(k.text LIKE :w{i} ESCAPE '\\' OR f.rel_path LIKE :w{i} ESCAPE '\\')" for i in range(len(words)))
    kind = " AND f.doc_type = :t" if doc_type else ""
    rows = db.execute(sql(f"SELECT f.id, k.location, k.text FROM kb_fts k JOIN kb_files f ON f.id = k.file_id "
                          f"WHERE f.missing = 0 AND {cond}{kind} LIMIT 50"), params).all()
    named = db.execute(sql(f"SELECT f.id, '' , '' FROM kb_files f WHERE f.missing = 0 AND f.chunks = 0 AND "
                           + " AND ".join(f"f.rel_path LIKE :w{i} ESCAPE '\\'" for i in range(len(words))) + kind),
                       params).all()
    files = {f.id: f for f in db.scalars(select(KbFile).where(KbFile.id.in_({r[0] for r in [*rows, *named]})))}
    out = []
    for fid, location, body in [*rows, *named]:
        flat = re.sub(r"\s+", " ", body or "")
        at = min((i for w in words if (i := flat.lower().find(w.lower())) >= 0), default=0)
        snippet = ("…" if at > 80 else "") + flat[max(at - 80, 0):at + 160] + ("…" if len(flat) > at + 160 else "")
        out.append({"file": _file(files[fid]), "project": files[fid].project_key, "location": location,
                    "snippet": snippet})
    return out


def item_out(db: Session, i: KbItem, names: dict) -> dict:
    p, out = i.payload, {}
    if i.kind == "product":
        fields = {n: label for n, label, _ in FIELDS[i.business_line][p["category"]]}
        out = {"model": p["model"], "from_reference": p["from_reference"],
               "fields": [{"name": f, "label": text(fields[f]), "value": v, "current": p["current"].get(f),
                           "changed": f in p["changes"]} for f, v in p["values"].items()]}
    elif i.kind == "template":
        out = {"original": p["original"], "row": p["row"], "files": len(p["files"])}
    elif i.kind == "project":
        out = {"key": p["project_key"], "record": {k: p["record"][k] for k in ("line", "shape", "inputs", "actual")}}
    elif i.kind == "rule":
        rules = latest(db, RuleSetVersion, i.business_line).content
        title = next((r["title"] for r in rules["rules"] if r["id"] == p["rule_id"]), "")
        out = {"key": p["project_key"], "rule_id": p["rule_id"], "rule_title": text(title), "name": p["name"],
               "rule_value": p["rule_value"], "actual": p["actual"], "rules_version": p["rules_version"]}
    return {"id": i.id, "kind": i.kind, "line": i.business_line, "confidence": i.confidence, "status": i.status,
            "source": _file(i.source_file), "location": i.location, "snippet": i.snippet,
            "decided_by": i.decider.name if i.decider else None, "decided_at": iso(i.decided_at),
            "result": i.result and {k: i.result[k] for k in ("target", "version") if k in i.result},
            "labels": names.get(i.business_line, {}), **out}


@router.get("/items")
def list_items(status: Literal["pending", "decided", "all"] = "pending", db: Session = Depends(get_db)):
    q = select(KbItem).order_by(KbItem.id)
    if status == "pending":
        q = q.where(KbItem.status == "pending")
    elif status == "decided":
        q = q.where(KbItem.status != "pending").order_by(None).order_by(KbItem.decided_at.desc())
    names = {line: labels(db, line) for line in ("LED", "PJ")}
    return [item_out(db, i, names) for i in db.scalars(q)]


def _item(db: Session, item_id: int) -> KbItem:
    i = db.get(KbItem, item_id)
    if i is None:
        raise HTTPException(404, tr("这条内容不存在（可能已在复扫时更新）", "Item not found (it may have been updated by a rescan)"))
    return i


def _slug(title: str, taken: set[str]) -> str:
    words = re.findall(r"[a-z0-9]+", re.sub(r"\{\w+\}", " ", title.lower()))
    base = "_".join(words[:4])[:36] or "row"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}_{n}"
    return key


def adopt_product(db: Session, i: KbItem, user: User) -> dict:
    p, line = i.payload, i.business_line
    base = latest(db, ProductLibraryVersion, line)
    products = copy.deepcopy(base.content["products"])
    product = next((x for x in products if x["id"] == p["product_id"]), None)
    added = product is None
    if added:
        product = next((copy.deepcopy(x) for x in load_reference(line) if x["id"] == p["product_id"]), None)
        if product is None or not p["from_reference"]:
            raise HTTPException(409, tr("产品库里已经没有这个型号", "This model is no longer in the product library"))
        products.append(product)
    before = {f: product.get(f) for f in p["values"]} | {"datasheet": product.get("datasheet")}
    product.update(p["values"])
    name = i.source_file.rel_path.rsplit("/", 1)[-1]
    product["datasheet"] = product.get("datasheet") or name
    content = {**base.content, "products": products}
    try:
        validate_library(content, line)
    except LibraryError as e:
        raise HTTPException(422, str(e))
    v = ProductLibraryVersion(business_line=line, version=next_label(base.version), content=content, created_by=user.id,
                              reason=f"资料库 #{i.id}：{'加入' if added else '更新'} {p['model']}（按规格书 {name} {i.location}）")
    db.add(v)
    return {"target": "products", "version": v.version, "before": before, "added": added}


def undo_product(db: Session, i: KbItem, user: User) -> None:
    base = latest(db, ProductLibraryVersion, i.business_line)
    products = copy.deepcopy(base.content["products"])
    product = next((x for x in products if x["id"] == i.payload["product_id"]), None)
    if product is None:
        return
    if i.result["added"]:
        products.remove(product)
    else:  # 只改回还是采用时那个值的字段；之后有人另外改过的不动
        for f, old in i.result["before"].items():
            if f == "datasheet" or product.get(f) == i.payload["values"][f]:
                product[f] = old
    if products != base.content["products"]:
        db.add(ProductLibraryVersion(business_line=i.business_line, version=next_label(base.version), created_by=user.id,
                                     content={**base.content, "products": products}, reason=f"撤销资料库 #{i.id}"))


def adopt_template(db: Session, i: KbItem, user: User) -> dict:
    line = i.business_line
    base = latest(db, TemplateVersion, line)
    content = copy.deepcopy(base.content)
    key = _slug(i.payload["row"]["title"], {r["key"] for r in content["boq"]["rows"]})
    content["boq"]["rows"].append({"key": key, **i.payload["row"]})
    try:
        validate_template(content, line, value_names(latest(db, RuleSetVersion, line).content))
    except TemplateError as e:
        raise HTTPException(422, str(e))
    name = i.source_file.rel_path.rsplit("/", 1)[-1]
    v = TemplateVersion(business_line=line, version=next_label(base.version), content=content, created_by=user.id,
                        reason=f"资料库 #{i.id}：加入一行（按以往 BOQ {name} {i.location}）")
    db.add(v)
    return {"target": "templates", "version": v.version, "key": key}


def undo_template(db: Session, i: KbItem, user: User) -> None:
    base = latest(db, TemplateVersion, i.business_line)
    content = copy.deepcopy(base.content)
    rows = [r for r in content["boq"]["rows"] if r["key"] != i.result["key"]]
    if len(rows) != len(content["boq"]["rows"]) and rows:
        content["boq"]["rows"] = rows
        db.add(TemplateVersion(business_line=i.business_line, version=next_label(base.version), content=content,
                               created_by=user.id, reason=f"撤销资料库 #{i.id}"))


def _project(db: Session, key: str) -> KbProject:
    p = db.scalar(select(KbProject).where(KbProject.key == key))
    if p is None:
        raise HTTPException(409, tr("资料库里已经没有这个项目", "This project is no longer in the knowledge base"))
    return p


def adopt_project(db: Session, i: KbItem, user: User) -> dict:
    p = _project(db, i.payload["project_key"])
    before = p.record
    p.record, p.record_version, p.record_by, p.record_at = i.payload["record"], p.record_version + 1, user.id, utcnow()
    return {"target": "project", "version": f"v{p.record_version}", "before": before}


def undo_project(db: Session, i: KbItem, user: User) -> None:
    p = _project(db, i.payload["project_key"])
    if p.record == i.payload["record"]:
        p.record, p.record_version, p.record_by, p.record_at = i.result["before"], p.record_version + 1, user.id, utcnow()


ADOPT = {"product": adopt_product, "template": adopt_template, "project": adopt_project,
         "rule": lambda db, i, user: {"target": "rules"}}
UNDO = {"product": undo_product, "template": undo_template, "project": undo_project, "rule": lambda db, i, user: None}
AFTER = {"product": ("product",), "template": ("template",), "project": ("project", "rule"), "rule": ()}


@router.post("/items/{item_id}/{action}")
def decide(item_id: int, action: Literal["adopt", "reject", "undo"], user: User = Depends(require_user),
           db: Session = Depends(get_db)):
    i = _item(db, item_id)
    if action == "undo":
        if i.status == "pending":
            raise HTTPException(409, tr("这条还没有处理", "This item has not been decided yet"))
        if i.status == "adopted":
            UNDO[i.kind](db, i, user)
        i.status, i.decided_by, i.decided_at, i.result = "pending", None, None, None
    else:
        if i.status != "pending":
            raise HTTPException(409, tr("这条已经处理过，要改请先撤销", "Already decided; undo it first"))
        i.result = ADOPT[i.kind](db, i, user) if action == "adopt" else None
        i.status, i.decided_by, i.decided_at = ("adopted" if action == "adopt" else "rejected"), user.id, utcnow()
    db.flush()
    refresh(db, AFTER[i.kind] if action != "reject" else ())
    db.commit()
    db.refresh(i)
    return item_out(db, i, {i.business_line: labels(db, i.business_line)})


def project_out(db: Session, p: KbProject, names: dict) -> dict:
    files = db.scalars(select(KbFile).where(KbFile.project_key == p.key, KbFile.missing.is_(False))
                       .order_by(KbFile.rel_path))
    out = {"id": p.id, "key": p.key, "project_no": p.project_no, "missing": p.missing,
           "record": p.record and {k: p.record[k] for k in ("line", "shape", "inputs", "actual")},
           "record_version": p.record_version, "record_by": p.record_author.name if p.record_author else None,
           "record_at": iso(p.record_at), "files": [_file(f) for f in files],
           "standard": {"manual": p.standard_manual, "list": p.standard_list,
                        "by": p.standard_author.name if p.standard_author else None, "at": iso(p.standard_at)},
           "labels": names.get(p.record["line"], {}) if p.record else {}, "compare": None}
    if p.record and (p.standard_manual or p.standard_list):
        line = p.record["line"]
        rules = latest(db, RuleSetVersion, line)
        out["compare"] = learn.compare(p.record, rules.content, latest(db, ProductLibraryVersion, line).content) | {
            "rules_version": rules.version}
    return out


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    names = {line: labels(db, line) for line in ("LED", "PJ")}
    return [project_out(db, p, names) for p in db.scalars(select(KbProject).where(KbProject.missing.is_(False))
                                                          .order_by(KbProject.key))]


class StandardIn(BaseModel):
    standard: bool


@router.put("/projects/{project_id}/standard")
def set_standard(project_id: int, body: StandardIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    p = db.get(KbProject, project_id)
    if p is None:
        raise HTTPException(404, tr("项目不存在", "Project not found"))
    p.standard_manual, p.standard_by, p.standard_at = body.standard, user.id, utcnow()
    db.flush()
    refresh(db, ("rule",))
    db.commit()
    return project_out(db, p, {line: labels(db, line) for line in ("LED", "PJ")})


@router.get("/references/{line}")
def references(line: str, db: Session = Depends(get_db)):
    """规则页用：已采用的规则参考（以往项目实际数量和规则结果不一样的地方），只作参考。"""
    items = db.scalars(select(KbItem).where(KbItem.kind == "rule", KbItem.business_line == line,
                                            KbItem.status == "adopted").order_by(KbItem.decided_at.desc()))
    return [{"id": i.id, "rule_id": i.payload["rule_id"], "name": i.payload["name"], "key": i.payload["project_key"],
             "rule_value": i.payload["rule_value"], "actual": i.payload["actual"],
             "rules_version": i.payload["rules_version"], "label": labels(db, line).get(i.payload["name"], i.payload["name"]),
             "decided_by": i.decider.name if i.decider else None, "decided_at": iso(i.decided_at)} for i in items]


@router.get("/files/{file_id}")
def download(file_id: int, request: Request, db: Session = Depends(get_db)):
    f = db.get(KbFile, file_id)
    path = request.app.state.kb_dir / f.rel_path if f else None
    if f is None or f.missing or not path.is_file():
        raise HTTPException(404, tr("文件不存在", "File not found"))
    return FileResponse(path, filename=Path(f.rel_path).name, content_disposition_type="inline")
