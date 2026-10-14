"""LED 业务线：尺寸吸附，以及步骤类规则（步骤写在代码里，只改参数）。"""
from decimal import Decimal

from ..products.library import active, name
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
        return {"check": "BLOCK", "note": "V1 只支持同宽的箱体尺寸组合"}
    w = widths.pop()
    if ctx["width_mm"] % w:
        return {"check": "BLOCK", "note": f"屏宽 {_n(ctx['width_mm'])} 不是箱体宽 {_n(w)} 的整数倍，现有箱体拼不出"}
    counts = _stack(ctx["height_mm"], [h for _, h in sizes])
    if counts is None:
        return {"check": "BLOCK", "note": f"屏高 {_n(ctx['height_mm'])} 用现有箱体高度拼不出"}
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


def controller_pick(ctx: dict, catalog: dict) -> dict:
    """F11：带载像素和网口数都要够，否则阻断。按产品库顺序取第一款够用的。"""
    load, runs = ctx["total_pixels"], ctx["data_runs"]
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
                "note": "网口全部用满，备用线没有空余网口" if runs == ports else "",
                "trace": f"{fmt(load)} ≤ {fmt(cap)}，且 {_n(runs)} 路 ≤ {_n(ports)} 口",
                "sample": c.get("sample", False),
            }
    return {"check": "BLOCK", "note": f"没有带载和网口都够的控制器：需要 {fmt(load)} px、{_n(runs)} 口",
            "sample": True}


def processor_pick(ctx: dict, catalog: dict) -> dict:
    """F13：按信号源数量和分辨率选视频处理器，取产品库里第一款够用的。"""
    load, sources = ctx["total_pixels"], ctx["signal_sources"]
    for p in catalog.get("processors", []):
        if sources <= p["inputs"] and load <= p["max_px"]:
            return {
                "outputs": {"processor": p["model"], "processor_id": p.get("id"), "processor_qty": Decimal(1)},
                "trace": f"{_n(sources)} 路信号源，{load / 1_000_000:.2f} MP ≤ {Decimal(p['max_px']) / 1_000_000:.2f} MP",
                "sample": p.get("sample", False),
            }
    return {"check": "NOTE", "note": "产品库里没有输入数和分辨率都够的视频处理器", "sample": True}


# 步骤名 → (函数, 需要的名称, 产出的名称)
STEPS = {
    "cabinet_layout": (cabinet_layout, ["width_mm", "height_mm", "cabinet_sizes_mm"],
                       ["cabinets", "layout", "cabinet_counts"]),
    "controller_pick": (controller_pick, ["total_pixels", "data_runs"],
                        ["controller", "controller_id", "controller_qty", "load_mp", "capacity_mp", "ports_used", "ports"]),
    "processor_pick": (processor_pick, ["total_pixels", "signal_sources"], ["processor", "processor_id", "processor_qty"]),
}


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
    block = None if chosen else (f"产品库里没有符合的箱体：P{_n(pitch)} · {inputs['environment']} · "
                                 f"{inputs['maintenance']}，请先在产品库添加")
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
        "processors": [{"id": p["id"], "model": name(p), "inputs": p["inputs"], "max_px": p["max_px"],
                        "sample": p.get("sample", False)}
                       for p in active(library, "processor") if p.get("inputs") and p.get("max_px")],
    }


def boq(values: dict, cabinet: dict | None, inputs: dict, library: dict) -> list[dict]:
    """BOQ 行：数量全部来自规则结果，「数量依据」写规则编号。key 用来对应单价。"""
    lines = []
    products = {p["id"]: p for p in library["products"]}

    def add(key, item, model, qty, unit, why, rule, included=False):
        if qty is not None:
            lines.append({"key": key, "item": item, "model": model, "qty": qty, "unit": unit, "why": why,
                          "rule": rule, "included": included, "manual": False})

    if cabinet:
        m = cabinet["model"]
        for i, (w, h, n) in enumerate(values.get("cabinet_counts") or []):
            add(f"{cabinet['id']}:{w}x{h}", f"LED cabinet 箱体 {w} × {h}", m, n, "个", ("主尺寸，" if i == 0 else "") + "F3", "F3")
        add(f"{cabinet['id']}:module", f"Spare modules 备用模组 {cabinet['module_w_mm']} × {cabinet['module_h_mm']}",
            m, values.get("spare_modules"), "块", "F10", "F10")
        if values.get("cabinets") is not None:
            psu, rx = cabinet.get("psu_per_cabinet") or 1, cabinet.get("rx_per_cabinet") or 1
            add("", "Power supply 电源", "箱内", values["cabinets"] * psu, "个", f"每箱 {psu} 个", "F3", included=True)
            add("", "Receiving card 接收卡", "箱内", values["cabinets"] * rx, "张", f"每箱 {rx} 张", "F3", included=True)
        add(f"{cabinet['id']}:psu", "Spare PSU 备用电源", m, values.get("spare_psu"), "个", "F8", "F8")
        add(f"{cabinet['id']}:rx", "Spare receiving card 备用接收卡", m, values.get("spare_rx_cards"), "张", "F8", "F8")
    if values.get("controller_id") in products:
        add(values["controller_id"], "Controller 控制器", products[values["controller_id"]]["model"],
            values["controller_qty"], "台", f"{values['load_mp']:.2f} / {values['capacity_mp']:.2f} MP，F11", "F11")
    if values.get("processor_id") in products:
        add(values["processor_id"], "Video processor 视频处理器", products[values["processor_id"]]["model"],
            values["processor_qty"], "台", f"{inputs.get('signal_sources')} 路信号源，F13", "F13")
    if values.get("circuits") is not None:
        add("power_cable", "Power cable 电源线", "—", values.get("power_cables"), "路", f"{values['circuits']} 回路 + 备用，F7", "F7")
        add("db_box", "DB box with MCB 配电箱（含 MCB）", "定制", values.get("db_boxes"), "个", f"{values['circuits']} 回路，F12", "F12")
    if values.get("data_runs") is not None:
        add("data_cable", "Data cable 数据线", "Cat6", values.get("data_cables"), "路", f"{values['data_runs']} 路 + 备用，F9", "F9")
    if values.get("installation_items"):
        add(f"install:{inputs.get('installation')}", values["installation_items"], "—", 1, "套", "F16", "F16")
    return lines
