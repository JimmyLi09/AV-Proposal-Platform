import json
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api import get_db, require_user
from ..i18n import text, tr
from ..models import ProductLibraryVersion, User
from ..storage import safe_name, save_original
from ..versions import check_base, history, latest, next_label, version_out
from .importer import (BATCH_MAX, batch_item, datasheet_values, export_xlsx, import_xlsx, mark_duplicates, table_items,
                       template_xlsx)
from .library import CATEGORY_LABEL, FIELDS, SCENES, STATUSES, LibraryError, load_reference, load_seed, name, validate

router = APIRouter(prefix="/products")


def ensure_seed(db: Session) -> None:
    for line in FIELDS:
        if db.scalar(select(ProductLibraryVersion.id).where(ProductLibraryVersion.business_line == line)) is None:
            db.add(ProductLibraryVersion(business_line=line, version="v1.0", content=load_seed(line),
                                         reason={"LED": "示例产品，清单 D 组填好后替换"}.get(line, "示例产品，投影清单 v2 填好后替换")))
    db.commit()


@router.get("/template.xlsx")
def download_template(db: Session = Depends(get_db)):
    """导入模板（两条业务线 + 说明页）。"""
    data = template_xlsx({line: latest(db, ProductLibraryVersion, line).content for line in FIELDS})
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="product-import-template.xlsx"'})


@router.get("/{line}")
def get_latest(line: str, db: Session = Depends(get_db)):
    v = latest(db, ProductLibraryVersion, line)
    fields = {cat: [{"name": n, "label": text(label), "type": kind} for n, label, kind in fs]
              for cat, fs in FIELDS[line].items()}
    categories = {k: text(label) for k, label in CATEGORY_LABEL.items()}
    return version_out(v) | {"fields": fields, "categories": categories, "statuses": STATUSES, "scenes": SCENES}


@router.get("/{line}/versions")
def list_versions(line: str, db: Session = Depends(get_db)):
    latest(db, ProductLibraryVersion, line)
    return [version_out(v, content=False) for v in history(db, ProductLibraryVersion, line)]


class SaveIn(BaseModel):
    base_id: int
    reason: str = Field(min_length=1, max_length=500)
    content: dict


@router.post("/{line}", status_code=201)
def save_version(line: str, body: SaveIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    base = latest(db, ProductLibraryVersion, line)
    check_base(base, body.base_id, body.content)
    try:
        validate(body.content, line)
    except LibraryError as e:
        raise HTTPException(422, str(e))
    except (KeyError, TypeError, AttributeError):
        raise HTTPException(422, tr("产品库内容格式不对", "Product library content is malformed"))
    v = ProductLibraryVersion(business_line=line, version=next_label(base.version), content=body.content,
                              reason=body.reason.strip(), created_by=user.id)
    db.add(v)
    db.commit()
    return version_out(v)


class ReferenceIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)


@router.post("/{line}/reference", status_code=201)
def add_reference(line: str, body: ReferenceIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """把参考型号表里的建议型号加进产品库（另存新版本）。数值仍标示例值，等按规格书核实。"""
    ref = next((p for p in load_reference(line) if p["id"] == body.id), None)
    if ref is None:
        raise HTTPException(404, tr("参考型号表里没有这个型号", "This model is not in the reference table"))
    base = latest(db, ProductLibraryVersion, line)
    if any(p["id"] == ref["id"] for p in base.content["products"]):
        raise HTTPException(409, ref["model"] + tr(" 已经在产品库里", " is already in the product library"))
    content = {**base.content, "products": [*base.content["products"], ref]}
    validate(content, line)
    v = ProductLibraryVersion(business_line=line, version=next_label(base.version), content=content,
                              reason=f"加入建议型号 {name(ref)}（参考型号表，数值待核对规格书）", created_by=user.id)
    db.add(v)
    db.commit()
    return version_out(v)


# ---- 导入文件（2026-11-17）：Excel 批量导入 / 导出，规格书读参数 ----

@router.get("/{line}/excel")
def download_excel(line: str, db: Session = Depends(get_db)):
    v = latest(db, ProductLibraryVersion, line)
    return Response(export_xlsx(v.content, line),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="products-{line}-{v.version}.xlsx"'})


@router.post("/{line}/excel")
async def upload_excel(line: str, file: UploadFile = File(...), content: str = Form(...),
                       user: User = Depends(require_user), db: Session = Depends(get_db)):
    """把 Excel 合并进界面上的草稿（content），返回合并后的产品和每行的问题；不保存。"""
    latest(db, ProductLibraryVersion, line)
    try:
        return import_xlsx(await file.read(), json.loads(content), line)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as e:  # 不是 xlsx、文件损坏
        raise HTTPException(422, tr(f"读不了这个 Excel：{type(e).__name__}", f"Cannot read this Excel: {type(e).__name__}"))


DATASHEET_TYPES = {"pdf", "jpg", "jpeg", "png", "xlsx", "xlsm", "xls", "docx"}


@router.post("/{line}/datasheet")
def read_datasheet(line: str, request: Request, file: UploadFile = File(...), category: str = Form(...),
                   user: User = Depends(require_user)):
    """读一份规格书：原件复制存档（只读），返回认出的参数和原文，由人勾选后填进产品。"""
    from ..knowledge.read import read

    if category not in FIELDS.get(line, {}):
        raise HTTPException(422, tr("类别不对", "Wrong category"))
    filename = (file.filename or "datasheet").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    kind = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if kind not in DATASHEET_TYPES:
        raise HTTPException(422, tr("规格书请用 PDF、图片、Excel 或 Word", "Use a PDF, image, Excel or Word datasheet"))
    state = request.app.state
    r = read(_archive(state, filename, file.file), state.oda)
    values = datasheet_values(r["chunks"], line, category) if r["chunks"] else {}
    return {"datasheet": filename, "values": values, "ocr": r["method"] == "ocr", "note": text(r["note"]),
            "read": bool(r["chunks"])}


def _archive(state, filename: str, fh):
    """规格书原件复制存档（只读）。"""
    rel = f"datasheets/{uuid.uuid4().hex}/{safe_name(filename)}"
    save_original(state.data_dir, rel, fh)
    return state.data_dir / rel


def _kind(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _batch(request: Request, db: Session, line: str, sources: list[tuple[str, object]]) -> dict:
    """sources: [(文件名, 打开的文件)]。每份读一遍，列成复核表，不改产品库。"""
    from ..knowledge.read import read

    if not sources:
        raise HTTPException(422, tr("请选文件", "Choose files"))
    if len(sources) > BATCH_MAX:
        raise HTTPException(422, tr(f"一次最多 {BATCH_MAX} 份", f"At most {BATCH_MAX} files at a time"))
    products = latest(db, ProductLibraryVersion, line).content["products"]
    taken = {p["id"] for p in products}
    items, skipped, errors = [], [], []
    state = request.app.state
    for filename, fh in sources:
        if _kind(filename) not in DATASHEET_TYPES:
            skipped.append(filename)
            continue
        path = _archive(state, filename, fh)
        table = table_items(path.read_bytes(), line, products, filename) if _kind(filename) in ("xlsx", "xlsm") else None
        if table is not None:  # 按模板填的产品表：一行一个产品
            items += table[0]
            errors += table[1]
        else:
            items.append(batch_item(line, filename, read(path, state.oda), products, taken))
    mark_duplicates(items)
    return {"items": items, "skipped": skipped, "errors": errors}


@router.post("/{line}/datasheets")
def batch_upload(line: str, request: Request, files: list[UploadFile] = File(...),
                 user: User = Depends(require_user), db: Session = Depends(get_db)):
    """规格书批量导入：从电脑上传多份。"""
    return _batch(request, db, line, [((f.filename or "file").replace("\\", "/").rsplit("/", 1)[-1], f.file) for f in files])


class ServerFiles(BaseModel):
    paths: list[str]


@router.post("/{line}/datasheets/server")
def batch_server(line: str, body: ServerFiles, request: Request,
                 user: User = Depends(require_user), db: Session = Depends(get_db)):
    """规格书批量导入：直接读服务器文件夹（project_import_dir）里的文件，原文件不动。"""
    from ..server_import import server_file

    paths = [server_file(request, rel) for rel in body.paths]
    handles = [open(p, "rb") for p in paths]
    try:
        return _batch(request, db, line, [(p.name, h) for p, h in zip(paths, handles)])
    finally:
        for h in handles:
            h.close()
