"""LED 业务线：尺寸吸附，以及步骤类规则（步骤写在代码里，只改参数）。"""
import math
from decimal import Decimal

from ..i18n import text, tr
from ..products.library import active, load_reference, name
from .expr import fmt


def _n(x: Decimal) -> str:
    return str(int(x)) if x == x.to_integral_value() else str(x.normalize())


def size_choices(ctx: dict) -> dict:
    """尺寸不是模组整数倍时，给出两个最近的有效尺寸让人选，不报错。"""
    choices = {}
    for dim, module in (("width_mm", "module_w_mm"), ("height_mm", "module_h_mm")):
        if dim in ctx and module in ctx and ctx[dim] % ctx[module]:
            low = ctx[dim] // ctx[module] * ctx[module]
            choices[dim] = [low, low + ctx[module]]
    return choices


def _stack(height: Decimal, heights: list) -> list | None:
    """每列从上到下怎么叠：尽量多用排在前面的尺寸（主尺寸优先），拼不出返回 None。"""
    if not heights:
        return [] if height == 0 else None
    h, rest = heights[0], heights[1:]
    for count in range(int(height // h), -1, -1):
        tail = _stack(height - count * h, rest)
        if tail is not None:
            return [count, *tail]
    return None


def cabinet_layout(ctx: dict, catalog: dict) -> dict:
    """F3：屏宽按箱体宽分列，每列按高度组合箱体，主尺寸（列表第一个）优先。"""
    sizes = ctx["cabinet_sizes_mm"]
    widths = {w for w, _ in sizes}
    if len(widths) != 1:
        return {"check": "BLOCK", "note": tr("V1 只支持同宽的箱体尺寸组合", "V1 supports only cabinet sizes of the same width")}
    w = widths.pop()
    if ctx["width_mm"] % w:
        return {"check": "BLOCK", "note": tr(f"屏宽 {_n(ctx['width_mm'])} 不是箱体宽 {_n(w)} 的整数倍，现有箱体拼不出",
                                             f"Width {_n(ctx['width_mm'])} is not a multiple of cabinet width {_n(w)}; "
                                             "the cabinets cannot fill it")}
    counts = _stack(ctx["height_mm"], [h for _, h in sizes])
    if counts is None:
        return {"check": "BLOCK", "note": tr(f"屏高 {_n(ctx['height_mm'])} 用现有箱体高度拼不出",
                                             f"Height {_n(ctx['height_mm'])} cannot be made from the cabinet heights")}
    cols = ctx["width_mm"] / w
    used = [(c, h) for c, (_, h) in zip(counts, sizes) if c]
    total = cols * sum(counts)
    return {
        "outputs": {
            "cabinets": total,
            "layout": " + ".join(f"{_n(cols * c)} x {_n(w)}x{_n(h)}" for c, h in used),
            "cabinet_counts": [[w, h, cols * c] for c, h in used],
        },
        "trace": f"cols {_n(cols)} × {_n(w)} · rows " + " + ".join(f"{c} × {_n(h)}" for c, h in used)
                 + " → " + " + ".join(_n(cols * c) for c, _ in used),
    }


def _sources(ctx: dict) -> Decimal:
    return ctx.get("signal_sources") or Decimal(1)  # CR-2：没填按 1 路算


def integrated_pick(ctx: dict, catalog: dict) -> dict | None:
    """处理器（含发送）：带载像素、网口、输入路数都够的第一台（首选在前）。输入路数没填的按待核对处理，不挡。"""
    load, runs, sources = ctx["total_pixels"], ctx["data_runs"], _sources(ctx)
    for p in catalog.get("processors", []):
        if (p.get("sending") and load <= p["capacity_px"] and runs <= p["ports"]
                and (p.get("inputs") is None or sources <= p["inputs"])):
            return p
    return None


def _load(load: Decimal, cap) -> str:
    pct = f"{load / Decimal(cap) * 100:.0f} %"
    return f"{load / 1_000_000:.2f} / {Decimal(cap) / 1_000_000:.2f} MP" + tr(f"（{pct}）", f" ({pct})")


def controller_pick(ctx: dict, catalog: dict) -> dict:
    """F11：带载像素和网口数都要够，否则阻断。按产品库顺序取第一款够用的。
    产品库里有够用的处理器（含发送）时，不再单独配控制器（CR-2）。"""
    load, runs = ctx["total_pixels"], ctx["data_runs"]
    if p := integrated_pick(ctx, catalog):
        cap, ports = Decimal(p["capacity_px"]), Decimal(p["ports"])
        return {
            "outputs": {
                "controller": tr(f"已包含在处理器 {p['model']} 里", f"Included in processor {p['model']}"),
                "controller_id": "", "controller_qty": Decimal(0),
                "load_mp": load / 1_000_000, "capacity_mp": cap / 1_000_000, "ports_used": runs, "ports": ports,
            },
            "check": "PASS",
            "note": tr(f"处理器 {p['model']} 含发送，不单独配控制器",
                       f"Processor {p['model']} has sending built in; no separate controller"),
            "trace": tr(f"含发送：{_load(load, cap)}，{_n(runs)} 路 ≤ {_n(ports)} 口",
                        f"With sending: {_load(load, cap)}, {_n(runs)} runs ≤ {_n(ports)} ports"),
            "sample": p.get("sample", False),
        }
    for c in catalog.get("controllers", []):
        cap, ports = Decimal(c["capacity_px"]), Decimal(c["ports"])
        if load <= cap and runs <= ports:
            return {
                "outputs": {
                    "controller": c["model"], "controller_id": c.get("id"), "controller_qty": Decimal(1),
                    "load_mp": load / 1_000_000, "capacity_mp": cap / 1_000_000,
                    "ports_used": runs, "ports": ports,
                },
                "check": "PASS",
                "note": tr("网口全部用满，备用线没有空余网口", "All ports are used; no free port for the spare cable")
                        if runs == ports else "",
                "trace": tr(f"{fmt(load)} ≤ {fmt(cap)}，且 {_n(runs)} 路 ≤ {_n(ports)} 口",
                            f"{fmt(load)} ≤ {fmt(cap)}, and {_n(runs)} runs ≤ {_n(ports)} ports"),
                "sample": c.get("sample", False),
            }
    return {"check": "BLOCK", "note": tr(f"没有带载和网口都够的控制器：需要 {fmt(load)} px、{_n(runs)} 口",
                                         f"No controller with enough load and ports: needs {fmt(load)} px, {_n(runs)} ports"),
            "sample": True}


def processor_pick(ctx: dict, catalog: dict) -> dict:
    """F13：先找一台够用的处理器（含发送）；找不到再按信号源数量和分辨率选独立处理器（另配 F11 的控制器）。"""
    load, runs, sources = ctx["total_pixels"], ctx["data_runs"], _sources(ctx)
    notes = [] if "signal_sources" in ctx else [tr("信号源数量没填，按 1 路计算", "Signal sources not filled in; 1 assumed")]
    if p := integrated_pick(ctx, catalog):
        cap = Decimal(p["capacity_px"])
        if load / cap > Decimal("0.9"):
            notes.append(tr("负载超过 90 %，余量偏小", "Load above 90 %; little headroom"))
        if p.get("inputs") is None:
            notes.append(tr("输入路数待核对规格书", "Input count to be checked against the datasheet"))
        return {
            "outputs": {"processor": p["model"], "processor_id": p.get("id"), "processor_qty": Decimal(1),
                        "processor_sending": True},
            "check": "NOTE" if notes else None, "note": tr("；", "; ").join(notes),
            "trace": tr(f"含发送：{_load(load, cap)}，{_n(runs)} 路 ≤ {_n(Decimal(p['ports']))} 口，{_n(sources)} 路信号源",
                        f"With sending: {_load(load, cap)}, {_n(runs)} runs ≤ {_n(Decimal(p['ports']))} ports, "
                        f"{_n(sources)} signal sources"),
            "sample": p.get("sample", False),
        }
    for p in catalog.get("processors", []):
        if not p.get("sending") and p.get("inputs") and p.get("max_px") and sources <= p["inputs"] and load <= p["max_px"]:
            return {
                "outputs": {"processor": p["model"], "processor_id": p.get("id"), "processor_qty": Decimal(1),
                            "processor_sending": False},
                "check": "NOTE" if notes else None, "note": tr("；", "; ").join(notes),
                "trace": tr(f"{_n(sources)} 路信号源，{load / 1_000_000:.2f} MP ≤ {Decimal(p['max_px']) / 1_000_000:.2f} MP",
                            f"{_n(sources)} signal sources, {load / 1_000_000:.2f} MP ≤ {Decimal(p['max_px']) / 1_000_000:.2f} MP"),
                "sample": p.get("sample", False),
            }
    notes.append(tr("产品库里没有输入数和分辨率都够的视频处理器", "No video processor in the library with enough inputs and resolution"))
    return {"check": "NOTE", "note": tr("；", "; ").join(notes), "sample": True}


# 步骤名 → (函数, 需要的名称, 产出的名称)
STEPS = {
    "cabinet_layout": (cabinet_layout, ["width_mm", "height_mm", "cabinet_sizes_mm"],
                       ["cabinets", "layout", "cabinet_counts"]),
    "controller_pick": (controller_pick, ["total_pixels", "data_runs"],
                        ["controller", "controller_id", "controller_qty", "load_mp", "capacity_mp", "ports_used", "ports"]),
    "processor_pick": (processor_pick, ["total_pixels", "data_runs"],
                       ["processor", "processor_id", "processor_qty", "processor_sending"]),
}


# 推荐页上可以手动覆盖的结果（CR-5）：规则编号 → 结果名
OVERRIDABLE = {"F4": ["res_x", "res_y"], "F2": ["modules"], "F3": ["cabinets"], "F10": ["spare_modules"],
               "F5": ["power_kw"], "F6": ["circuits"], "F7": ["power_cables"], "F9": ["data_cables"],
               "F11": ["controller_qty"], "F12": ["db_boxes"]}


# ---- 推荐与 BOQ ----

PRODUCT_INPUTS = ["module_w_mm", "module_h_mm", "cabinet_sizes_mm"]  # 由选定的箱体带出，不用手填


def recommend(inputs: dict, library: dict, cabinet_id: str | None = None) -> dict:
    """箱体只从产品库里选：点间距、使用环境、维护方式都对得上，首选在前。可以换成其它符合的型号。"""
    missing = [k for k in ("pixel_pitch_mm", "environment", "maintenance") if inputs.get(k) in (None, "")]
    if missing:
        return {"cabinet": None, "candidates": [], "block": None, "missing": missing}
    pitch = Decimal(str(inputs["pixel_pitch_mm"]))
    candidates = [p for p in active(library, "cabinet")
                  if p.get("pixel_pitch_mm") and Decimal(str(p["pixel_pitch_mm"])) == pitch
                  and inputs["environment"] in p["scenes"] and p["maintenance"] in (inputs["maintenance"], "both")]
    chosen = next((p for p in candidates if p["id"] == cabinet_id), candidates[0] if candidates else None)
    where = f"P{_n(pitch)} · {inputs['environment']} · {inputs['maintenance']}"
    block = None if chosen else tr(f"产品库里没有符合的箱体：{where}，请先在产品库添加",
                                   f"No matching cabinet in the library: {where}. Add one in the Product Library first")
    return {"cabinet": chosen, "candidates": candidates, "block": block, "missing": []}


def product_inputs(cabinet: dict | None) -> dict:
    return {k: cabinet[k] for k in PRODUCT_INPUTS if cabinet and cabinet.get(k) is not None}


def catalog(library: dict, cabinet: dict | None) -> dict:
    """规则引擎用到的产品：选定的箱体，以及按首选顺序排好的控制器、视频处理器。"""
    return {
        "cabinet": {"model": name(cabinet), "brightness_nits": cabinet.get("brightness_nits"),
                    "sample": cabinet.get("sample", False)} if cabinet else {},
        "controllers": [{"id": c["id"], "model": name(c), "capacity_px": c["capacity_px"], "ports": c["ports"],
                         "sample": c.get("sample", False)}
                        for c in active(library, "controller") if c.get("capacity_px") and c.get("ports")],
        "processors": [{"id": p["id"], "model": name(p), "inputs": p.get("inputs"), "max_px": p.get("max_px"),
                        "sending": bool(p.get("sending")), "capacity_px": p.get("capacity_px"), "ports": p.get("ports"),
                        "sample": p.get("sample", False)}
                       for p in active(library, "processor")
                       if (p.get("sending") and p.get("capacity_px") and p.get("ports")) or (p.get("inputs") and p.get("max_px"))],
    }


def boq(values: dict, cabinet: dict | None, inputs: dict, library: dict, manual: set = frozenset()) -> list[dict]:
    """内部明细：数量全部来自规则结果，「数量依据」写规则编号。key 用来对应示意图里的设备。
    manual：手动覆盖过的结果名，数量就是这个结果的行标「手动」。"""
    lines = []
    products = {p["id"]: p for p in library["products"]}

    def add(key, item, model, qty, unit, why, rule, included=False, name=None):
        if qty is not None:
            lines.append({"key": key, "item": item, "model": model, "qty": qty, "unit": unit, "why": why,
                          "rule": rule, "included": included, "manual": name in manual})

    if cabinet:
        m = cabinet["model"]
        for i, (w, h, n) in enumerate(values.get("cabinet_counts") or []):
            add(f"{cabinet['id']}:{w}x{h}", tr("箱体", "LED cabinet") + f" {w} × {h}", m, n, tr("个", "pcs"),
                (tr("主尺寸，", "main size, ") if i == 0 else "") + "F3", "F3")
        add(f"{cabinet['id']}:module", tr("备用模组", "Spare modules") + f" {cabinet['module_w_mm']} × {cabinet['module_h_mm']}",
            m, values.get("spare_modules"), tr("块", "pcs"), "F10", "F10", name="spare_modules")
        if values.get("cabinets") is not None:
            psu, rx = cabinet.get("psu_per_cabinet") or 1, cabinet.get("rx_per_cabinet") or 1
            inside = tr("箱内", "In cabinet")
            add("", tr("电源", "Power supply"), inside, values["cabinets"] * psu, tr("个", "pcs"),
                tr(f"每箱 {psu} 个", f"{psu} per cabinet"), "F3", included=True)
            add("", tr("接收卡", "Receiving card"), inside, values["cabinets"] * rx, tr("张", "pcs"),
                tr(f"每箱 {rx} 张", f"{rx} per cabinet"), "F3", included=True)
        add(f"{cabinet['id']}:psu", tr("备用电源", "Spare PSU"), m, values.get("spare_psu"), tr("个", "pcs"), "F8", "F8")
        add(f"{cabinet['id']}:rx", tr("备用接收卡", "Spare receiving card"), m, values.get("spare_rx_cards"), tr("张", "pcs"),
            "F8", "F8")
    if values.get("controller_id") in products:
        add(values["controller_id"], tr("控制器", "Controller"), products[values["controller_id"]]["model"],
            values["controller_qty"], tr("台", "units"),
            f"{values['load_mp']:.2f} / {values['capacity_mp']:.2f} MP" + tr("，", ", ") + "F11", "F11", name="controller_qty")
    if values.get("processor_id") in products:
        sources = inputs.get("signal_sources") or 1
        add(values["processor_id"], tr("视频处理器（含发送）", "Video processor with sending") if values.get("processor_sending")
            else tr("视频处理器", "Video processor"), products[values["processor_id"]]["model"],
            values["processor_qty"], tr("台", "units"), tr(f"{sources} 路信号源，F13", f"{sources} signal sources, F13"), "F13")
    if values.get("circuits") is not None:
        c = values["circuits"]
        add("power_cable", tr("电源线", "Power cable"), "—", values.get("power_cables"), tr("路", "runs"),
            tr(f"{c} 回路 + 备用，F7", f"{c} circuits + spare, F7"), "F7", name="power_cables")
        add("db_box", tr("配电箱（含 MCB）", "DB box with MCB"), tr("定制", "Custom"), values.get("db_boxes"), tr("个", "pcs"),
            tr(f"{c} 回路，F12", f"{c} circuits, F12"), "F12", name="db_boxes")
    if values.get("data_runs") is not None:
        r = values["data_runs"]
        add("data_cable", tr("数据线", "Data cable"), "Cat6", values.get("data_cables"), tr("路", "runs"),
            tr(f"{r} 路 + 备用，F9", f"{r} runs + spare, F9"), "F9", name="data_cables")
    if values.get("installation_items"):
        add(f"install:{inputs.get('installation')}", text(values["installation_items"]), "—", 1, tr("套", "set"), "F16", "F16")
    return lines


# 客户版 BOQ 模板里能用的 {名字}：输入、规则结果，加上下面这些由它们换个写法得到的值（不另算数量）
ENVIRONMENT_LABEL = {"indoor": "Indoor", "outdoor": "Outdoor", "rental": "Rental"}
INSTALLATION_LABEL = {"wall": "on wall", "floor": "on floor stand", "hanging": "hanging", "embedded": "embedded"}
BOQ_EXTRA = ["environment_label", "installation_label", "cabinet_model", "cabinet_sizes", "brightness_nits",
             "aspect_ratio", "load_pct", "power_spares", "data_spares", "processor_title"]


def boq_context(values: dict, cabinet: dict | None, inputs: dict) -> dict:
    ctx = {**inputs, **product_inputs(cabinet), **values}
    ctx["signal_sources"] = inputs.get("signal_sources") or 1  # 没填按 1 路算（和 F13 一致）
    ctx["processor_title"] = "Video processor with sending" if values.get("processor_sending") else "Video processor"
    ctx["environment_label"] = ENVIRONMENT_LABEL.get(inputs.get("environment"))
    ctx["installation_label"] = INSTALLATION_LABEL.get(inputs.get("installation"))
    if cabinet:
        ctx["cabinet_model"] = cabinet["model"]
        ctx["brightness_nits"] = cabinet.get("brightness_nits")
        ctx["cabinet_sizes"] = " / ".join(f"{w} × {h}" for w, h, _ in values.get("cabinet_counts") or [])
    if values.get("res_x") and values.get("res_y"):
        g = math.gcd(int(values["res_x"]), int(values["res_y"]))
        ctx["aspect_ratio"] = f"{int(values['res_x']) // g}:{int(values['res_y']) // g}"
    if values.get("capacity_mp"):
        ctx["load_pct"] = round(values["load_mp"] / values["capacity_mp"] * 100)
    if values.get("power_cables") is not None and values.get("circuits") is not None:
        ctx["power_spares"] = values["power_cables"] - values["circuits"]
    if values.get("data_cables") is not None and values.get("data_runs") is not None:
        ctx["data_spares"] = values["data_cables"] - values["data_runs"]
    return ctx


SUGGEST_LABEL = {"recommended": lambda: tr("推荐", "Recommended"), "headroom": lambda: tr("余量大", "More headroom"),
                 "no": lambda: tr("不推荐", "Not recommended")}


def suggest(values: dict, inputs: dict, library: dict) -> list[dict]:
    """CR-2：产品库里没有够用的处理器 / 控制器时，从参考型号表给出建议型号（未入库，数值待核对规格书）。
    第一款够用的标「推荐」，再大的标「余量大」，不够的写明哪里不够；由人选，点一下加进产品库。"""
    load, runs = values.get("total_pixels"), values.get("data_runs")
    if load is None or runs is None or (values.get("controller_qty") is not None and values.get("processor_id")):
        return []
    in_library, sources = {p["id"] for p in library["products"]}, inputs.get("signal_sources") or 1
    out, found = [], False
    for p in sorted(load_reference(library["business_line"]), key=lambda p: p["capacity_px"]):
        if p["id"] in in_library:
            continue
        why = [w for ok, w in ((load <= p["capacity_px"], tr("带载不够", "not enough load")),
                               (runs <= p["ports"], tr("网口不够", "not enough ports")),
                               (p.get("inputs") is None or sources <= p["inputs"], tr("输入路数不够", "not enough inputs")))
               if not ok]
        pct = round(load / p["capacity_px"] * 100)
        status = "no" if why else "headroom" if found else "recommended"
        found = found or not why
        out.append({"id": p["id"], "model": name(p), "capacity_px": p["capacity_px"], "ports": p["ports"],
                    "ports_used": runs, "load_pct": pct, "status": status, "label": SUGGEST_LABEL[status](),
                    "reason": tr("、", ", ").join(why), "note": tr("余量偏小", "little headroom") if not why and pct > 90 else "",
                    "remark": text(p.get("remark", ""))})
    return out


def diagram(values: dict, boq_lines: list[dict], inputs: dict, cabinet: dict | None, library: dict,
            suggestions: list[dict] | None = None, manual: set = frozenset()) -> dict | None:
    """Level 1 / Level 2 示意图由 BOQ 生成：每台设备、每条线缆都对应 BOQ 行。
    业主提供（supply=owner）或随设备附带（supply=included）的不进 BOQ，会在图上标出来（示例假设，清单 H4）。"""
    if not cabinet or values.get("cabinets") is None:
        return None
    products = {p["id"]: p for p in library["products"]}
    nodes = {"source": {"title": tr("信号源", "Content source"), "model": tr("播放器或电脑", "Player or PC"),
                        "qty": inputs.get("signal_sources") or 1,
                        "detail": "", "boq": [], "supply": "owner"}}
    # 处理器 / 控制器选不出来（F13 / F11）时保留位置并标出，不能悄悄从图上消失；有建议型号就写在框里
    missing = {"model": "—", "qty": "", "boq": [], "supply": "missing"}
    fits = [x["model"] for x in suggestions or [] if x["status"] != "no"]
    hint = (tr(f"建议型号：{' / '.join(fits)}（含发送，未入库）", f"Suggested: {' / '.join(fits)} (with sending, not in library)")
            if fits else "")
    sending = bool(values.get("processor_sending"))
    if values.get("processor_id") in products:
        pct = values["load_mp"] / values["capacity_mp"] * 100 if sending else 0
        nodes["processor"] = {
            "title": tr("处理器（含发送）", "Processor with sending") if sending else tr("视频处理器", "Video processor"),
            "model": products[values["processor_id"]]["model"], "qty": values["processor_qty"],
            "detail": tr(f"{values['ports_used']} / {values['ports']} 口 · 负载 {pct:.0f} %",
                         f"{values['ports_used']} / {values['ports']} ports · load {pct:.0f} %")
            if sending else "", "boq": [values["processor_id"]], "supply": "boq"}
    else:
        nodes["processor"] = missing | {"title": tr("视频处理器", "Video processor"), "detail": hint or tr(
            "F13 未选出（缺输入或产品库没有合适的）", "F13 not selected (missing inputs or nothing suitable in the library)")}
    # 用处理器（含发送）时不画控制器；处理器、控制器都没有而有建议的一体机时，也只画三个框
    if not sending and not (nodes["processor"]["supply"] == "missing" and hint):
        nodes["controller"] = {"title": tr("控制器", "Controller"), "model": products[values["controller_id"]]["model"],
                               "qty": values["controller_qty"],
                               "detail": tr(f"{values['ports']} 口", f"{values['ports']} ports") + f" · {values['capacity_mp']:.1f} MP",
                               "boq": [values["controller_id"]], "supply": "boq"
                               } if values.get("controller_id") in products else missing | {
            "title": tr("控制器", "Controller"),
            "detail": hint or tr("F11 阻断：产品库里没有合适的", "F11 blocked: nothing suitable in the library")}
    w, h = inputs.get("width_mm"), inputs.get("height_mm")
    nodes["screen"] = {"title": tr("LED 屏", "LED wall"), "model": cabinet["model"],
                       "qty": tr(f"{values['cabinets']} 个箱体", f"{values['cabinets']} cabinets"),
                       "detail": f"{w} × {h} · P{inputs.get('pixel_pitch_mm')}",
                       "boq": [f"{cabinet['id']}:{cw}x{ch}" for cw, ch, _ in values.get("cabinet_counts") or []],
                       "supply": "boq"}
    if values.get("db_boxes") is not None:
        nodes["db_box"] = {"title": tr("配电箱", "DB box"), "model": tr("定制", "Custom"), "qty": values["db_boxes"],
                           "detail": tr("每回路一个 MCB", "One MCB per circuit") + f" · {values.get('power_kw', 0):.2f} kW",
                           "boq": ["db_box"], "supply": "boq"}
    chain = [n for n in ("source", "processor", "controller", "screen") if n in nodes]
    links = []
    for a, b in zip(chain, chain[1:]):
        if b == "screen":
            if values.get("data_runs") is not None:
                links.append({"from": a, "to": b, "cable": "Cat6", "qty": f"{values['data_runs']} + {values['data_cables'] - values['data_runs']} " + tr("备用", "spare"),
                              "boq": "data_cable", "supply": "boq"})
        elif a == "source":
            links.append({"from": a, "to": b, "cable": "HDMI", "qty": str(nodes["source"]["qty"]), "boq": None, "supply": "owner"})
        else:
            links.append({"from": a, "to": b, "cable": "HDMI", "qty": "1", "boq": None, "supply": "included"})
    if "db_box" in nodes and values.get("power_cables") is not None:
        links.append({"from": "db_box", "to": "screen", "cable": tr("电源线", "Power cable"),
                      "qty": f"{values['circuits']} + {values['power_cables'] - values['circuits']} " + tr("备用", "spare"),
                      "boq": "power_cable", "supply": "boq"})
    for key, names in (("controller", {"controller_qty"}), ("screen", {"cabinets"}), ("db_box", {"db_boxes"})):
        if key in nodes:
            nodes[key]["manual"] = bool(names & manual)  # 数量是手动值（CR-5）
    for x in links:
        x["manual"] = bool({"data_cable": {"data_cables"}, "power_cable": {"circuits", "power_cables"}}.get(x["boq"], set()) & manual)
    keys = {line["key"] for line in boq_lines if line["key"]}
    paren = lambda x: tr(f"（{x}）", f" ({x})")  # noqa: E731
    unmatched = [n["title"] + paren(k) for n in nodes.values() if n["supply"] == "boq" for k in n["boq"] if k not in keys]
    unmatched += [n["title"] + paren(n["detail"]) for n in nodes.values() if n["supply"] == "missing"]
    unmatched += [x["cable"] + paren(x["boq"]) for x in links if x["supply"] == "boq" and x["boq"] not in keys]
    return {"chain": chain, "power": "db_box" if "db_box" in nodes else None, "nodes": nodes, "links": links,
            "unmatched": unmatched}
