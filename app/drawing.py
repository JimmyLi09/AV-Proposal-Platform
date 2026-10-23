"""LED 拼接与线路图（CR-3）：由 F3 箱体排布、F5 / F6 电源回路、F9 网线自动生成。只做平面单屏。

- 箱体：按 F3 的排布，主尺寸的行放在下面；编号从左下角 R1C1 开始。
- 电源回路：每箱功率 = 箱体面积 × F5 的每平方米功率；整列整列地分组，每个回路不超过 F6 的每回路功率，
  一列就超过时再按箱体拆开。
- 网线：从左下角起按列蛇形走（第 1 列向上、第 2 列向下……），每根不超过 F9 的每根带载像素，满了换下一根。
- 可以手动把箱体换到别的回路 / 网线（随 Rev 保存）；改完立即重新校验，超载的标红、不能批准。
图上不另算数量：箱体、功率、带载都来自规则结果和规则参数。
"""
from decimal import ROUND_HALF_UP, Decimal

from .i18n import tr

VOLTAGE = 230  # 单相 230 V，只用来在图上标回路电流
LETTERS = "ABCDEF"


def _d(v) -> Decimal:
    return Decimal(str(v))


def _auto_cables(cabs: list[dict], order: list[str], cap: Decimal) -> dict[str, int]:
    by_id, out, no, load = {c["id"]: c for c in cabs}, {}, 1, Decimal(0)
    for cid in order:
        px = by_id[cid]["_px"]
        if load and load + px > cap:
            no, load = no + 1, Decimal(0)
        out[cid], load = no, load + px
    return out


def _auto_circuits(columns: list[list[dict]], order: list[str], cap: Decimal) -> dict[str, int]:
    """整列整列地放进同一个回路；一列就超过上限时，这一列按蛇形顺序拆到几个回路。"""
    out, no, load = {}, 1, Decimal(0)
    pos = {cid: i for i, cid in enumerate(order)}
    for col in columns:
        watts = sum(c["_w"] for c in col)
        if watts <= cap:
            if load and load + watts > cap:
                no, load = no + 1, Decimal(0)
            for c in col:
                out[c["id"]] = no
            load += watts
            continue
        for c in sorted(col, key=lambda c: pos[c["id"]]):
            if load and load + c["_w"] > cap:
                no, load = no + 1, Decimal(0)
            out[c["id"]], load = no, load + c["_w"]
    return out


def build(values: dict, inputs: dict, params: dict, edits: dict | None = None, manual: set = frozenset()) -> dict | None:
    """values：规则结果（含 F3 的 cabinet_counts，手动覆盖过的用手动值）；params：规则参数 {名字: 值}；
    edits：{power: {箱体: 回路}, data: {箱体: 网线}}；manual：手动覆盖过的结果名（CR-5）。"""
    counts = values.get("cabinet_counts")
    if not counts or values.get("power_kw") is None or values.get("data_runs") is None or not values.get("area_m2"):
        return None
    pitch = _d(inputs["pixel_pitch_mm"])
    col_w = int(counts[0][0])
    cols = int(_d(inputs["width_mm"]) / col_w)
    rows = [int(h) for _, h, n in counts for _ in range(int(n) // cols)]  # 从下往上
    letter = {int(h): LETTERS[i] for i, (_, h, _n) in enumerate(counts)}
    w_per_m2 = _d(values["power_kw"]) * 1000 / _d(values["area_m2"])
    cap_w, cap_px = _d(params["circuit_kw"]) * 1000, _d(params["px_per_data_cable"])

    cabs, columns, y = [], [[] for _ in range(cols)], 0
    for r, h in enumerate(rows):
        for c in range(cols):
            cab = {"id": f"R{r + 1}C{c + 1}", "row": r + 1, "col": c + 1, "x": c * col_w, "y": y, "w": col_w, "h": h,
                   "size": letter[h], "_px": (col_w / pitch) * (h / pitch), "_w": _d(col_w * h) / 1_000_000 * w_per_m2}
            cabs.append(cab)
            columns[c].append(cab)
        y += h
    order = [cab["id"] for c, col in enumerate(columns) for cab in (col if c % 2 == 0 else col[::-1])]

    auto_cable, auto_circuit = _auto_cables(cabs, order, cap_px), _auto_circuits(columns, order, cap_w)
    n_cables, n_circuits = max(auto_cable.values()), max(auto_circuit.values())
    edits = edits or {}
    power = {k: v for k, v in (edits.get("power") or {}).items() if k in auto_circuit and 1 <= v <= n_circuits}
    data = {k: v for k, v in (edits.get("data") or {}).items() if k in auto_cable and 1 <= v <= n_cables}
    for cab in cabs:
        cab["circuit"], cab["cable"] = power.get(cab["id"], auto_circuit[cab["id"]]), data.get(cab["id"], auto_cable[cab["id"]])
        cab["manual"] = cab["id"] in power or cab["id"] in data
        cab["px"], cab["watts"] = int(cab["_px"]), float(cab["_w"].quantize(Decimal("0.1"), ROUND_HALF_UP))

    circuits = []
    for no in range(1, n_circuits + 1):
        members = [c for c in cabs if c["circuit"] == no]
        watts = sum((c["_w"] for c in members), Decimal(0))
        circuits.append({"no": no, "cabinets": len(members), "watts": round(float(watts)),
                         "amps": float((watts / VOLTAGE).quantize(Decimal("0.1"), ROUND_HALF_UP)), "over": watts > cap_w})
    cables = []
    for no in range(1, n_cables + 1):
        path = [cid for cid in order if next(c for c in cabs if c["id"] == cid)["cable"] == no]
        px = sum((c["_px"] for c in cabs if c["cable"] == no), Decimal(0))
        cables.append({"no": no, "cabinets": len(path), "px": int(px), "over": px > cap_px, "path": path})
    for cab in cabs:
        del cab["_px"], cab["_w"]

    checks = []
    for x in circuits:
        if x["over"]:
            checks.append({"check": "BLOCK", "text": tr(f"回路 {x['no']} 超载：{x['watts']} W > {int(cap_w)} W",
                                                     f"Circuit {x['no']} overloaded: {x['watts']} W > {int(cap_w)} W")})
    for x in cables:
        if x["over"]:
            checks.append({"check": "BLOCK", "text": tr(f"网线 {x['no']} 超载：{x['px']:,} px > {int(cap_px):,} px",
                                                     f"Data cable {x['no']} overloaded: {x['px']:,} px > {int(cap_px):,} px")})
    if n_circuits != values.get("circuits"):
        checks.append({"check": "NOTE", "text": tr(
            f"图上整列分组是 {n_circuits} 路，F6 手动值是 {values.get('circuits')} 路",
            f"Grouping whole columns gives {n_circuits} circuits; the manual F6 value is {values.get('circuits')}")
            if "circuits" in manual else tr(
            f"图上整列分组是 {n_circuits} 路，F6 按总功率算是 {values.get('circuits')} 路",
            f"Grouping whole columns gives {n_circuits} circuits; F6 on total power gives {values.get('circuits')}")})
    if "cabinets" in manual and len(cabs) != values.get("cabinets"):
        checks.append({"check": "NOTE", "text": tr(
            f"图上按 F3 排布是 {len(cabs)} 个箱体，F3 手动值是 {values.get('cabinets')} 个",
            f"The F3 layout has {len(cabs)} cabinets; the manual F3 value is {values.get('cabinets')}")})
    if n_cables != values.get("data_runs"):
        checks.append({"check": "NOTE", "text": tr(
            f"图上蛇形分组是 {n_cables} 根，F9 按总像素算是 {values.get('data_runs')} 根",
            f"Snake grouping gives {n_cables} cables; F9 on total pixels gives {values.get('data_runs')}")})
    return {
        "width": int(_d(inputs["width_mm"])), "height": sum(rows), "cols": cols, "col_w": col_w, "rows": rows,
        "sizes": {letter[int(h)]: {"w": int(w), "h": int(h), "count": int(n)} for w, h, n in counts},
        "cabinets": cabs, "circuits": circuits, "cables": cables,
        "circuit_cap_w": int(cap_w), "cable_cap_px": int(cap_px), "voltage": VOLTAGE,
        "spare_circuits": int(values.get("power_cables", n_circuits) - values.get("circuits", n_circuits)),
        "spare_cables": int(values.get("data_cables", n_cables) - values.get("data_runs", n_cables)),
        "manual": {"power": len(power), "data": len(data)}, "edits": {"power": power, "data": data},
        "checks": checks, "blocked": any(x["check"] == "BLOCK" for x in checks),
    }
