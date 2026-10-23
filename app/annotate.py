"""PDF / JPG 标注：在客户的图纸或照片上标出位置，另存一份标注副本，原件不动。

标记坐标用 0–1 的相对位置（与图片分辨率无关）。设置比例：两点 + 实际距离（mm），区域标记会算出近似尺寸。
"""
import math
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .api import get_db, iso, require_user
from .i18n import tr
from .models import SourceFile, User, utcnow
from .workspace import get_proposal

router = APIRouter()
IMAGE_TYPES = {"jpg", "jpeg", "png"}
PAGE_SIDE_PX = 2000  # PDF 页面渲染成图片时的最长边
FONTS = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
ORANGE, NAVY, WHITE = (194, 65, 12), (21, 32, 58), (255, 255, 255)
TYPE_LABEL = {"point": lambda: tr("点", "Point"), "area": lambda: tr("区域", "Area"),
              "device": lambda: tr("设备", "Device"), "text": lambda: tr("文字", "Text")}


def page_count(state, f: SourceFile) -> int:
    if f.file_type in IMAGE_TYPES:
        return 1
    if f.file_type == "pdf":
        import pdfplumber
        with pdfplumber.open(state.data_dir / f.stored_path) as pdf:
            return len(pdf.pages)
    return 0


def base_image(state, f: SourceFile, page: int) -> Path:
    """标注用的底图（副本）：照片按 EXIF 摆正，PDF 页面渲染成图片。缓存在 derived 目录。"""
    out = state.data_dir / "derived" / str(f.id) / f"page-{page}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    if f.file_type in IMAGE_TYPES:
        from PIL import Image, ImageOps
        with Image.open(state.data_dir / f.stored_path) as img:
            ImageOps.exif_transpose(img).convert("RGB").save(out, quality=90)
    else:
        import pdfplumber
        with pdfplumber.open(state.data_dir / f.stored_path) as pdf:
            p = pdf.pages[page - 1]
            dpi = PAGE_SIDE_PX / (max(p.width, p.height) / 72)
            p.to_image(resolution=dpi).original.convert("RGB").save(out, quality=90)
    return out


def annotatable(db: Session, state, prop, file_id: int, page: int) -> SourceFile:
    f = db.get(SourceFile, file_id)
    if f is None or f.project_id != prop.project_id:
        raise HTTPException(404, tr("文件不存在", "File not found"))
    if not 1 <= page <= page_count(state, f):
        raise HTTPException(422, tr("这个文件不能标注，或页码不对（只能标注 PDF 和 JPG / PNG）",
                                   "This file cannot be annotated, or the page is wrong (PDF and JPG / PNG only)"))
    return f


@router.get("/files/{file_id}/pages")
def pages(file_id: int, request: Request, db: Session = Depends(get_db)):
    f = db.get(SourceFile, file_id)
    if f is None:
        raise HTTPException(404, tr("文件不存在", "File not found"))
    return {"pages": page_count(request.app.state, f)}


@router.get("/files/{file_id}/page/{page}")
def page_image(file_id: int, page: int, request: Request, db: Session = Depends(get_db)):
    f = db.get(SourceFile, file_id)
    if f is None or not 1 <= page <= page_count(request.app.state, f):
        raise HTTPException(404, tr("页面不存在", "Page not found"))
    return FileResponse(base_image(request.app.state, f, page))


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Scale(BaseModel):
    a: Point
    b: Point
    mm: float = Field(gt=0)


class Mark(BaseModel):
    type: Literal["point", "area", "device", "text"]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(0, ge=0, le=1)
    h: float = Field(0, ge=0, le=1)
    label: str = Field("", max_length=100)
    note: str = Field("", max_length=300)
    boq_key: str | None = Field(None, max_length=120)  # 设备标记对应的 BOQ 行


class AnnotationIn(BaseModel):
    file_id: int
    page: int = 1
    scale: Scale | None = None
    marks: list[Mark]


def size_mm(mark: Mark, scale: Scale | None, width: int, height: int) -> list[int] | None:
    """有比例时，区域标记的近似实际尺寸（mm）。"""
    if mark.type != "area" or scale is None:
        return None
    px = math.hypot((scale.b.x - scale.a.x) * width, (scale.b.y - scale.a.y) * height)
    if px == 0:
        return None
    return [round(mark.w * width / px * scale.mm), round(mark.h * height / px * scale.mm)]


def _font(size: int):
    from PIL import ImageFont
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_copy(base: Path, body: AnnotationIn, sizes: list, out: Path) -> None:
    """在底图副本上画标记，下方加图例；保存为 JPG。"""
    from PIL import Image, ImageDraw

    with Image.open(base) as img:
        img = img.convert("RGB")
    W, H = img.size
    unit = max(W, H) / 100
    fs = max(14, int(unit * 1.4))
    font, small = _font(fs), _font(int(fs * 0.85))
    legend = [f"{i}  {m.label or TYPE_LABEL[m.type]()}"
              + (f" · ≈ {s[0]} × {s[1]} mm" if s else "") + (f" — {m.note}" if m.note else "")
              for i, (m, s) in enumerate(zip(body.marks, sizes), 1)]
    if body.scale:
        legend.append(tr(f"比例：两点间距 {body.scale.mm:g} mm", f"Scale: {body.scale.mm:g} mm between two points"))
    line_h = int(fs * 1.7)
    canvas = Image.new("RGB", (W, H + line_h * len(legend) + line_h), WHITE)
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    r = int(unit * 1.3)

    def badge(cx, cy, n):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ORANGE, outline=WHITE, width=max(2, r // 6))
        d.text((cx, cy), str(n), fill=WHITE, font=small, anchor="mm")

    if body.scale:
        a, b = (body.scale.a.x * W, body.scale.a.y * H), (body.scale.b.x * W, body.scale.b.y * H)
        d.line([a, b], fill=NAVY, width=max(2, int(unit / 3)))
        for p in (a, b):
            d.ellipse((p[0] - r / 3, p[1] - r / 3, p[0] + r / 3, p[1] + r / 3), fill=NAVY)
    for i, m in enumerate(body.marks, 1):
        x, y = m.x * W, m.y * H
        if m.type == "area":
            d.rectangle((x, y, x + m.w * W, y + m.h * H), outline=ORANGE, width=max(3, int(unit / 2.5)))
            badge(x, y, i)
        elif m.type == "device":
            s = r * 1.6
            d.rectangle((x - s, y - s, x + s, y + s), fill=NAVY, outline=WHITE, width=2)
            badge(x + s, y - s, i)
        elif m.type == "text":
            text = m.label or ""
            box = d.textbbox((x, y), text, font=font)
            d.rectangle((box[0] - 6, box[1] - 4, box[2] + 6, box[3] + 4), fill=WHITE, outline=NAVY)
            d.text((x, y), text, fill=NAVY, font=font)
            badge(box[0] - 8 - r, (box[1] + box[3]) / 2, i)
        else:
            badge(x, y, i)
    for j, text in enumerate(legend):
        d.text((int(unit * 2), H + line_h // 2 + j * line_h), text, fill=NAVY, font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=88)


@router.put("/proposals/{proposal_id}/annotations")
def save_annotation(proposal_id: int, body: AnnotationIn, request: Request, user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    state = request.app.state
    prop = get_proposal(db, proposal_id)
    rev = prop.revisions[-1]
    f = annotatable(db, state, prop, body.file_id, body.page)
    key = f"{f.id}:{body.page}"
    docs = dict(rev.annotations or {})
    if not body.marks:  # 清空 = 删掉这份标注
        docs.pop(key, None)
        rev.annotations = docs
        db.commit()
        return {"annotations": docs}
    base = base_image(state, f, body.page)
    from PIL import Image
    with Image.open(base) as img:
        width, height = img.size
    sizes = [size_mm(m, body.scale, width, height) for m in body.marks]
    stem = Path(f.filename).stem
    name = f"{stem}{f'_p{body.page}' if f.file_type == 'pdf' else ''}_annotated_Rev{rev.rev_no}.jpg"
    rel = f"derived/proposals/{prop.id}/rev{rev.rev_no}/{f.id}-{body.page}/{name}"
    render_copy(base, body, sizes, state.data_dir / rel)
    docs[key] = {"file_id": f.id, "filename": f.filename, "page": body.page, "width": width, "height": height,
                 "scale": body.scale.model_dump() if body.scale else None,
                 "marks": [m.model_dump() | {"size_mm": s} for m, s in zip(body.marks, sizes)],
                 "copy_name": name, "copy_path": rel, "updated_by": user.name, "updated_at": iso(utcnow())}
    rev.annotations = docs
    db.commit()
    return {"annotations": docs}


@router.get("/proposals/{proposal_id}/annotations/{file_id}/{page}/copy")
def annotation_copy(proposal_id: int, file_id: int, page: int, request: Request, db: Session = Depends(get_db)):
    doc = (get_proposal(db, proposal_id).revisions[-1].annotations or {}).get(f"{file_id}:{page}")
    if doc is None:
        raise HTTPException(404, tr("还没有标注副本", "No annotated copy yet"))
    return FileResponse(request.app.state.data_dir / doc["copy_path"], filename=doc["copy_name"])
