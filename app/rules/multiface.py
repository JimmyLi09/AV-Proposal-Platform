"""多面屏（CR-7）：LED 的 S1–S7，投影的 P18–P22。

屏形先由程序从资料文字里猜，人确认；每一面单独输入尺寸（LED 还有朝向、信号 / 电源输入点、防护、压在上面的东西）。
- LED：每面单独跑 F1–F16（回路、配电箱、数据线按面算，因为每面有自己的输入点），同型号备品按整屏合计；
  再按 S1–S7 合起来检查转角、画布与处理器输出、特殊面和资料一致性。
- 投影：每面单独按 P1–P10 排投影机（不跨角投射），再按投影机总数跑 P11–P17；P20 查内角两侧第 1 台机位冲突，
  P21 展开画布，P22 弧形 / 环幕要几何校正。
数量全部来自规则；这里只做按面拆分、合计和检查。
"""
import math
from decimal import Decimal

from ..diagram import faces_svg
from ..i18n import tr
from . import led as L
from . import pj as P
from .expr import fmt, num

MULTI_KEYS = {"shape", "faces", "corners", "total_weight_kg", "reference_circuits", "reference_data_cables"}
SINGLE = {"flat", "single"}
SHAPES = {"LED": ["flat", "L", "L_wall_floor", "U", "outside_corner", "curved", "cube", "custom"],
          "PJ": ["single", "L", "U", "curved", "ring", "wall_floor"]}
PJ_FACE_RULES = {f"P{i}" for i in range(1, 11)}  # 每面单独跑的几何规则
PJ_FACE_INPUTS = {"wall_width_mm", "wall_height_mm", "available_depth_mm", "mount_height_m"}  # 每面可以不同的输入
SPARE_RULES = {"F8", "F10"}  # 同型号备品按整屏合计
PROCESSOR_RULES = {"F13"}  # 视频处理器整屏 1 台，每面接 1 路输出（S5）
WHOLE = ("processor_qty",)  # 整屏只有一份的数量，客户版 BOQ 放在共用组
POOLED = ("spare_modules", "spare_psu", "spare_rx_cards")  # 整屏合计的备品数，客户版 BOQ 只在共用组出一次

# 资料文字里的关键词 → 屏形（只是先猜，人要确认）
GUESS = [
    ("outside_corner", ("外转角", "outside corner", "包柱", "column wrap")),
    ("L_wall_floor", ("wall + floor", "墙 + 地面", "地面屏", "floor led")),
    ("wall_floor", ("wall + floor", "墙 + 地面", "地面投影")),
    ("cube", ("立方", "cube")),
    ("ring", ("环幕", "360", "ring")),
    ("curved", ("弧形", "curved", "arc ")),
    ("U", ("u-shape", "u 形", "u形", "三面")),
    ("L", ("l-shape", "l 形", "l形", "转角", "corner")),
]


def is_multi(inputs: dict) -> bool:
    return inputs.get("shape") not in (None, *SINGLE) and bool(inputs.get("faces"))


def guess_shape(line: str, text: str) -> str:
    low = (text or "").lower()
    for shape, words in GUESS:
        if shape in SHAPES[line] and any(w in low for w in words):
            return shape
    return SHAPES[line][0]


def shape_label(shape: str) -> str:
    return {"flat": tr("平面单屏", "Flat"), "single": tr("单面墙", "Single wall"), "L": tr("L 形（内转角）", "L-shape (inside corner)"),
            "L_wall_floor": tr("L 形（墙 + 地面）", "L-shape (wall + floor)"), "U": tr("U 形（三面）", "U-shape (three faces)"),
            "outside_corner": tr("外转角", "Outside corner"), "curved": tr("弧形", "Curved"), "cube": tr("立方体", "Cube"),
            "custom": tr("自定义", "Custom"), "ring": tr("环幕", "Ring screen"),
            "wall_floor": tr("墙 + 地面", "Wall + floor")}.get(shape, shape)


def _n(x) -> str:
    return fmt(num(x)) if x is not None else "—"


def _row(rid: str, title: str, display: str = "", check: str | None = None, note: str = "", trace: str = "",
         status: str = "set", missing: list | None = None) -> dict:
    """多面屏检查的一行，格式和规则结果一样（计算依据页、校验列表直接显示）。"""
    return {"id": rid, "title": title, "note": note, "lines": [], "display": display, "trace": trace, "check": check,
            "status": status, "params": [], "missing": missing or [], "error": None, "manual": []}


def _worst(checks: list[str]) -> str | None:
    order = [None, "PASS", "NOTE", "BLOCK"]
    return max(checks, key=order.index, default=None)


def _rule_checks(checks: list[dict], rule: str) -> list[str]:
    return [c["check"] for c in checks if c["rule"] == rule]


def _values(rules: list[dict]) -> dict:
    return {ln["name"]: ln["value"] for r in rules for ln in r["lines"]}


def source_conflicts(faces: list[dict], module_w, module_h) -> list[dict]:
    """S7：同一面同一尺寸在不同资料里不一样，又还没选定 → 冲突；列出是否模组整数倍和两个吸附选项。"""
    out = []
    for f in faces:
        for field, module in (("width_mm", module_w), ("height_mm", module_h)):
            srcs = f.get(field.replace("_mm", "_sources")) or []
            if len({s["value"] for s in srcs}) > 1 and f.get(field) in (None, ""):
                rows = []
                for s in srcs:
                    fits = bool(module) and s["value"] % module == 0
                    low = s["value"] // module * module if module else None
                    rows.append(s | {"fits": fits, "options": [] if fits or not module else [low, low + module]})
                out.append({"face": f["id"], "field": field, "sources": rows})
    return out


def _plan_notes(faces: list[dict]) -> list[dict]:
    """S7：选定的尺寸和平面图上的墙宽 / 墙高不一样时提示（多了可能放不下）。"""
    out = []
    for f in faces:
        for field, zh, en in (("width_mm", "宽", "width"), ("height_mm", "高", "height")):
            chosen = f.get(field)
            for s in f.get(field.replace("_mm", "_sources")) or []:
                if s.get("kind") == "plan" and chosen not in (None, "") and s["value"] != chosen:
                    diff = chosen - s["value"]
                    out.append({"rule": "S7", "check": "NOTE", "text": tr(
                        f"{f['id']} 面{zh} {_n(chosen)} 比平面图 {_n(s['value'])} {'多' if diff > 0 else '少'} {_n(abs(diff))} mm",
                        f"Face {f['id']} {en} {_n(chosen)} is {_n(abs(diff))} mm {'more' if diff > 0 else 'less'} than the plan's "
                        f"{_n(s['value'])}")})
    return out


def _canvas(faces: list[dict], key_w: str, key_h: str) -> list[int]:
    """展开画布：墙面横向展开；地面 / 顶面接在墙的下 / 上方（纵向展开）。"""
    walls = [f for f in faces if f.get("orientation", "wall") == "wall"] or faces
    flats = [f for f in faces if f not in walls]
    width = max(sum(f["values"][key_w] for f in walls), max((f["values"][key_w] for f in flats), default=0))
    height = max(f["values"][key_h] for f in walls) + sum(f["values"][key_h] for f in flats)
    return [int(width), int(height)]


# ---- LED · S1–S7 ----

def calculate_led(content: dict, library: dict, inputs: dict, cabinet_id: str | None, run) -> dict:
    rec = L.recommend(inputs, library, cabinet_id)
    cab, faces, corners = rec["cabinet"], inputs["faces"], inputs.get("corners") or []
    common = {k: v for k, v in inputs.items() if k not in MULTI_KEYS}
    pinputs, catalog = L.product_inputs(cab), L.catalog(library, cab)
    params = {p["name"]: p["value"] for p in content["params"]}
    shape = inputs["shape"]
    rows = [_row("S1", tr("屏形", "Screen shape"), shape_label(shape), "PASS",
                 tr("程序先猜，人确认后计算", "Guessed by the program, confirmed by a person"))]
    checks: list[dict] = []
    out = {"choices": {}, "recommendation": rec, "faces": [], "suggestions": [], "diagram": None, "manual": [],
           "boq": [], "values": common | pinputs,
           "multi": {"shape": shape, "totals": {}, "checks": checks, "conflicts": [], "corners": []}}

    lacking = [f["id"] for f in faces if f.get("width_mm") in (None, "") and not f.get("width_sources")
               or f.get("height_mm") in (None, "") and not f.get("height_sources")]
    conflicts = source_conflicts(faces, pinputs.get("module_w_mm"), pinputs.get("module_h_mm")) if cab else []
    out["multi"]["conflicts"] = conflicts
    rows.append(_row("S2", tr("分面输入", "Faces"), tr(f"{len(faces)} 面", f"{len(faces)} faces"),
                     missing=[tr(f"{x} 面尺寸", f"face {x} size") for x in lacking]))
    for c in conflicts:
        checks.append({"rule": "S7", "check": "BLOCK", "text": tr(
            f"{c['face']} 面{'宽' if c['field'] == 'width_mm' else '高'}：{len(c['sources'])} 份资料对不上，选定前不能计算",
            f"Face {c['face']} {'width' if c['field'] == 'width_mm' else 'height'}: {len(c['sources'])} sources disagree; "
            f"choose one before calculating")})
    if not cab or lacking or conflicts:
        rows.append(_row("S7", tr("资料一致性", "Source consistency"), check=_worst(_rule_checks(checks, "S7"))))
        out["rules"] = rows
        return out

    # S5：视频处理器整屏 1 台。每面先按不含发送的处理器配控制器（F11），再按整屏的像素和网线数选处理器（F13）；
    # 选出的是含发送的，再按面算一次，各面的控制器就包含在这台处理器里
    face_content = {**content, "rules": [r for r in content["rules"] if r["id"] not in PROCESSOR_RULES]}
    face_inputs = [common | {"width_mm": f["width_mm"], "height_mm": f["height_mm"]} | pinputs for f in faces]
    split = catalog | {"processors": [p for p in catalog.get("processors", []) if not p["sending"]]}
    results = [run(face_content, x, split) for x in face_inputs]
    load = [_values(r["rules"]) for r in results]
    proc_rules, pv = [], {}
    if all(v.get(k) is not None for v in load for k in ("total_pixels", "data_runs")):
        proc_rules = run({**content, "rules": [r for r in content["rules"] if r["id"] in PROCESSOR_RULES]},
                         {"total_pixels": sum(num(v["total_pixels"]) for v in load),
                          "data_runs": sum(num(v["data_runs"]) for v in load), "processor_outputs": len(faces)}
                         | ({"signal_sources": common["signal_sources"]} if common.get("signal_sources") else {}),
                         catalog)["rules"]
        pv = _values(proc_rules)
        if pv.get("processor_sending"):
            chosen = [p for p in catalog["processors"] if p["id"] == pv["processor_id"]]
            results = [run(face_content, x, catalog | {"processors": chosen}) for x in face_inputs]

    for f, res in zip(faces, results):
        out["faces"].append({k: f.get(k) for k in ("id", "name", "orientation", "width_mm", "height_mm", "signal_point",
                                                  "power_point", "protection", "load")}
                            | {"rules": res["rules"], "choices": res["choices"], "values": _values(res["rules"])})
        for name, opts in res["choices"].items():
            checks.append({"rule": "S2", "check": "BLOCK", "text": tr(
                f"{f['id']} 面{'宽' if name == 'width_mm' else '高'} {_n(f[name])} 不是模组整数倍，请选 {_n(opts[0])} 或 {_n(opts[1])}",
                f"Face {f['id']} {'width' if name == 'width_mm' else 'height'} {_n(f[name])} is not a module multiple; "
                f"choose {_n(opts[0])} or {_n(opts[1])}")})
        for r in res["rules"]:
            if r["check"] == "BLOCK":
                checks.append({"rule": f"{f['id']} {r['id']}", "check": "BLOCK", "text": f"{f['id']} · {r['id']} {r['title']}"
                               + (tr("：", ": ") + r["note"] if r["note"] else "")})
    rows[1]["check"] = _worst(_rule_checks(checks, "S2"))
    if rows[1]["check"] == "BLOCK":
        out["rules"] = rows
        return out

    fv = [f["values"] for f in out["faces"]]
    total = lambda k: sum((num(v.get(k) or 0) for v in fv), Decimal(0))  # noqa: E731
    modules, cabinets = total("modules"), total("cabinets")
    spare_run = run({**content, "rules": [r for r in content["rules"] if r["id"] in SPARE_RULES]},
                    {"modules": modules, "cabinets": cabinets}, catalog)
    spares = _values(spare_run["rules"])
    canvas = _canvas(out["faces"], "res_x", "res_y")
    t = {"canvas_px": canvas, "modules": int(modules), "cabinets": int(cabinets), "area_m2": float(total("area_m2")),
         "power_kw": float(total("power_kw")), "circuits": int(total("circuits")),
         "power_cables": int(total("power_cables")), "db_boxes": int(total("db_boxes")),
         "data_runs": int(total("data_runs")), "data_cables": int(total("data_cables")),
         "power_jumpers": int(total("power_jumpers")), "power_jumper_m": float(total("power_jumper_m")),
         "data_jumpers": int(total("data_jumpers")), "data_jumper_m": float(total("data_jumper_m")),
         "spare_modules": spares.get("spare_modules"), "spare_psu": spares.get("spare_psu"),
         "spare_rx_cards": spares.get("spare_rx_cards"), "processor_outputs": len(faces)}
    out["multi"]["totals"] = t
    out["multi"]["spare_rules"] = spare_run["rules"]

    # S3 按面计算：和参考资料（供应商图、原方案）的数量对比
    for key, ref, zh, en, u_zh, u_en in (("circuits", "reference_circuits", "回路", "circuits", "路", ""),
                                         ("data_cables", "reference_data_cables", "数据线", "data cables", "根", "")):
        if inputs.get(ref) not in (None, "") and num(inputs[ref]) != t[key]:
            checks.append({"rule": "S3", "check": "NOTE", "text": tr(
                f"规则算出{zh} {t[key]} {u_zh}，参考资料是 {_n(inputs[ref])} {u_zh}",
                f"The rules give {t[key]} {en}; the reference has {_n(inputs[ref])}")})
    rows.append(_row("S3", tr("按面计算", "Per-face calculation"),
                     tr(f"{t['circuits']} 路回路 · {t['data_cables']} 根数据线 · {t['db_boxes']} 个配电箱",
                        f"{t['circuits']} circuits · {t['data_cables']} data cables · {t['db_boxes']} DB boxes"),
                     _worst(_rule_checks(checks, "S3")), tr("回路、配电箱、数据线按面算；同型号备品按整屏合计",
                                                         "Circuits, DB boxes and data cables per face; spares pooled for the whole screen"),
                     trace=" + ".join(f"{f['id']} {f['values'].get('circuits', '—')}" for f in out["faces"]) + f" = {t['circuits']}",
                     missing=[f"{f['id']} · {r['id']}" for f in out["faces"] for r in f["rules"] if r["missing"] or r["error"]]))

    # S4 转角：点间距一致；内角要确认哪面压哪面；外转角用转角箱体或 45° 切角模组
    checks.append({"rule": "S4", "check": "PASS", "text": tr(f"各面点间距一致（P{_n(inputs.get('pixel_pitch_mm'))}）",
                                                           f"Same pixel pitch on every face (P{_n(inputs.get('pixel_pitch_mm'))})")})
    for c in corners:
        a, b = c["between"]
        if c["type"] == "outside_corner":
            text = tr(f"{a} / {b} 外转角：用转角箱体或 45° 切角模组，两面按外边尺寸算，转角处像素要连续",
                      f"{a} / {b} outside corner: use corner cabinets or 45° bevel modules, size both faces to the outer edge, "
                      "keep pixels continuous at the corner")
        elif c["type"] == "fold_wall_to_floor":
            text = tr(f"{a} / {b} 墙转地面：转角处像素要连续", f"{a} / {b} wall to floor: keep pixels continuous at the fold")
        elif c.get("overlap"):
            text = tr(f"{a} / {b} 内转角：{c['overlap']}", f"{a} / {b} inside corner: {c['overlap']}")
        else:
            text = tr(f"{a} / {b} 内转角：请确认哪面压哪面、净宽怎么扣", f"{a} / {b} inside corner: confirm which face overlaps and the net width")
        checks.append({"rule": "S4", "check": "NOTE", "text": text})
    rows.append(_row("S4", tr("转角", "Corners"), tr(f"{len(corners)} 个转角", f"{len(corners)} corners"),
                     _worst(_rule_checks(checks, "S4"))))

    # S5 画布与处理器：每面 1 路输出，单路不超过上限
    limit = num(params.get("output_max_px_w") or 3840)
    widest = max(f["values"]["res_x"] for f in out["faces"])
    over = [f for f in out["faces"] if f["values"]["res_x"] > limit]
    for f in over:
        checks.append({"rule": "S5", "check": "BLOCK", "text": tr(
            f"{f['id']} 面 {f['values']['res_x']} px 超过每路输出上限 {_n(limit)} px",
            f"Face {f['id']} {f['values']['res_x']} px exceeds the {_n(limit)} px output limit")})
    if not over:
        checks.append({"rule": "S5", "check": "PASS", "text": tr(f"每面输出不超过 {_n(limit)} px（最宽 {widest} px）",
                                                               f"Every face output ≤ {_n(limit)} px (widest {widest} px)")})
    if pv.get("processor_id"):  # 整屏 1 台处理器（F13）：含发送的各面直接接网口；独立处理器每面接 1 路输出
        outs = next(p for p in catalog["processors"] if p["id"] == pv["processor_id"]).get("outputs")
        if pv.get("processor_sending"):
            checks.append({"rule": "S5", "check": "PASS", "text": tr(
                f"处理器 {pv['processor']} 含发送：整屏 1 台，各面直接接它的网口",
                f"Processor {pv['processor']} has sending: one for the whole screen, every face connects to its ports")})
        elif outs:
            checks.append({"rule": "S5", "check": "PASS", "text": tr(
                f"处理器 {pv['processor']}：整屏 1 台，{_n(outs)} 路输出，每面 1 路（{len(faces)} 面）",
                f"Processor {pv['processor']}: one for the whole screen, {_n(outs)} outputs, one per face ({len(faces)} faces)")})
        else:
            checks.append({"rule": "S5", "check": "NOTE", "text": tr(
                f"处理器 {pv['processor']} 的输出路数待核对规格书（要 ≥ {len(faces)} 路，每面 1 路）",
                f"Processor {pv['processor']}: output count to be checked against the datasheet "
                f"(≥ {len(faces)} needed, one per face)")})
    rows.append(_row("S5", tr("画布与处理器", "Canvas & processor"),
                     tr(f"{canvas[0]} × {canvas[1]} · {len(faces)} 路输出", f"{canvas[0]} × {canvas[1]} · {len(faces)} outputs"),
                     _worst(_rule_checks(checks, "S5")),
                     tr("墙面横向展开，地面 / 顶面纵向接上；每面接处理器的一路输出，各路同步",
                        "Walls unfold horizontally, floor / ceiling faces stack vertically; one synchronised processor output per face")))
    rows += proc_rules  # F13 按整屏算的那一行，放在 S5 后面

    # S6 特殊面：地面要防护和承重，顶面要吊挂，有东西压在屏上要列出
    for f in faces:
        orient = f.get("orientation", "wall")
        if orient == "floor":
            if "gob" in (f.get("protection") or "").lower():
                checks.append({"rule": "S6", "check": "PASS", "text": tr(f"{f['id']} 面是地面面，已写 GOB 防护",
                                                                       f"Face {f['id']} is a floor face with GOB protection")})
            else:
                checks.append({"rule": "S6", "check": "BLOCK", "text": tr(f"{f['id']} 面是地面面，要写防护（例如 GOB）",
                                                                        f"Face {f['id']} is a floor face; protection is required (e.g. GOB)")})
        elif orient == "ceiling":
            checks.append({"rule": "S6", "check": "NOTE", "text": tr(f"{f['id']} 面是顶面，要吊挂并核重量",
                                                                   f"Face {f['id']} is a ceiling face; hanging and weight to check")})
        if f.get("load"):
            checks.append({"rule": "S6", "check": "NOTE", "text": tr(f"{f['id']} 面上有：{f['load']}", f"On face {f['id']}: {f['load']}")})
    if inputs.get("total_weight_kg") not in (None, ""):
        checks.append({"rule": "S6", "check": "NOTE", "text": tr(
            f"总重 {_n(inputs['total_weight_kg'])} kg，请结构确认（背墙加固、地面承重）",
            f"Total weight {_n(inputs['total_weight_kg'])} kg; structural check needed (wall reinforcement, floor load)")})
    special = [f["id"] for f in faces if f.get("orientation", "wall") != "wall" or f.get("load")]
    rows.append(_row("S6", tr("特殊面", "Special faces"), " · ".join(special) or tr("无", "None"), _worst(_rule_checks(checks, "S6"))))

    checks.extend(_plan_notes(faces))
    s7 = _rule_checks(checks, "S7")
    rows.append(_row("S7", tr("资料一致性", "Source consistency"),
                     tr(f"{len(s7)} 条提示", f"{len(s7)} notes") if s7 else tr("一致", "Consistent"), _worst(s7) or "PASS"))
    out["rules"] = rows
    params = {p["name"]: p["value"] for p in content["params"] if p["name"] in L.BOQ_EXTRA}  # 空开、线径（CR-13）
    out["values"] = L.boq_context({k: v for k, v in t.items() if not isinstance(v, list)} | pv, cab, common | pinputs | params)
    for f in out["faces"]:  # 客户版 BOQ 按面分组用
        f["boq_context"] = L.boq_context(f["values"], cab, common | params | {"width_mm": f["width_mm"],
                                                                              "height_mm": f["height_mm"]})
    out["boq"] = _led_boq(out["faces"], cab, library, spares | pv, common)
    out["diagram"] = _led_diagram(out["faces"], cab, library, pv, common, out["boq"])
    return out


def _led_boq(faces: list[dict], cab: dict, library: dict, whole: dict, inputs: dict) -> list[dict]:
    """内部明细：每面一组（编号前加面），备品和视频处理器按整屏一组（whole：整屏的值）。"""
    lines = []
    for f in faces:
        v = {k: x for k, x in f["values"].items() if k not in POOLED}
        for line in L.boq(v, cab, {"width_mm": f["width_mm"], "height_mm": f["height_mm"]}, library):
            lines.append(line | {"key": f"{f['id']}:{line['key']}" if line["key"] else "", "item": f"{f['id']} · {line['item']}"})
    for line in L.boq(whole, cab, inputs, library):
        if line["rule"] in SPARE_RULES | PROCESSOR_RULES:
            lines.append(line | {"item": tr("整屏 · ", "Whole screen · ") + line["item"]})
    return lines


def _led_diagram(faces: list[dict], cab: dict, library: dict, pv: dict, inputs: dict, boq_lines: list[dict]) -> dict | None:
    """多面屏的 Level 1 / Level 2 示意图，和单屏一样由内部明细生成，每台设备、每条线缆都对应明细行：
    信号源 → 视频处理器（整屏 1 台，每面 1 路输出）→ 每面的控制器 → 每面的屏；每面的配电箱接自己那一面。
    处理器含发送时不画控制器，处理器直接用网线接各面。"""
    if any(f["values"].get("cabinets") is None for f in faces):
        return None
    products = {p["id"]: p for p in library["products"]}
    spare = tr("备用", "spare")
    sources = inputs.get("signal_sources") or 1
    sending = bool(pv.get("processor_sending"))
    nodes = {"source": {"title": tr("信号源", "Content source"), "model": tr("播放器或电脑", "Player or PC"), "qty": sources,
                        "detail": "", "boq": [], "supply": "owner"}}
    if pv.get("processor_id") in products:
        nodes["processor"] = {
            "title": tr("处理器（含发送）", "Processor with sending") if sending else tr("视频处理器", "Video processor"),
            "model": products[pv["processor_id"]]["model"], "qty": pv["processor_qty"],
            "detail": tr("整屏 1 台 · 各面接网口", "Whole screen · faces on its ports") if sending
            else tr(f"整屏 1 台 · 每面 1 路输出（{len(faces)} 路）", f"Whole screen · one output per face ({len(faces)})"),
            "boq": [pv["processor_id"]], "supply": "boq"}
    else:
        nodes["processor"] = {"title": tr("视频处理器", "Video processor"), "model": "—", "qty": "", "boq": [], "supply": "missing",
                              "detail": tr("F13 未选出（整屏）", "F13 not selected (whole screen)")}
    links = [{"from": "source", "to": "processor", "cable": "HDMI", "qty": str(sources), "boq": None, "supply": "owner"}]
    rows = []
    for f in faces:
        v, fid = f["values"], f["id"]
        label = f"{fid} · {f['name']}" if f.get("name") else fid
        row = {"id": fid, "screen": f"{fid}:screen"}
        nodes[row["screen"]] = {
            "title": tr(f"LED 屏 {label}", f"LED wall {label}"), "model": cab["model"],
            "qty": tr(f"{v['cabinets']} 个箱体", f"{v['cabinets']} cabinets"),
            "detail": f"{_n(f['width_mm'])} × {_n(f['height_mm'])} · P{_n(inputs.get('pixel_pitch_mm'))}",
            "boq": [f"{fid}:{cab['id']}:{w}x{h}" for w, h, _ in v.get("cabinet_counts") or []], "supply": "boq"}
        feed = "processor"
        if not sending:
            feed = row["controller"] = f"{fid}:controller"
            nodes[feed] = {"title": tr(f"控制器 {fid}", f"Controller {fid}"), "model": products[v["controller_id"]]["model"],
                           "qty": v["controller_qty"],
                           "detail": tr(f"{v['ports']} 口", f"{v['ports']} ports") + f" · {v['capacity_mp']:.1f} MP",
                           "boq": [f"{fid}:{v['controller_id']}"], "supply": "boq"} if v.get("controller_id") in products else {
                "title": tr(f"控制器 {fid}", f"Controller {fid}"), "model": "—", "qty": "", "boq": [], "supply": "missing",
                "detail": tr("F11 阻断：产品库里没有合适的", "F11 blocked: nothing suitable in the library")}
            links.append({"from": "processor", "to": feed, "cable": "HDMI", "qty": "1", "boq": None, "supply": "included"})
        if v.get("data_runs") is not None:
            links.append({"from": feed, "to": row["screen"], "cable": "Cat6",
                          "qty": f"{v['data_runs']} + {v['data_cables'] - v['data_runs']} {spare}",
                          "boq": f"{fid}:data_cable", "supply": "boq"})
        if v.get("db_boxes") is not None:
            row["db_box"] = f"{fid}:db_box"
            nodes[row["db_box"]] = {"title": tr(f"配电箱 {fid}", f"DB box {fid}"), "model": tr("定制", "Custom"),
                                    "qty": v["db_boxes"], "detail": tr("每回路一个 MCB", "One MCB per circuit")
                                    + f" · {v.get('power_kw', 0):.2f} kW", "boq": [f"{fid}:db_box"], "supply": "boq"}
            if v.get("power_cables") is not None:
                links.append({"from": row["db_box"], "to": row["screen"], "cable": tr("电源线", "Power cable"),
                              "qty": f"{v['circuits']} + {v['power_cables'] - v['circuits']} {spare}",
                              "boq": f"{fid}:power_cable", "supply": "boq"})
        rows.append(row)
    for x in [*nodes.values(), *links]:
        x["manual"] = False  # 多面屏没有推荐页手动覆盖（CR-5）
    keys = {ln["key"] for ln in boq_lines if ln["key"]}
    paren = lambda x: tr(f"（{x}）", f" ({x})")  # noqa: E731
    unmatched = [n["title"] + paren(k) for n in nodes.values() if n["supply"] == "boq" for k in n["boq"] if k not in keys]
    unmatched += [n["title"] + paren(n["detail"]) for n in nodes.values() if n["supply"] == "missing"]
    unmatched += [x["cable"] + paren(x["boq"]) for x in links if x["supply"] == "boq" and x["boq"] not in keys]
    d = {"faces": rows, "nodes": nodes, "links": links, "unmatched": unmatched}
    return d | {"svg": faces_svg(d)}


# ---- 投影 · P18–P22 ----

def calculate_pj(content: dict, library: dict, inputs: dict, cabinet_id: str | None, run) -> dict:
    rec = P.recommend(inputs, library, cabinet_id)
    proj, faces, corners = rec["cabinet"], inputs["faces"], inputs.get("corners") or []
    common = {k: v for k, v in inputs.items() if k not in MULTI_KEYS}
    pinputs, catalog = P.product_inputs(proj), P.catalog(library, proj)
    params = {p["name"]: p["value"] for p in content["params"]}
    shape = inputs["shape"]
    rows = [_row("P18", tr("屏形与分面", "Shape & faces"), shape_label(shape) + tr(f" · {len(faces)} 面", f" · {len(faces)} faces"),
                 "PASS", tr("程序先猜，人确认后计算", "Guessed by the program, confirmed by a person"))]
    out = {"choices": {}, "recommendation": rec, "faces": [], "suggestions": [], "diagram": None, "manual": [], "boq": [],
           "values": common | pinputs, "multi": {"shape": shape, "totals": {}, "checks": [], "conflicts": [], "corners": []}}
    lacking = [f["id"] for f in faces if f.get("width_mm") in (None, "")]
    if not proj or lacking:
        rows[0]["missing"] = [tr(f"{x} 面宽", f"face {x} width") for x in lacking]
        out["rules"] = rows
        return out

    face_content = {**content, "rules": [r for r in content["rules"] if r["id"] in PJ_FACE_RULES]}
    for f in faces:
        fin = common | {"wall_width_mm": f["width_mm"]} | {
            k: f[src] for k, src in (("wall_height_mm", "height_mm"), ("available_depth_mm", "depth_mm"),
                                     ("mount_height_m", "mount_height_m")) if f.get(src) not in (None, "")}
        res = run(face_content, fin | pinputs, catalog)
        out["faces"].append({k: f.get(k) for k in ("id", "name", "width_mm", "height_mm")}
                            | {"rules": res["rules"], "choices": {}, "values": _values(res["rules"]),
                               "inputs": {k: v for k, v in fin.items() if k in PJ_FACE_INPUTS}})  # 专属图按面画要用
    rows.append(_row("P19", tr("按面排投影", "Projectors per face"),
                     " · ".join(f"{f['id']} {_n(f['values'].get('projectors'))}" for f in out["faces"]),
                     note=tr("每面独立按 P1–P10 排投影，不跨角投射；投影机在两端角线内均匀排开",
                             "Each face is laid out with P1–P10 on its own, no projection across corners; projectors spread evenly between the corner lines"),
                     missing=[f"{f['id']} P{x}" for f in out["faces"] for r in f["rules"] if r["missing"] for x in [r["id"][1:]]]))
    if rows[-1]["missing"]:
        out["rules"] = rows
        return out

    fv = {f["id"]: f["values"] for f in out["faces"]}
    n = int(sum((num(v["projectors"]) for v in fv.values()), Decimal(0)))
    canvas = [int(sum(num(v["blended_px_x"]) for v in fv.values())), int(max(num(v["blended_px_y"]) for v in fv.values()))]

    # P20 转角机位冲突：内角两侧第 1 台投影机（各在自己画面第 1 格的中线上、离墙 d）之间的距离
    limit = num(params["corner_clash_m"])
    for c in corners:
        a, b = c["between"]
        if c.get("type", "inside_90") != "inside_90" or a not in fv or b not in fv:
            continue
        wa, da, wb, db = (num(fv[a]["image_w_m"]), num(fv[a]["distance_m"]), num(fv[b]["image_w_m"]), num(fv[b]["distance_m"]))
        dist = Decimal(math.hypot(wa / 2 - db, da - wb / 2)).quantize(Decimal("0.01"))
        result = "PASS" if dist >= limit else "NOTE" if c.get("resolution") else "BLOCK"
        out["multi"]["corners"].append({"between": [a, b], "distance_m": float(dist), "result": result,
                                        "resolution": c.get("resolution") or ""})
    clash = [c for c in out["multi"]["corners"] if c["result"] != "PASS"]
    rows.append(_row("P20", tr("转角机位冲突", "Corner clash"),
                     " · ".join(f"{'/'.join(c['between'])} {c['distance_m']:.2f} m" for c in out["multi"]["corners"]) or "—",
                     _worst([c["result"] for c in out["multi"]["corners"]]) or "PASS",
                     tr("；", "; ").join(
                         tr(f"{'/'.join(c['between'])} 第 1 台相距 {c['distance_m']:.2f} m，小于 {_n(limit)} m",
                            f"{'/'.join(c['between'])} first projectors {c['distance_m']:.2f} m apart, under {_n(limit)} m")
                         + (tr(f"；已人工处理：{c['resolution']}", f"; resolved by hand: {c['resolution']}") if c["resolution"]
                            else tr("：错开挂高 / 镜头位移 / 改吊架，记录后才能继续",
                                    ": stagger heights / lens shift / change mounts, and record it to continue")) for c in clash),
                     status="sample"))

    sys_content = {**content, "rules": [r for r in content["rules"] if r["id"] not in PJ_FACE_RULES]}
    system = run(sys_content, common | pinputs | {"projectors": n, "blended_px_x": canvas[0], "blended_px_y": canvas[1]}, catalog)
    for r in system["rules"]:
        if r["check"] == "BLOCK":
            out["multi"]["checks"].append({"rule": r["id"], "check": "BLOCK", "text": f"{r['id']} {r['title']}：{r['note']}"})
    sv = _values(system["rules"])
    outputs = sv.get("blender_outputs")
    rows.append(_row("P21", tr("展开画布", "Unfolded canvas"), f"{canvas[0]} × {canvas[1]}",
                     "PASS" if outputs is not None and (n < 2 or num(outputs) >= n) else "BLOCK",
                     tr(f"宽 = 各面融合后像素之和，高取各面最大；融合器输出 ≥ 投影机总数 {_n(n)}",
                        f"Width = sum of blended pixels per face, height = the largest; blender outputs ≥ {_n(n)} projectors"),
                     trace=" + ".join(f"{fid} {_n(v['blended_px_x'])}" for fid, v in fv.items()) + f" = {canvas[0]}"))
    curved = shape in ("curved", "ring")
    blender = next((b for b in catalog["blenders"] if b["id"] == sv.get("blender_id")), None)
    rows.append(_row("P22", tr("弧形 / 环幕几何校正", "Curved / ring geometry correction"),
                     tr("需要" if curved else "不适用", "Required" if curved else "Not applicable"),
                     ("PASS" if blender and blender["curved"] else "BLOCK") if curved else "PASS",
                     tr("弧形幕、环幕必须几何校正，融合器不支持曲面校正时阻断",
                        "Curved and ring screens need geometry correction; blocked when the blender cannot do it")))
    out["multi"]["totals"] = {"projectors": n, "canvas_px": canvas, "blender_outputs_min": n}
    out["rules"] = rows + system["rules"]
    first = fv[out["faces"][0]["id"]]
    values = sv | {"projectors": n, "blended_px_x": canvas[0], "blended_px_y": canvas[1]} | {
        k: first[k] for k in ("lens", "lens_id", "throw_ratio", "distance_m") if k in first}
    out["boq"] = P.boq(values, proj, common, library)
    out["values"] = P.boq_context(values, proj, common)
    out["diagram"] = _pj_diagram(out["faces"], proj, values, out["boq"])
    return out


def _pj_diagram(faces: list[dict], proj: dict, values: dict, boq_lines: list[dict]) -> dict:
    """多面投影的 Level 1 / Level 2 示意图（和单面墙一样由内部明细生成）：播控电脑 → 融合器（每台投影机 1 路输出）→
    每面的投影机 → 每面的墙，每面一行。视频线按 P15「视频线 = 台数」每面写这面的台数，备用写在融合器上（明细里是整套一行）。"""
    from ..products.library import name
    nodes = {"source": {"title": tr("播控电脑", "Media PC"), "model": "—", "qty": 1, "detail": "", "boq": ["media_pc"],
                        "supply": "boq"}}
    spare = (tr(f"视频线 {_n(values['video_lines'])} + {_n(values['video_spare'])} 备用",
                f"Video {_n(values['video_lines'])} + {_n(values['video_spare'])} spare")
             if values.get("video_lines") is not None else "")
    nodes["blender"] = {"title": tr("融合器", "Blender"), "model": values["blender"], "qty": values["blender_qty"],
                        "detail": tr(f"{_n(values['blender_outputs'])} 路输出", f"{_n(values['blender_outputs'])} outputs")
                        + (" · " + spare if spare else ""), "boq": [values["blender_id"]], "supply": "boq"} \
        if values.get("blender_qty") else {"title": tr("融合器", "Blender"), "model": "—", "qty": "", "boq": [], "supply": "missing",
                                           "detail": tr("P11 未选出", "P11 not selected")}
    links = [{"from": "source", "to": "blender", "cable": "HDMI", "qty": "1", "boq": None, "supply": "included"}]
    rows = []
    for f in faces:
        fid, v = f["id"], f["values"]
        label = f"{fid} · {f['name']}" if f.get("name") and f["name"] != fid else fid
        row = {"id": fid, "projector": f"{fid}:projector", "screen": f"{fid}:screen"}
        nodes[row["projector"]] = {"title": tr(f"投影机 {fid}", f"Projector {fid}"), "model": name(proj), "qty": v["projectors"],
                                   "detail": f"{v.get('lens', '—')}", "boq": [proj["id"]], "supply": "boq"}
        nodes[row["screen"]] = {"title": tr(f"投影墙 {label}", f"Wall {label}"), "model": "—",
                                "qty": f"{_n(f['inputs'].get('wall_width_mm'))} × {_n(f['inputs'].get('wall_height_mm'))}",
                                "detail": tr("幕面 / 涂料视现场", "Surface / paint subject to site"), "boq": [], "supply": "owner"}
        if values.get("video_lines") is not None:
            links.append({"from": "blender", "to": row["projector"], "cable": values.get("transport", ""),
                          "qty": _n(v["projectors"]), "boq": "video_cable", "supply": "boq"})
        links.append({"from": row["projector"], "to": row["screen"], "cable": tr("投射", "Projection"), "qty": "", "boq": None,
                      "supply": "included"})
        rows.append(row)
    for x in [*nodes.values(), *links]:
        x["manual"] = False
    keys = {ln["key"] for ln in boq_lines if ln["key"]}
    paren = lambda x: tr(f"（{x}）", f" ({x})")  # noqa: E731
    unmatched = [n["title"] + paren(k) for n in nodes.values() if n["supply"] == "boq" for k in n["boq"] if k not in keys]
    unmatched += [n["title"] + paren(n["detail"]) for n in nodes.values() if n["supply"] == "missing"]
    unmatched += [x["cable"] + paren(x["boq"]) for x in links if x["supply"] == "boq" and x["boq"] not in keys]
    d = {"faces": rows, "hub": "blender", "columns": ["projector", "screen"], "nodes": nodes, "links": links,
         "unmatched": list(dict.fromkeys(unmatched))}
    return d | {"svg": faces_svg(d)}


def calculate(content: dict, library: dict, inputs: dict, cabinet_id: str | None, run) -> dict:
    line = content["business_line"]
    return (calculate_led if line == "LED" else calculate_pj)(content, library, inputs, cabinet_id, run)
