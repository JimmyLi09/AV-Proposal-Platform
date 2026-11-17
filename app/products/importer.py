"""产品库导入文件（2026-11-17 Jimmy：两种都要）。

1. Excel：导出当前产品库（一类产品一个工作表），改好或加行后再导入。按「编号」对上已有产品就更新，
   新编号就新增；空格子 = 不改。导入只改界面上的草稿，人看过再填原因另存新版本。
   「每箱最大电流 / 功率」结构复杂，不进 Excel，在界面里填。
2. 规格书：上传一份规格书（PDF / 图片 / Excel / Word），复制存档（只读），读出这一类产品的数值参数，
   每个值带原文，交给人逐项勾选后填进产品表单。只找格式确定的写法（同资料库 learn.SPEC），不推算。
"""
import io
import re

from openpyxl import Workbook, load_workbook

from ..i18n import CONTENT, text, tr
from .library import CATEGORY_LABEL, FIELDS, LibraryError, validate

SKIP = {"ratings"}  # 不进 Excel 的字段类型
WORDS = {
    "status": {"preferred": "首选", "approved": "已批准", "retired": "已停用"},
    "scenes": {"indoor": "室内", "outdoor": "户外", "rental": "租赁"},
    "maintenance": {"front": "前维护", "rear": "后维护", "both": "前后维护"},
}
YES, NO = {"是", "yes", "y", "true", "1", "✓", "√"}, {"否", "no", "n", "false", "0", "✗", "×"}


def _columns(line: str, category: str) -> list[tuple[str, str, str]]:
    return [("id", "编号 ID", "id")] + [f for f in FIELDS[line][category] if f[2] not in SKIP]


def _sheet_name(category: str) -> str:
    return text(CATEGORY_LABEL[category])[:31]


def _cell(kind: str, v):
    if v is None:
        return None
    if kind in WORDS:
        return "、".join(WORDS[kind][x] for x in v) if kind == "scenes" else WORDS[kind].get(v, v)
    if kind in ("bool", "flag"):
        return "是" if v else "否"
    if kind == "sizes":
        return "; ".join(f"{w}x{h}" for w, h in v)
    if kind == "ids":
        return ", ".join(v)
    return v


def export_xlsx(content: dict, line: str) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for category in FIELDS[line]:
        ws = wb.create_sheet(_sheet_name(category))
        cols = _columns(line, category)
        ws.append([_head(label) for _, label, _ in cols])
        for p in content["products"]:
            if p["category"] == category:
                ws.append([_cell(kind, p.get(name)) for name, _, kind in cols])
        for i, (_, label, _) in enumerate(cols):
            ws.column_dimensions[ws.cell(1, i + 1).column_letter].width = max(12, len(_head(label)) + 4)
        ws.freeze_panes = "B2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _head(label: str) -> str:
    return text(label) if label in CONTENT else label


def _norm(s: str) -> str:
    return re.sub(r"[\s_（）()]", "", str(s or "")).lower()


def _keys(label: str, name: str) -> set[str]:
    """一个字段 / 类别认的写法：中英双写、只写中文、只写英文、字段名。"""
    keys = {_norm(label), _norm(name)} | {_norm(v) for v in CONTENT.get(label, {}).values()}
    if name == "id":
        keys |= {"编号", "id"}
    return keys - {""}


def _header_map(line: str, category: str, header: list) -> dict[int, tuple[str, str, str]]:
    """表头 → 字段。"""
    out = {}
    for name, label, kind in _columns(line, category):
        keys = _keys(label, name)
        for i, h in enumerate(header):
            if _norm(h) in keys and i not in out:
                out[i] = (name, kind, _head(label))
                break
    return out


def _parse(kind: str, v):
    """Excel 单元格 → 产品库的值；看不懂的抛 ValueError。"""
    s = str(v).strip()
    if kind in ("id", "text"):
        return s
    if kind == "number":
        n = float(s.replace(",", ""))
        return int(n) if n.is_integer() else n
    if kind in WORDS:
        back = {w.lower(): k for k, w in WORDS[kind].items()} | {k: k for k in WORDS[kind]}
        if kind == "maintenance":
            back |= {"前后": "both"}
        parts = [x.strip().lower() for x in re.split(r"[,，、;；/]", s) if x.strip()]
        values = [back[x] for x in parts]  # KeyError → 看不懂
        return values if kind == "scenes" else values[0]
    if kind in ("bool", "flag"):
        if s.lower() in YES:
            return True
        if s.lower() in NO:
            return False
        raise ValueError(s)
    if kind == "sizes":
        return [[_parse("number", w), _parse("number", h)]
                for w, h in (re.split(r"\s*[x×*]\s*", x.strip(), flags=re.I) for x in re.split(r"[;；,，]", s) if x.strip())]
    if kind == "ids":
        return [x.strip() for x in re.split(r"[,，、;；]", s) if x.strip()]
    raise ValueError(s)


def _blank(line: str, category: str, pid: str) -> dict:
    p = {"id": pid, "category": category, "brand": "", "model": "", "status": "approved", "sample": False}
    for name, _, kind in FIELDS[line][category]:
        if name not in p:
            p[name] = ["indoor"] if kind == "scenes" else "" if kind == "text" else "front" if kind == "maintenance" else None
    return p


def import_xlsx(data: bytes, content: dict, line: str) -> dict:
    """把 Excel 合并进 content（界面上的草稿）。返回 {products, added, updated, errors}，不保存。"""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    by_sheet = {k: c for c in FIELDS[line] for k in _keys(CATEGORY_LABEL[c], c)}
    products = [dict(p) for p in content["products"]]
    index = {p["id"]: i for i, p in enumerate(products)}
    added, updated, errors, seen = [], [], [], 0
    for ws in wb.worksheets:
        category = by_sheet.get(_norm(ws.title))
        if category is None:
            continue
        seen += 1
        rows = ws.iter_rows(values_only=True)
        cols = _header_map(line, category, list(next(rows, [])))
        id_col = next((i for i, (n, _, _) in cols.items() if n == "id"), None)
        if id_col is None:
            errors.append(tr(f"{ws.title}：第一行没有「编号」栏", f"{ws.title}: no ID column in the first row"))
            continue
        for no, row in enumerate(rows, start=2):
            pid = str(row[id_col]).strip() if id_col < len(row) and row[id_col] is not None else ""
            if not pid:
                continue
            where = f"{ws.title}!{no}"
            old = products[index[pid]] if pid in index else None
            if old is not None and old["category"] != category:
                errors.append(tr(f"{where}：编号 {pid} 已经是别的类别", f"{where}: ID {pid} belongs to another category"))
                continue
            p = dict(old) if old else _blank(line, category, pid)
            try:
                for i, (name, kind, head) in cols.items():
                    if name != "id" and i < len(row) and row[i] is not None and str(row[i]).strip():
                        try:
                            p[name] = _parse(kind, row[i])
                        except (ValueError, KeyError, IndexError):
                            raise LibraryError(tr(f"{head} 看不懂：{row[i]}", f"cannot read {head}: {row[i]}"))
                validate({"business_line": line, "products": [p]}, line)
            except LibraryError as e:
                errors.append(f"{where}：{e}")
                continue
            if old is None:
                index[pid] = len(products)
                products.append(p)
                added.append(pid)
            elif p != old:
                products[index[pid]] = p
                updated.append(pid)
    if not seen:
        errors.append(tr("没有找到产品工作表：请用「导出 Excel」下载的格式（一类产品一个工作表）",
                         "No product sheets found: use the format from Export Excel (one sheet per category)"))
    return {"products": products, "added": added, "updated": updated, "errors": errors}


def datasheet_values(chunks: list[tuple[str, str]], line: str, category: str) -> dict:
    """规格书里认出的这一类产品的数值参数：{字段: {value, location, snippet}}。"""
    from ..knowledge.learn import spec_values

    fields = {n for n, _, kind in FIELDS[line][category] if kind == "number"}
    return {f: {"value": v, "location": loc, "snippet": snip} for f, (v, loc, snip) in spec_values(chunks, fields).items()}
