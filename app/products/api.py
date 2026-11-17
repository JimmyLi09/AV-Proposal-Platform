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
from .importer import datasheet_values, export_xlsx, import_xlsx
from .library import CATEGORY_LABEL, FIELDS, SCENES, STATUSES, LibraryError, load_reference, load_seed, name, validate

router = APIRouter(prefix="/products")


def ensure_seed(db: Session) -> None:
    for line in FIELDS:
        if db.scalar(select(ProductLibraryVersion.id).where(ProductLibraryVersion.business_line == line)) is None:
            db.add(ProductLibraryVersion(business_line=line, version="v1.0", content=load_seed(line),
                                         reason={"LED": "示例产品，清单 D 组填好后替换"}.get(line, "示例产品，投影清单 v2 填好后替换")))
    db.commit()


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


DATASHEET_TYPES = {"pdf", "jpg", "jpeg", "png", "xlsx", "xlsm", "docx"}


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
    rel = f"datasheets/{uuid.uuid4().hex}/{safe_name(filename)}"
    save_original(state.data_dir, rel, file.file)
    r = read(state.data_dir / rel, state.oda)
    values = datasheet_values(r["chunks"], line, category) if r["chunks"] else {}
    return {"datasheet": filename, "values": values, "ocr": r["method"] == "ocr", "note": text(r["note"]),
            "read": bool(r["chunks"])}
