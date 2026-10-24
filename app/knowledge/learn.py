"""资料库「学到的内容」（CR-8）：只用确定的格式匹配，从读到的文字里找出建议值，交给人确认。不计算、不改任何数量。

- 规格书 → 产品库：文件名（或全文）里只出现一个产品库 / 参考型号表里的型号时，按它的类别找带载、网口、亮度、流明……
- BOQ → 模板默认行：Excel 里有 Description 和 Qty 栏的表；模板里还没有的行写法，只收固定 1 项的行和按面积（sqm）计的行，
  数量照模板的做法写成 1 或 area_m2，尺寸、点间距换成 {名字}。
- 以往项目 → 项目记录：一个子文件夹一个项目，汇总业务线、屏形、尺寸、点间距和 BOQ 里的实际数量。
- 标准答案项目 → 规则参考：用项目记录跑一遍规则，和实际数量不一样的列出来，只作参考。
"""
import hashlib
import json
import re

from ..extract.fields import LABELS, find_in_text, parse_value
from ..products.library import FIELDS, name
from ..rules.engine import LINES, calculate
from ..rules.led import ENVIRONMENT_LABEL, INSTALLATION_LABEL

CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def fingerprint(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _number(s) -> float | int | None:
    s = str(s or "").replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None
    v = float(s)
    return int(v) if v.is_integer() else v


PJ_WORDS = re.compile(r"projector|projection|lumens?|throw\s*ratio|blend|投影|流明|融合|投射比", re.I)
LED_WORDS = re.compile(r"\bLED\b|cabinet|pixel\s*pitch|\bnits\b|箱体|点间距|模组|\bP\d\.\d", re.I)


def detect_line(text: str) -> str | None:
    pj, led = len(PJ_WORDS.findall(text)), len(LED_WORDS.findall(text))
    return "PJ" if pj > led else "LED" if led else None


# ---- 读文件时：每份文件的结构化内容（存在 kb_files.facts）----

HEAD_DESC = re.compile(r"description|描述|品名|项目内容", re.I)
HEAD_QTY = re.compile(r"^(?:qty|quantity|q'ty|数量)", re.I)
HEAD_UNIT = re.compile(r"^(?:unit|uom|单位)", re.I)
BULLET = re.compile(r"^[-•·*]\s*")


def boq_rows(rows: list[tuple[str, int, list[str]]]) -> list[dict]:
    """Excel 里的 BOQ 行：找到 Description / Qty（/ Unit）表头后，有数量的是一行，以「-」开头的是上一行的规格。"""
    out, cols, current = [], {}, None
    for sheet, no, cells in rows:
        if sheet not in cols:
            d = next((i for i, x in enumerate(cells) if HEAD_DESC.search(x)), None)
            q = next((i for i, x in enumerate(cells) if HEAD_QTY.search(x)), None)
            if d is not None and q is not None:
                cols[sheet] = (d, q, next((i for i, x in enumerate(cells) if HEAD_UNIT.search(x)), None))
                current = None
            continue
        d, q, u = cols[sheet]
        get = lambda i: cells[i] if i is not None and i < len(cells) else ""  # noqa: E731
        desc, qty = get(d), _number(get(q))
        if not desc:
            continue
        if qty is not None:
            current = {"sheet": sheet, "row": no, "title": desc, "qty": qty, "unit": get(u), "specs": []}
            out.append(current)
        elif BULLET.match(desc) and current:
            current["specs"].append(BULLET.sub("", desc))
        else:
            current = None  # 组标题
    return out


def file_facts(chunks: list[tuple[str, str]], rows: list, method: str) -> dict:
    """认出的输入字段（同字段同值合并计数）、BOQ 行、业务线。"""
    ocr = method == "ocr"
    found: dict[tuple, dict] = {}

    def add(field, value, conf, location, snippet):
        key = (field, json.dumps(value))
        if key in found:
            found[key]["count"] += 1
        else:
            found[key] = {"field": field, "value": value, "confidence": conf, "location": location,
                          "snippet": snippet[:200], "count": 1}

    for location, chunk in chunks:
        for line in chunk.splitlines():
            for field, value, conf, snippet in find_in_text(line, ocr):
                add(field, value, conf, location, snippet)
    for sheet, no, cells in rows:  # Excel：栏名在左、值在右
        for i, c in enumerate(cells):
            field = next((f for f, p in LABELS.items() if re.search(p, c, re.I)), None) if 0 < len(c) <= 40 else None
            value = next((parse_value(field, v) for v in cells[i + 1:i + 4] if v), None) if field else None
            if value is not None:
                add(field, value, "high", f"{sheet}!{no}", " | ".join(x for x in cells if x))
    return {"line": detect_line("\n".join(t for _, t in chunks)), "fields": list(found.values()),
            "boq": boq_rows(rows), "ocr": ocr}


# ---- 规格书 → 产品库 ----

def _int(s: str) -> int:
    return int(float(s.replace(",", "")))


def _capacity(m) -> int | None:
    v = float(m[1].replace(",", ""))
    v *= {"million": 1e6, "mil": 1e6, "m": 1e6, "万": 1e4}.get((m[2] or "").lower(), 1)
    return int(v) if v >= 100_000 else None


def _first(m, conv):
    return conv(next(g for g in m.groups() if g))


SPEC = {  # 字段: (正则, 换算)；只找这一类产品有的字段
    "capacity_px": (r"(?:load(?:ing)?\s*capacity|max(?:imum)?\s*load(?:ing)?|带载(?:能力|像素)?)\D{0,20}?"
                    r"(\d[\d,.]*)\s*(million|mil|M(?![a-z])|万)?", _capacity),
    "ports": (r"(\d{1,2})\s*(?:x|×)?\s*(?:gigabit\s*)?(?:ethernet|RJ-?45|network)\s*(?:output\s*)?ports?"
              r"|(?:输出网口|网口)\D{0,6}?(\d{1,2})", lambda m: _first(m, int)),
    "inputs": (r"(\d{1,2})\s*(?:x|×)?\s*(?:video\s*)?inputs?\b|(\d{1,2})\s*路\s*(?:视频)?输入", lambda m: _first(m, int)),
    "outputs": (r"(\d{1,2})\s*(?:x|×)?\s*(?:video\s*)?outputs?\b|(\d{1,2})\s*路\s*输出", lambda m: _first(m, int)),
    "brightness_nits": (r"(\d[\d,]{2,5})\s*(?:nits|cd/m2|cd/m²|cd/㎡)", lambda m: _int(m[1])),
    "max_power_w_m2": (r"max(?:imum)?\.?\s*power(?:\s*consumption)?\D{0,15}?(\d{2,4})\s*W\s*/\s*(?:m2|m²|㎡|sqm)",
                       lambda m: int(m[1])),
    "weight_kg": (r"(?:weight|重量)\D{0,12}?(\d+(?:\.\d+)?)\s*kg", lambda m: _number(m[1])),
    "pixel_pitch_mm": (r"(?:pixel\s*pitch|点间距)\D{0,8}?(\d{1,2}(?:\.\d{1,3})?)\s*mm", lambda m: _number(m[1])),
    "lumens": (r"(\d{1,2}[,.]?\d{3})\s*(?:ANSI\s*)?(?:lm|lumens?)\b", lambda m: _int(m[1].replace(".", ""))),
    "power_w": (r"power\s*consumption\D{0,15}?(\d{2,4})\s*W\b(?!\s*/)", lambda m: int(m[1])),
    "noise_db": (r"(?:noise|噪音)\D{0,15}?(\d{2})\s*dB", lambda m: int(m[1])),
}
RESOLUTION = re.compile(r"(\d{3,4})\s*[x×]\s*(\d{3,4})\s*(?:pixels|\(?\s*(?:WUXGA|WXGA|4K|UHD|1080p|native))", re.I)
THROW = re.compile(r"throw\s*ratio\D{0,10}?(\d\.\d{1,2})\s*(?:[-–~]\s*(\d\.\d{1,2}))?\s*:\s*1", re.I)


def spec_values(lines: list[tuple[str, str]], fields: set[str]) -> dict[str, tuple]:
    """{字段: (值, 位置, 原文)}，每个字段取第一次出现的。"""
    out = {}
    for location, line in lines:
        for field, (pattern, conv) in SPEC.items():
            if field in fields and field not in out and (m := re.search(pattern, line, re.I)):
                value = conv(m)
                if value:
                    out[field] = (value, location, m[0].strip())
        if {"native_px_w", "native_px_h"} <= fields and "native_px_w" not in out and (m := RESOLUTION.search(line)):
            out["native_px_w"], out["native_px_h"] = (int(m[1]), location, m[0]), (int(m[2]), location, m[0])
        if "throw_ratio" in fields and "throw_ratio" not in out and (m := THROW.search(line)):
            out["throw_ratio"] = (float(m[1]), location, m[0])
            if m[2]:
                out["throw_max"] = (float(m[2]), location, m[0])
    return out


def _model_pattern(model: str) -> re.Pattern:
    chars = [re.escape(c) for c in re.sub(r"[\s\-_]", "", model)]
    return re.compile(r"(?<![A-Za-z0-9])" + r"[\s\-_]?".join(chars) + r"(?![A-Za-z0-9])", re.I)


def match_product(filename: str, text: str, candidates: list[dict]) -> dict | None:
    """文件名里只出现一个型号就用它；否则全文里只出现一个型号才用。几个型号都出现时（选型手册）不认。"""
    for where in (filename, text):
        hits = [p for p in candidates if _model_pattern(p["model"]).search(where)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return None
    return None


def spec_item(file, lines: list[tuple[str, str]], libraries: dict, references: dict) -> dict | None:
    candidates = [(line, p, False) for line, lib in libraries.items() for p in lib["products"]]
    ids = {(line, p["id"]) for line, p, _ in candidates}
    candidates += [(line, p, True) for line, refs in references.items() for p in refs if (line, p["id"]) not in ids]
    text = "\n".join(t for _, t in lines)
    hit = match_product(file.rel_path.rsplit("/", 1)[-1], text, [p for _, p, _ in candidates])
    if hit is None:
        return None
    line, p, from_ref = next(c for c in candidates if c[1] is hit)
    fields = {n for n, _, kind in FIELDS[line][p["category"]] if kind == "number"}
    found = spec_values(lines, fields)
    changes = [f for f, (v, _, _) in found.items() if v != p.get(f)]
    if not found or not (changes or from_ref):
        return None
    values = {f: v for f, (v, _, _) in found.items()}
    first = min(found.values(), key=lambda x: [loc for loc, _ in lines].index(x[1]))
    return {"kind": "product", "business_line": line,
            "fingerprint": fingerprint("product", line, p["id"], values, file.rel_path),
            "payload": {"product_id": p["id"], "model": name(p), "category": p["category"], "from_reference": from_ref,
                        "values": values, "changes": changes, "current": {f: p.get(f) for f in values}},
            "source_file_id": file.id, "location": first[1],
            "snippet": " · ".join(dict.fromkeys(s for _, _, s in found.values()))[:300],
            "confidence": "low" if (file.facts or {}).get("ocr") else "medium"}


# ---- BOQ → 模板默认行 ----

UNITS = [("sqm", r"sqm|sq\.?\s*m|m2|m²|㎡|平方米?"), ("set", r"sets?|套"), ("lot", r"lots?|ls|l/s|lump\s*sum|项"),
         ("pcs", r"pcs?|nos?\.?|ea|each|units?|个|台|块")]


def norm_unit(u: str) -> str | None:
    return next((k for k, p in UNITS if re.fullmatch(p, (u or "").strip(), re.I)), None)


def _norm(title: str) -> str:
    """比较写法用：{名字}、数字、室内外和安装方式的写法都当作同一个位置。"""
    t = re.sub(r"\{\w+\}", "#", title.lower())
    for label in (*ENVIRONMENT_LABEL.values(), *INSTALLATION_LABEL.values()):
        t = re.sub(rf"(?<![a-z]){re.escape(label.lower())}(?![a-z])", "#", t)
    t = re.sub(r"\d+(?:[.,]\d+)*", "#", t)
    return re.sub(r"\s+", " ", t).strip()


# 模板里整行描述就是一个 {名字} 的，用它可能出现的写法来比较（见 led.boq_context）
TITLE_VALUES = {"processor_title": ["Video processor", "Video processor with sending"]}


def _titles(title: str) -> list[str]:
    for n, values in TITLE_VALUES.items():
        if "{" + n + "}" in title:
            return [title.replace("{" + n + "}", v) for v in values]
    return [title]


DIMS = {"LED": ("width_mm", "height_mm"), "PJ": ("wall_width_mm", "wall_height_mm")}


def placeholders(text: str, line: str) -> str:
    """把以往项目的具体数字换成模板的 {名字}：尺寸、点间距、室内外、安装方式。其它数字原样保留，采用前人看得到。"""
    if line == "LED":
        text = re.sub(r"\bP\d+(?:\.\d+)?\b", "P{pixel_pitch_mm}", text)
        for label in ENVIRONMENT_LABEL.values():
            text = re.sub(rf"(?<![A-Za-z]){label}(?![A-Za-z])", "{environment_label}", text)
        for label in INSTALLATION_LABEL.values():
            text = re.sub(rf"(?<![A-Za-z]){re.escape(label)}(?![A-Za-z])", "{installation_label}", text)
    w, h = DIMS[line]
    return re.sub(r"(\d{3,6})\s*[x×*]\s*(\d{3,6})\s*mm", "{%s} × {%s} mm" % (w, h), text)


def template_items(boqs: list[tuple], templates: dict, known: dict) -> list[dict]:
    """boqs：[(文件, 业务线, BOQ 行)]。同一种写法只出一条，记出现在几份 BOQ 里。"""
    items: dict[tuple, dict] = {}
    for file, line, rows in boqs:
        if line not in templates:
            continue
        existing = {_norm(t) for r in templates[line]["boq"]["rows"] for t in _titles(r["title"])}
        for r in rows:
            unit = norm_unit(r["unit"])
            qty = ("area_m2" if "area_m2" in known[line] else None) if unit == "sqm" else 1 if r["qty"] == 1 else None
            key = (line, _norm(r["title"]))
            if unit is None or qty is None or key[1] in existing:
                continue
            if key in items:
                items[key]["payload"]["files"] = sorted({*items[key]["payload"]["files"], file.rel_path})
                continue
            row = {"title": placeholders(r["title"], line), "specs": [placeholders(s, line) for s in r["specs"]][:12],
                   "qty": qty, "unit": unit, "source": f"{file.rel_path.rsplit('/', 1)[-1]} · {r['sheet']}!{r['row']}"}
            items[key] = {"kind": "template", "business_line": line, "fingerprint": fingerprint("template", *key),
                          "payload": {"row": row, "original": r["title"], "files": [file.rel_path]},
                          "source_file_id": file.id, "location": f"{r['sheet']}!{r['row']}", "snippet": r["title"],
                          "confidence": "high"}
    return list(items.values())


# ---- 以往项目 → 项目记录 ----

SHAPES = [("outside_corner", r"outside\s*corner|外转角"), ("U", r"\bU[\s-]*(?:shape|shaped)\b|U\s*形"),
          ("L", r"\bL[\s-]*(?:shape|shaped)\b|L\s*形"), ("curved", r"\bcurved?\b|弧形"),
          ("cube", r"\bcube\b|立方体"), ("ring", r"\bring\b|环幕")]
LED_INPUTS = ["width_mm", "height_mm", "pixel_pitch_mm", "environment", "installation", "maintenance",
              "brightness_required_nits", "viewing_distance_m", "signal_sources"]
PJ_INPUTS = {"width_mm": "wall_width_mm", "height_mm": "wall_height_mm"}


def _pairs(pattern: str, texts: list[tuple[str, str, int]]):
    """在所有行里找「a + b」写法，返回 (a, b, 文件, 位置)。"""
    for text, location, fid in texts:
        if m := re.search(pattern, text, re.I):
            yield int(m[1]), int(m[2]) if m.lastindex and m.lastindex > 1 and m[2] else None, fid, location


def project_record(files: list[dict], projectors: list[dict]) -> dict | None:
    """files：[{id, facts, lines: [(位置, 文字)]}]。返回 {line, shape, inputs, actual, sources}，什么都没认出时为 None。"""
    boq = [(r, f["id"]) for f in files for r in (f["facts"] or {}).get("boq", [])]
    # 先看 BOQ 的行（来源能写到第几行），再看其它正文
    texts = [(s, f"{r['sheet']}!{r['row']}", fid) for r, fid in boq for s in [r["title"], *r["specs"]]]
    texts += [(t, loc, f["id"]) for f in files for loc, chunk in f["lines"] for t in chunk.splitlines()]
    whole = "\n".join(t for t, _, _ in texts)
    line = detect_line(whole)
    if line is None:
        return None
    rec = {"line": line, "shape": next((k for k, p in SHAPES if re.search(p, whole, re.I)), "flat"),
           "inputs": {}, "actual": {}, "sources": {}}
    conf = []

    def put(section, key, value, fid, location, confidence="high"):
        if value is not None and key not in rec[section]:
            rec[section][key] = value
            rec["sources"][key] = {"file_id": fid, "location": location}
            conf.append(confidence)

    best: dict[str, tuple] = {}
    for f in files:
        for x in (f["facts"] or {}).get("fields", []):
            rank = (CONF_RANK[x["confidence"]], -x["count"])
            if x["field"] not in best or rank < best[x["field"]][0]:
                best[x["field"]] = (rank, x, f["id"])
    wanted = {n: n for n in LED_INPUTS} if line == "LED" else PJ_INPUTS
    for field, (_, x, fid) in best.items():
        if field in wanted:
            put("inputs", wanted[field], x["value"], fid, x["location"], x["confidence"])

    def qty_of(pattern, exclude=None, unit=None):
        for r, fid in boq:
            if re.search(pattern, r["title"], re.I) and not (exclude and re.search(exclude, r["title"], re.I)) \
                    and (unit is None or norm_unit(r["unit"]) == unit):
                return r["qty"], fid, f"{r['sheet']}!{r['row']}"
        return None, None, None

    if line == "LED":
        put("actual", "area_m2", *qty_of(r"\bLED\b.*\b(?:screen|display|wall)\b", unit="sqm"))
        put("actual", "controller_qty", *qty_of(r"controller", exclude=r"processor"))
        for a, _, fid, loc in _pairs(r"(\d+)\s*circuits?\b", texts):
            put("actual", "circuits", a, fid, loc)
        for a, b, fid, loc in _pairs(r"power\s*cables?\s*(\d+)\s*\+\s*(\d+)", texts):
            put("actual", "power_cables", a + b, fid, loc)
        for a, b, fid, loc in _pairs(r"CAT\s*6\D{0,3}(\d+)\s*\+\s*(\d+)\s*spare", texts):
            put("actual", "data_runs", a, fid, loc)
            put("actual", "data_cables", a + b, fid, loc)
        for a, _, fid, loc in _pairs(r"spares?:?\s*(\d+)\s*modules?", texts):
            put("actual", "spare_modules", a, fid, loc)
    else:
        put("actual", "projectors", *qty_of(r"projector", exclude=r"\blens\b|mount|bracket|screen"))
        for p in projectors:
            if any(_model_pattern(p["model"]).search(t) for t, _, _ in texts):
                put("inputs", "projector", p["id"], None, "")
                break
        for t, loc, fid in texts:
            if m := re.search(r"(?:throw\s*ratio\D{0,6})?(0\.\d{1,2})\s*:\s*1", t, re.I):
                put("inputs", "lens_throw_ratio", float(m[1]), fid, loc, "medium")
                break
        for a, _, fid, loc in _pairs(r"video\s*(\d+)\s*\+\s*(\d+)", texts):
            put("actual", "video_lines", a, fid, loc)
        for a, _, fid, loc in _pairs(r"control\s*CAT\s*6\s*(\d+)\s*\+\s*(\d+)", texts):
            put("actual", "control_lines", a, fid, loc)
    if not rec["inputs"] and not rec["actual"]:
        return None
    rec["confidence"] = max(conf, key=CONF_RANK.get) if conf else "medium"
    return rec


# ---- 标准答案项目 → 规则参考（回归对比）----

COMPARE = {"LED": ["area_m2", "circuits", "power_cables", "data_runs", "data_cables", "controller_qty", "spare_modules"],
           "PJ": ["projectors", "video_lines", "control_lines"]}


def rule_ids(content: dict) -> dict[str, str]:
    steps = LINES[content["business_line"]]["steps"]
    out = {}
    for rule in content["rules"]:
        for n in (steps[rule["step"]][2] if "step" in rule else [o["name"] for o in rule["outputs"]]):
            out[n] = rule["id"]
    return out


def compare(record: dict, rules: dict, library: dict) -> dict:
    """项目记录跑一遍当前规则，逐条对比实际数量。多面屏的项目记录没有分面尺寸，先不对比。"""
    if record["shape"] not in ("flat", "single") or record["line"] != rules["business_line"]:
        return {"rows": [], "missing": [], "skipped": True}
    result = calculate(rules, library, dict(record["inputs"]))
    values = {ln["name"]: ln["value"] for r in result["rules"] for ln in r["lines"]}
    inputs = {i["name"] for i in rules["inputs"]}
    missing = sorted({m for r in result["rules"] for m in r["missing"] if m in inputs} - set(record["inputs"]))
    ids, rows = rule_ids(rules), []
    for n in COMPARE[record["line"]]:
        if n in record["actual"]:
            rule, actual = values.get(n), record["actual"][n]
            rows.append({"name": n, "rule_id": ids.get(n), "rule": rule, "actual": actual,
                         "match": isinstance(rule, (int, float)) and abs(rule - actual) < 0.01})
    return {"rows": rows, "missing": missing, "skipped": False}


def rule_items(key: str, record: dict, result: dict, rules_version: str) -> list[dict]:
    return [{"kind": "rule", "business_line": record["line"],
             "fingerprint": fingerprint("rule", key, r["name"], r["rule"], r["actual"], rules_version),
             "payload": {"project_key": key, "rule_id": r["rule_id"], "name": r["name"], "rule_value": r["rule"],
                         "actual": r["actual"], "rules_version": rules_version},
             "source_file_id": record["sources"].get(r["name"], {}).get("file_id"),
             "location": record["sources"].get(r["name"], {}).get("location", ""), "snippet": "", "confidence": "medium"}
            for r in result["rows"] if not r["match"] and r["rule"] is not None]
