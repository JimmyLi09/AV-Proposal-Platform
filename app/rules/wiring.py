"""W1 接线布置（CR-10 / CR-11）：按 F3 的箱体排布，先排电源回路、再排网线，算跳线根数和长度，并逐组检查带载。

- 箱体：主尺寸的行放在下面（和 CR-3 的图纸一样），编号从左下角 R1C1 开始。
- 方向 wiring_orientation：row 按行（默认）/ col 按列。走线 power_route / data_route：S（相邻行反向）/ straight（同方向，回线沿行缝走）。
- 电源从最下一行、靠配电箱一侧（左下）开始；按走线顺序把箱体连续分成 circuits 组，箱数尽量平均（相差不超过 1），可以跨行。
- 网线从最上一行、靠发送卡一侧（左上）开始。rows：从上往下装整行，装到不超过每网口带载；一行本身就超出时这一行按箱数平均拆开。
  count：按箱数连续装满再换下一口。
- 跳线：电源 = 箱数 − 回路数，网线 = 箱数 − 网口数；长度按相邻两箱中心距离（横向 + 纵向）累加，直走时自然包含回线。
步骤写在代码里，参数在规则页可改。长度、电流、像素都用整数 mm 或 Decimal。
"""
from decimal import ROUND_HALF_UP, Decimal


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def size_key(w, h) -> str:
    return f"{int(_d(w))}x{int(_d(h))}"


def cells(width_mm, counts, pitch, ratings: dict | None) -> tuple[list[dict], int]:
    """箱体格子（从左下角开始编号），以及列数。counts：F3 的 [[宽, 高, 个数], ...]，主尺寸在前。"""
    col_w = _d(counts[0][0])
    cols = int(_d(width_mm) / col_w)
    out, y, row = [], Decimal(0), 0
    for w, h, n in counts:
        for _ in range(int(_d(n)) // cols):
            row += 1
            for c in range(cols):
                r = (ratings or {}).get(size_key(w, h)) or {}
                out.append({"id": f"R{row}C{c + 1}", "row": row, "col": c + 1, "x": col_w * c, "y": y, "w": col_w, "h": _d(h),
                            "size": size_key(w, h), "px": (col_w / _d(pitch)) * (_d(h) / _d(pitch)),
                            "a": _d(r["a"]) if r.get("a") is not None else None,
                            "watts": _d(r["w"]) if r.get("w") is not None else None})
            y += _d(h)
    return out, cols


def lines(grid: list[dict], orientation: str, start_top: bool) -> list[list[dict]]:
    """按方向分成行（或列），从下往上（电源）或从上往下（网线）排；每条线里从左到右（或从下到上 / 从上到下）。"""
    key, along = ("row", "col") if orientation == "row" else ("col", "row")
    groups: dict[int, list[dict]] = {}
    for c in grid:
        groups.setdefault(c[key], []).append(c)
    order = sorted(groups)
    if orientation == "row" and start_top:
        order.reverse()
    out = []
    for k in order:
        line = sorted(groups[k], key=lambda c: c[along])
        if orientation == "col" and start_top:
            line.reverse()  # 按列时网线从上往下走
        out.append(line)
    return out


def route(lines_: list[list[dict]], how: str) -> list[list[dict]]:
    """S 形：相邻两条线方向相反；直走：每条线同一方向。"""
    return [line[::-1] if how == "S" and i % 2 else line for i, line in enumerate(lines_)]


def _balanced(items: list, parts: int) -> list[list]:
    q, r = divmod(len(items), parts)
    out, i = [], 0
    for k in range(parts):
        n = q + (1 if k < r else 0)
        out.append(items[i:i + n])
        i += n
    return out


def power_groups(order: list[dict], circuits: int) -> list[list[dict]]:
    n = max(1, min(int(circuits), len(order)))
    return _balanced(order, n)


def data_groups(lines_: list[list[dict]], cap: Decimal, mode: str) -> list[list[dict]]:
    px = lambda cs: sum((c["px"] for c in cs), Decimal(0))  # noqa: E731
    out, current = [], []
    if mode == "count":
        for c in (c for line in lines_ for c in line):
            if current and px(current) + c["px"] > cap:
                out.append(current)
                current = []
            current.append(c)
        return out + [current] if current else out
    for line in lines_:
        if px(line) > cap:  # 一行就超出：这一行按箱数平均拆开
            if current:
                out.append(current)
                current = []
            parts = -(-px(line) // cap)
            while parts < len(line) and any(px(p) > cap for p in _balanced(line, int(parts))):
                parts += 1
            out += _balanced(line, int(parts))
            continue
        if current and px(current) + px(line) > cap:
            out.append(current)
            current = []
        current = current + line
    return out + [current] if current else out


def _center(c: dict) -> tuple[Decimal, Decimal]:
    return c["x"] + c["w"] / 2, c["y"] + c["h"] / 2


def jumper_mm(group: list[dict]) -> Decimal:
    total = Decimal(0)
    for a, b in zip(group, group[1:]):
        (ax, ay), (bx, by) = _center(a), _center(b)
        total += abs(ax - bx) + abs(ay - by)
    return total


def metres(mm: Decimal) -> Decimal:
    return (mm / 1000).quantize(Decimal("0.1"), ROUND_HALF_UP)


def plan(width_mm, counts, pitch, ratings, circuits, p: dict) -> dict:
    """p：规则参数（usable_a、chain_max、px_per_data_cable、data_grouping、wiring_orientation、power_route、data_route）。"""
    grid, cols = cells(width_mm, counts, pitch, ratings)
    orientation = p.get("wiring_orientation") or "row"
    power_order = [c for line in route(lines(grid, orientation, False), p.get("power_route") or "S") for c in line]
    data_lines = route(lines(grid, orientation, True), p.get("data_route") or "straight")
    cap, usable, chain = _d(p["px_per_data_cable"]), _d(p["usable_a"]), int(_d(p["chain_max"]))
    power = []
    for no, g in enumerate(power_groups(power_order, circuits), 1):
        amps = sum((c["a"] for c in g), Decimal(0)) if all(c["a"] is not None for c in g) else None
        power.append({"no": no, "cabinets": [c["id"] for c in g], "amps": amps, "jumper_mm": jumper_mm(g),
                      "over_a": amps is not None and amps > usable, "over_chain": len(g) > chain})
    data = []
    for no, g in enumerate(data_groups(data_lines, cap, p.get("data_grouping") or "rows"), 1):
        px = sum((c["px"] for c in g), Decimal(0))
        data.append({"no": no, "cabinets": [c["id"] for c in g], "px": px, "jumper_mm": jumper_mm(g), "over": px > cap})
    return {"cells": grid, "cols": cols, "power": power, "data": data,
            "power_jumpers": len(grid) - len(power), "data_jumpers": len(grid) - len(data),
            "power_jumper_mm": sum((g["jumper_mm"] for g in power), Decimal(0)),
            "data_jumper_mm": sum((g["jumper_mm"] for g in data), Decimal(0))}
