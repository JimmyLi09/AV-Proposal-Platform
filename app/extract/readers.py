"""在服务器上读客户文件：PDF 先读文字层，读不到再文字识别（OCR）；图片走 OCR；Excel 按栏名；DXF 读文字；
DWG 先用免费的 ODA File Converter 转成 DXF 副本。原件只读，截图和转换结果都另存在 derived 目录。"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .fields import LABELS, find_in_text, parse_value

MAX_PAGES = 30  # 文字层最多读前 30 页
MAX_OCR_PAGES = 5  # 扫描件最多识别前 5 页（CPU 上较慢）
MAX_SIDE_PX = 3000  # 送去识别的图片最长边

_ocr = None


def ocr_lines(img) -> list[tuple[str, tuple[float, float, float, float]]]:
    """图片里的文字行：(文字, 外框)。识别模型第一次用时才加载。"""
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    import numpy as np
    result, _ = _ocr(np.array(img.convert("RGB")))
    lines = []
    for box, text, _score in result or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append((text, (min(xs), min(ys), max(xs), max(ys))))
    return lines


def _shrink(img):
    scale = MAX_SIDE_PX / max(img.size)
    return img.resize((int(img.width * scale), int(img.height * scale))) if scale < 1 else img


class Collector:
    """收集一个文件里认出的字段，同字段同值只留第一条，截图存到 out_dir。"""

    def __init__(self, out_dir: Path, rel_dir: str):
        self.out_dir, self.rel_dir, self.fields, self.text = out_dir, rel_dir, [], []

    def line(self, text: str, ocr: bool, page=None, location="", crop=None):
        self.text.append(text)
        for field, value, conf, snippet in find_in_text(text, ocr):
            self.add(field, value, conf, page, location, snippet, crop)

    def add(self, field, value, conf, page, location, snippet, crop=None):
        if any(f["field"] == field and f["value"] == value for f in self.fields):
            return
        path = None
        if crop is not None:
            name = f"crop-{len(self.fields) + 1}.png"
            crop().save(self.out_dir / name)
            path = f"{self.rel_dir}/{name}"
        self.fields.append({"field": field, "value": value, "confidence": conf, "page": page,
                            "location": location, "snippet": snippet[:300], "crop": path})


def read_pdf(path: Path, c: Collector) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = pdf.pages[:MAX_PAGES]
        if any((p.extract_text() or "").strip() for p in pages):
            for no, page in enumerate(pages, 1):
                for line in page.extract_text_lines():
                    box = (max(line["x0"] - 6, 0), max(line["top"] - 6, 0),
                           min(line["x1"] + 6, page.width), min(line["bottom"] + 6, page.height))
                    c.line(line["text"], ocr=False, page=no, location=f"p.{no}",
                           crop=lambda p=page, b=box: p.crop(b).to_image(resolution=150).original)
            return "text_layer"
        for no, page in enumerate(pdf.pages[:MAX_OCR_PAGES], 1):  # 扫描件：整页渲染后识别
            dpi = min(200, MAX_SIDE_PX / (max(page.width, page.height) / 72))
            img = page.to_image(resolution=dpi).original
            _ocr_image(img, c, page=no)
        return "ocr"


def _ocr_image(img, c: Collector, page=None):
    img = _shrink(img)
    for text, (x0, y0, x1, y1) in ocr_lines(img):
        box = (max(x0 - 8, 0), max(y0 - 8, 0), min(x1 + 8, img.width), min(y1 + 8, img.height))
        c.line(text, ocr=True, page=page, location=f"p.{page} · 文字识别" if page else "文字识别",
               crop=lambda b=box: img.crop(b))


def read_image(path: Path, c: Collector) -> str:
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        _ocr_image(ImageOps.exif_transpose(img).convert("RGB"), c)
    return "ocr"


def read_excel(path: Path, c: Collector) -> str:
    """按栏名匹配：栏名在左、值在右（或栏名在上、值在下）。"""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=False)
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=200, max_col=30):
            for cell in row:
                if not isinstance(cell.value, str) or len(cell.value) > 40:
                    continue
                c.text.append(cell.value)
                field = next((f for f, pat in LABELS.items() if re.search(pat, cell.value, re.I)), None)
                if field is None:
                    continue
                right = [ws.cell(cell.row, col) for col in range(cell.column + 1, cell.column + 4)]
                below = [ws.cell(r, cell.column) for r in range(cell.row + 1, cell.row + 2)]
                for target in right + below:
                    if target.value not in (None, ""):
                        value = parse_value(field, target.value)
                        if value is not None:
                            c.add(field, value, "high", None, f"{ws.title}!{target.coordinate}",
                                  f"{cell.value}: {target.value}")
                        break
    return "excel"


def read_dxf(path: Path, c: Collector) -> str:
    import ezdxf

    doc = ezdxf.readfile(path)
    for e in doc.modelspace().query("TEXT MTEXT"):
        text = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
        x, y = e.dxf.insert.x, e.dxf.insert.y
        c.line(text, ocr=False, location=f"{e.dxf.layer} · ({x:.0f}, {y:.0f})")
    return "dxf"


def convert_dwg(path: Path, out_dir: Path, oda: str) -> Path:
    """ODA File Converter 只处理整个文件夹：把 DWG 复制到临时文件夹再转换，DXF 副本存到 out_dir。"""
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
        shutil.copy(path, Path(src) / "source.dwg")
        subprocess.run([oda, src, dst, "ACAD2018", "DXF", "0", "1", "*.DWG"], check=True, timeout=180,
                       capture_output=True)
        dxf = next(Path(dst).glob("*.dxf"))
        target = out_dir / "converted.dxf"
        shutil.copy(dxf, target)
        return target
