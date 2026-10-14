"""LED 业务线：尺寸吸附，以及步骤类规则（步骤写在代码里，只改参数）。"""
from decimal import Decimal

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
                    "controller": c["model"], "controller_qty": Decimal(1),
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
                "outputs": {"processor": p["model"], "processor_qty": Decimal(1)},
                "trace": f"{_n(sources)} 路信号源，{load / 1_000_000:.2f} MP ≤ {Decimal(p['max_px']) / 1_000_000:.2f} MP",
                "sample": p.get("sample", False),
            }
    return {"check": "NOTE", "note": "产品库里没有输入数和分辨率都够的视频处理器", "sample": True}


# 步骤名 → (函数, 需要的名称, 产出的名称)
STEPS = {
    "cabinet_layout": (cabinet_layout, ["width_mm", "height_mm", "cabinet_sizes_mm"], ["cabinets", "layout"]),
    "controller_pick": (controller_pick, ["total_pixels", "data_runs"],
                        ["controller", "controller_qty", "load_mp", "capacity_mp", "ports_used", "ports"]),
    "processor_pick": (processor_pick, ["total_pixels", "signal_sources"], ["processor", "processor_qty"]),
}
