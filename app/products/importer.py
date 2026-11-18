"""产品库导入文件（2026-11-17 Jimmy：两种都要）。

1. Excel：导出当前产品库（一类产品一个工作表），改好或加行后再导入。按「编号」对上已有产品就更新，
   新编号就新增；空格子 = 不改。导入只改界面上的草稿，人看过再填原因另存新版本。
   「每箱最大电流 / 功率」结构复杂，不进 Excel，在界面里填。
2. 规格书：上传一份规格书（PDF / 图片 / Excel / Word），复制存档（只读），读出这一类产品的数值参数，
   每个值带原文，交给人逐项勾选后填进产品表单。只找格式确定的写法（同资料库 learn.SPEC），不推算。
"""
import io
import json
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

    fields = {n for n, _, kind in FIELDS[line][category] if kind in ("number", "sizes")}
    return {f: {"value": v, "location": loc, "snippet": snip} for f, (v, loc, snip) in spec_values(chunks, fields).items()}


# ---- 规格书批量导入（2026-11-18）：一次多份，猜类别 / 型号 / 品牌，人逐行复核 ----

CATEGORY_WORDS = {
    "cabinet": r"module|模组|模块|cabinet|箱体|\d+\s*scan|\d+\s*扫|pixel\s*pitch|像素间距|点间距|(?<![A-Za-z])P\d",
    "controller": r"controller|控制器|sending\s*card|发送卡|MCTRL|loading\s*capacity|带载",
    "processor": r"video\s*processor|视频处理器|拼接处理|processor|(?<![A-Za-z])VX\d|novapro|(?<![A-Za-z])J6",
    "projector": r"projector|投影机|lumens?|流明",
    "lens": r"(?<![a-z])lens|镜头|throw\s*ratio|投射比",
    "blender": r"blend|融合|warp",
}
BRANDS = ["NovaStar", "Colorlight", "Linsn", "Huidu", "Kystar", "Absen", "Unilumin", "Leyard", "Liantronics", "MUXWAVE",
          "Panasonic", "Epson", "Christie", "Barco", "Sony", "NEC", "Optoma", "ViewSonic", "BenQ", "Hitachi"]
NOISE = re.compile(r"(?:模组)?规格书|规格|datasheet|data\s*sheet|specs?(?:ification)?s?|副本|copy|(?<![A-Za-z])V\d+(?:\.\d+)*(?![\w.])"
                   r"|[（(]\d+[)）]", re.I)
BATCH_MAX = 30


def guess_category(line: str, filename: str, text_: str) -> str:
    scores = {c: 3 * len(re.findall(p, filename, re.I)) + len(re.findall(p, text_[:20000], re.I))
              for c, p in CATEGORY_WORDS.items() if c in FIELDS[line]}
    return max(scores, key=lambda c: (scores[c], -list(FIELDS[line]).index(c)))


def guess_model(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    stem = re.sub(r"(?<![A-Za-z])(?:EN|CN|ZH|ENG)(?![A-Za-z])|[（(]?(?:英文|中文)版?[)）]?", " ", NOISE.sub(" ", stem))
    stem = re.sub(r"\s*[_]+\s*|\s+", " ", stem).strip(" -_–.")
    return stem[:60] or filename


def _slug(model: str, taken: set[str]) -> str:
    base = re.sub(r"[^A-Z0-9.]+", "-", model.upper()).strip("-")[:30] or "NEW"
    pid, n = base, 2
    while pid in taken:
        pid, n = f"{base}-{n}", n + 1
    taken.add(pid)
    return pid


def _choices(line: str, text_: str) -> dict:
    """维护方式、适用场景、防护等级：写明了才填，带原文。"""
    out = {}
    if "cabinet" in FIELDS[line]:
        for pattern, value in ((r"前后维护|前后均可维护|front\s*(?:and|&|/)\s*rear\s*(?:service|maintenance|access)", "both"),
                               (r"前维护|front\s*(?:service|maintenance|access)", "front"),
                               (r"后维护|rear\s*(?:service|maintenance|access)", "rear")):
            if m := re.search(pattern, text_, re.I):
                out["maintenance"] = {"value": value, "location": "", "snippet": m[0]}
                break
        scenes = [v for p, v in ((r"indoor|室内", "indoor"), (r"outdoor|户外|室外", "outdoor"), (r"rental|租赁", "rental"))
                  if re.search(p, text_[:5000], re.I)]
        if scenes:
            out["scenes"] = {"value": scenes, "location": "", "snippet": "、".join(WORDS["scenes"][x] for x in scenes)}
        if m := re.search(r"(?<![A-Za-z])IP\s?([2-6][0-9])(?!\d)", text_):
            out["ip"] = {"value": "IP" + m[1], "location": "", "snippet": m[0]}
    return out


def batch_item(line: str, filename: str, read_result: dict, products: list[dict], taken: set[str]) -> dict:
    """一份规格书 → 复核表的一行。每类产品各算一套值，界面改类别时直接换。"""
    from ..knowledge.learn import match_product

    chunks = read_result["chunks"]
    body = "\n".join(t for _, t in chunks)
    category = guess_category(line, filename, body)
    hit = match_product(filename, body, products)
    model = guess_model(filename)
    brand = next((b for b in BRANDS if re.search(rf"(?<![A-Za-z]){b}(?![A-Za-z])", filename + "\n" + body[:5000], re.I)), "")
    values = {c: datasheet_values(chunks, line, c) | _choices(line, body) for c in FIELDS[line]} if chunks else {}
    proc = values.get("processor", {})
    if "capacity_px" in proc and "ports" in proc:  # CR-2：写了带载和网口的处理器就是含发送的（如 VX 系列）
        proc["sending"] = {"value": True, "location": proc["capacity_px"]["location"],
                           "snippet": f'{proc["capacity_px"]["snippet"]} · {proc["ports"]["snippet"]}'}
    return {"file": filename, "category": category, "model": model, "brand": brand,
            "id": hit["id"] if hit else _slug(model, taken), "match": hit["id"] if hit else None,
            "values": values, "ocr": read_result["method"] == "ocr", "read": bool(chunks), "note": text(read_result["note"])}


def mark_duplicates(items: list[dict]) -> None:
    """同一产品的中英文两份规格书：类别相同、认出的数值完全一样（至少 2 个）。"""
    seen = {}
    for i, it in enumerate(items):
        vals = {f: v["value"] for f, v in it["values"].get(it["category"], {}).items()
                if f not in ("scenes", "maintenance", "ip")}
        key = (it["category"], json.dumps(vals, sort_keys=True)) if len(vals) >= 2 else None
        it["same_as"] = seen.get(key) if key else None
        if key and key not in seen:
            seen[key] = i
