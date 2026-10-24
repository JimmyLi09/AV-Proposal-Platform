"""资料库读文件（CR-8）：抽出文字（PDF 按页、Excel 按每 50 行、Word 按段落）和 Excel 的每一行，供全文索引和「学到的内容」用。

只用本地组件：pdfplumber、RapidOCR、openpyxl、ezdxf；Word 直接读 docx 里的 XML。原文件只读，DWG 转出的 DXF 放临时文件夹，用完即删。
位置写法不翻译：p.3、Sheet1!12、¶1–30、图层名。
"""
import html
import re
import tempfile
import zipfile
from pathlib import Path

from ..extract.readers import MAX_OCR_PAGES, MAX_SIDE_PX, convert_dwg, ocr_lines

MAX_PAGES = 200  # 文字层最多读前 200 页
MAX_ROWS = 2000  # 每个工作表最多读前 2000 行
ROWS_PER_CHUNK = 50
PARAS_PER_CHUNK = 30


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _ocr(img) -> str:
    scale = MAX_SIDE_PX / max(img.size)
    if scale < 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return "\n".join(text for text, _ in ocr_lines(img))


def read_pdf(path: Path, out: dict) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        texts = [(p.extract_text() or "") for p in pdf.pages[:MAX_PAGES]]
        if any(t.strip() for t in texts):
            out["chunks"] += [(f"p.{no}", t) for no, t in enumerate(texts, 1) if t.strip()]
            return "text_layer"
        for no, page in enumerate(pdf.pages[:MAX_OCR_PAGES], 1):  # 扫描件：整页渲染后识别
            dpi = min(200, MAX_SIDE_PX / (max(page.width, page.height) / 72))
            if t := _ocr(page.to_image(resolution=dpi).original):
                out["chunks"].append((f"p.{no}", t))
        return "ocr"


def read_image(path: Path, out: dict) -> str:
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        if t := _ocr(ImageOps.exif_transpose(img).convert("RGB")):
            out["chunks"].append(("", t))
    return "ocr"


def read_excel(path: Path, out: dict) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            lines = []
            for no, row in enumerate(ws.iter_rows(max_row=MAX_ROWS, values_only=True), 1):
                cells = [_cell(v) for v in row]
                if any(cells):
                    out["rows"].append((ws.title, no, cells))
                    lines.append((no, " | ".join(c for c in cells if c)))
            for i in range(0, len(lines), ROWS_PER_CHUNK):
                part = lines[i:i + ROWS_PER_CHUNK]
                out["chunks"].append((f"{ws.title}!{part[0][0]}–{part[-1][0]}", "\n".join(t for _, t in part)))
    finally:
        wb.close()
    return "excel"


def read_dxf(path: Path, out: dict) -> str:
    import ezdxf

    msp = ezdxf.readfile(path).modelspace()
    by_layer: dict[str, list[str]] = {}
    for e in msp.query("TEXT MTEXT"):
        text = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
        if text.strip():
            by_layer.setdefault(e.dxf.layer, []).append(text.strip())
    out["chunks"] += [(layer, "\n".join(texts)) for layer, texts in by_layer.items()]
    return "dxf"


def read_docx(path: Path, out: dict) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paras = [html.unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", p)))
             for p in xml.split("</w:p>")]
    paras = [p.strip() for p in paras if p.strip()]
    for i in range(0, len(paras), PARAS_PER_CHUNK):
        part = paras[i:i + PARAS_PER_CHUNK]
        out["chunks"].append((f"¶{i + 1}–{i + len(part)}", "\n".join(part)))
    return "docx"


def read_text(path: Path, out: dict) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i in range(0, len(lines), ROWS_PER_CHUNK):
        if t := "\n".join(lines[i:i + ROWS_PER_CHUNK]).strip():
            out["chunks"].append((f"{i + 1}–{min(i + ROWS_PER_CHUNK, len(lines))}", t))
    return "text"


READERS = {"pdf": read_pdf, "jpg": read_image, "jpeg": read_image, "png": read_image, "xlsx": read_excel,
           "xlsm": read_excel, "dxf": read_dxf, "docx": read_docx, "txt": read_text, "csv": read_text}


def read(path: Path, oda: str | None) -> dict:
    """{method, chunks: [(位置, 文字)], rows: [(工作表, 行号, [单元格])], note}。读不了的文件 method 为 none。"""
    out = {"method": "none", "chunks": [], "rows": [], "note": ""}
    kind = path.suffix.lower().lstrip(".")
    try:
        if kind == "dwg":
            if not oda:
                out["note"] = "DWG 要在服务器装免费的 ODA File Converter 才能读取"
                return out
            with tempfile.TemporaryDirectory() as tmp:
                read_dxf(convert_dwg(path, Path(tmp), oda), out)
            out["method"] = "dwg"
        elif kind in READERS:
            out["method"] = READERS[kind](path, out)
        else:
            out["note"] = "这类文件不读取，只能按文件名搜索"
    except Exception as e:  # 文件损坏、加密、转换失败等
        out.update(method="failed", chunks=[], rows=[], note=f"读取失败：{type(e).__name__}")
    return out
