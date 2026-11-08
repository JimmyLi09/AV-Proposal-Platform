"""LED 拼接与线路图（CR-3，CR-10 起改用 W1）：电源回路和网线的分组都来自 W1 接线布置，图纸、DXF 和 BOQ 用同一份结果。只做平面单屏。

- 箱体：按 F3 的排布，主尺寸的行放在下面；编号从左下角 R1C1 开始。
- 电源回路：W1 从最下一行靠配电箱一侧开始，按 F6 回路数连续平均分组；每个回路检查电流（Σ 单箱最大电流 ≤ 可用电流）和串接箱数。
- 网线：W1 从最上一行靠发送卡一侧开始，按行整行或按箱数装；每根检查像素 ≤ 每网口带载。
- 可以手动把箱体换到别的回路 / 网线（随 Rev 保存）；改完立即重新校验，超载的标红、不能批准。
图上不另算数量：箱体、电流、带载都来自规则结果、规则参数和产品库。
"""
from decimal import ROUND_HALF_UP, Decimal

from .i18n import tr
from .rules import wiring

VOLTAGE = 230  # 产品库没有单箱电流时，用功率 ÷ 230 V 估算回路电流（只在图上标）
LETTERS = "ABCDEF"


def _d(v) -> Decimal:
    return Decimal(str(v))


def build(values: dict, inputs: dict, params: dict, edits: dict | None = None, manual: set = frozenset(),
          ratings: dict | None = None) -> dict | None:
    """values：规则结果（含 F3 的 cabinet_counts、F6 的回路数和可用电流，手动覆盖过的用手动值）；params：规则参数 {名字: 值}；
    edits：{power: {箱体: 回路}, data: {箱体: 网线}}；manual：手动覆盖过的结果名（CR-5）；ratings：箱体每种尺寸的最大电流 / 功率。"""
    counts = values.get("cabinet_counts")
    if (not counts or any(values.get(k) is None for k in ("circuits", "usable_a", "data_runs", "area_m2", "power_kw"))
            or "chain_max" not in params):
        return None
    usable, chain, cap_px = _d(values["usable_a"]), int(_d(params["chain_max"])), _d(params["px_per_data_cable"])
    plan = wiring.plan(inputs["width_mm"], counts, inputs["pixel_pitch_mm"], ratings, values["circuits"],
                       params | {"usable_a": usable})
    letter = {wiring.size_key(w, h): LETTERS[i] for i, (w, h, _n) in enumerate(counts)}
    w_per_m2 = _d(values["power_kw"]) * 1000 / _d(values["area_m2"])
    cabs = []
    for c in plan["cells"]:
        watts = c["watts"] if c["watts"] is not None else c["w"] * c["h"] / 1_000_000 * w_per_m2
        cabs.append({"id": c["id"], "row": c["row"], "col": c["col"], "x": int(c["x"]), "y": int(c["y"]), "w": int(c["w"]),
                     "h": int(c["h"]), "size": letter[c["size"]], "_cell": c, "_w": watts,
                     "_a": c["a"] if c["a"] is not None else watts / VOLTAGE})
    auto_circuit = {cid: g["no"] for g in plan["power"] for cid in g["cabinets"]}
    auto_cable = {cid: g["no"] for g in plan["data"] for cid in g["cabinets"]}
    n_circuits, n_cables = len(plan["power"]), len(plan["data"])
    edits = edits or {}
    power = {k: v for k, v in (edits.get("power") or {}).items() if k in auto_circuit and 1 <= v <= n_circuits}
    data = {k: v for k, v in (edits.get("data") or {}).items() if k in auto_cable and 1 <= v <= n_cables}
    for cab in cabs:
        cab["circuit"], cab["cable"] = power.get(cab["id"], auto_circuit[cab["id"]]), data.get(cab["id"], auto_cable[cab["id"]])
        cab["manual"] = cab["id"] in power or cab["id"] in data
        cab["px"], cab["watts"] = int(cab["_cell"]["px"]), float(cab["_w"].quantize(Decimal("0.1"), ROUND_HALF_UP))

    # 走线顺序：电源从左下、网线从左上（W1 的顺序）；手动换组后按这个顺序重新连
    power_order = [cid for g in plan["power"] for cid in g["cabinets"]]
    data_order = [cid for g in plan["data"] for cid in g["cabinets"]]
    by_id = {c["id"]: c for c in cabs}
    circuits, power_mm = [], Decimal(0)
    for no in range(1, n_circuits + 1):
        members = [by_id[cid] for cid in power_order if by_id[cid]["circuit"] == no]
        watts = sum((c["_w"] for c in members), Decimal(0))
        amps = sum((c["_a"] for c in members), Decimal(0))
        jumper = wiring.jumper_mm([c["_cell"] for c in members])
        power_mm += jumper
        circuits.append({"no": no, "cabinets": len(members), "watts": round(float(watts)),
                         "amps": float(amps.quantize(Decimal("0.01"), ROUND_HALF_UP)),
                         "over_a": amps > usable, "over_chain": len(members) > chain,
                         "over": amps > usable or len(members) > chain})
    cables, data_mm = [], Decimal(0)
    for no in range(1, n_cables + 1):
        path = [cid for cid in data_order if by_id[cid]["cable"] == no]
        px = sum((by_id[cid]["_cell"]["px"] for cid in path), Decimal(0))
        data_mm += wiring.jumper_mm([by_id[cid]["_cell"] for cid in path])
        cables.append({"no": no, "cabinets": len(path), "px": int(px), "over": px > cap_px, "path": path})
    for cab in cabs:
        del cab["_cell"], cab["_w"], cab["_a"]

    checks = []
    for x in circuits:
        if x["over_a"]:
            checks.append({"check": "BLOCK", "text": tr(f"回路 {x['no']} 超载：{x['amps']} A > 可用 {usable.normalize():f} A",
                                                     f"Circuit {x['no']} overloaded: {x['amps']} A > usable {usable.normalize():f} A")})
        if x["over_chain"]:
            checks.append({"check": "BLOCK", "text": tr(f"回路 {x['no']} 串接 {x['cabinets']} 箱，超过上限 {chain}",
                                                     f"Circuit {x['no']} chains {x['cabinets']} cabinets, over the limit {chain}")})
    for x in cables:
        if x["over"]:
            checks.append({"check": "BLOCK", "text": tr(f"网线 {x['no']} 超载：{x['px']:,} px > {int(cap_px):,} px",
                                                     f"Data cable {x['no']} overloaded: {x['px']:,} px > {int(cap_px):,} px")})
    if "cabinets" in manual and len(cabs) != values.get("cabinets"):
        checks.append({"check": "NOTE", "text": tr(
            f"图上按 F3 排布是 {len(cabs)} 个箱体，F3 手动值是 {values.get('cabinets')} 个",
            f"The F3 layout has {len(cabs)} cabinets; the manual F3 value is {values.get('cabinets')}")})
    if n_cables != values.get("data_runs"):
        checks.append({"check": "NOTE", "text": tr(
            f"W1 按箱数连续装是 {n_cables} 根，F9 是 {values.get('data_runs')} 根",
            f"W1 packing by cabinets gives {n_cables} cables; F9 gives {values.get('data_runs')}")})
    rows = []
    for c in plan["cells"]:
        if c["col"] == 1:
            rows.append(int(c["h"]))
    return {
        "width": int(_d(inputs["width_mm"])), "height": sum(rows), "cols": plan["cols"], "col_w": cabs[0]["w"], "rows": rows,
        "sizes": {letter[wiring.size_key(w, h)]: {"w": int(w), "h": int(h), "count": int(n)} for w, h, n in counts},
        "cabinets": cabs, "circuits": circuits, "cables": cables,
        "circuit_cap_a": float(usable), "chain_max": chain, "cable_cap_px": int(cap_px), "voltage": VOLTAGE,
        "spare_circuits": int(values.get("power_cables", n_circuits) - values.get("circuits", n_circuits)),
        "spare_cables": int(values.get("data_cables", n_cables) - values.get("data_runs", n_cables)),
        "power_jumpers": len(cabs) - n_circuits, "power_jumper_m": float(wiring.metres(power_mm)),
        "data_jumpers": len(cabs) - n_cables, "data_jumper_m": float(wiring.metres(data_mm)),
        "manual": {"power": len(power), "data": len(data)}, "edits": {"power": power, "data": data},
        "checks": checks, "blocked": any(x["check"] == "BLOCK" for x in checks),
    }
