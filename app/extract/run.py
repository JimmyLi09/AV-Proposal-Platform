"""读一个文件，给出等级、读取方式和认出的字段。

等级（原型 New Proposal 页）：A 数值直接读取；B 数值靠文字识别，必须逐项确认；C 随项目保存，不用于计算数量。
"""
import shutil
from pathlib import Path

from ..i18n import tr
from .readers import Collector, convert_dwg, read_dxf, read_excel, read_image, read_pdf


def method_label(method: str | None) -> str:
    return {
        "text_layer": tr("文本层，直接读取", "Text layer, read directly"),
        "excel": tr("按栏名匹配", "Matched by column name"),
        "ocr": tr("先文字识别，再读尺寸", "OCR, then dimensions"),
        "dxf": tr("读 DXF 里的文字", "Text in the DXF"),
        "dwg": tr("DWG 经 ODA 转换后读取", "DWG converted by ODA, then read"),
        "none": tr("不读取，仅随项目保存", "Not read; kept with the project"),
    }.get(method or "", "")


READERS = {"pdf": read_pdf, "jpg": read_image, "jpeg": read_image, "png": read_image,
           "xlsx": read_excel, "xlsm": read_excel, "dxf": read_dxf}


def extract(path: Path, file_type: str, data_dir: Path, rel_dir: str, oda: str | None) -> dict:
    out_dir = data_dir / rel_dir
    shutil.rmtree(out_dir, ignore_errors=True)  # 只清掉上次读取生成的副本，原件不在这里
    out_dir.mkdir(parents=True)
    c = Collector(out_dir, rel_dir)
    note = ""
    try:
        if file_type == "dwg":
            if not oda:
                return _result("none", c, "DWG 要在服务器装免费的 ODA File Converter 才能读取，目前只随项目保存")
            read_dxf(convert_dwg(path, out_dir, oda), c)
            method = "dwg"
        elif file_type in READERS:
            method = READERS[file_type](path, c)
        else:
            return _result("none", c, "这类文件不读取，只随项目保存")
    except Exception as e:  # 文件损坏、加密、转换失败等
        return _result("none", c, f"读取失败：{type(e).__name__}", failed=True)
    if not c.fields:
        note = "未找到尺寸，仅作参考"
    return _result(method, c, note)


def _result(method: str, c: Collector, note: str, failed: bool = False) -> dict:
    grade = "C" if not c.fields else "B" if method == "ocr" else "A"
    status = "failed" if failed else ("read" if c.fields else "attached")
    return {"method": method, "grade": grade, "status": status, "note": note, "fields": c.fields,
            "text": "\n".join(c.text)[:2000]}
