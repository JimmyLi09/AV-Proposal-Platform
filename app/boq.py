"""BOQ 加价：单价人工录入，系统只做加总；过期单价标红；V1 不推算加价。"""
from datetime import date


def price(lines: list[dict], manual: list[dict], costs: dict, today: date) -> dict:
    """lines：规则带出的行；manual：人工增加的行（自带单价）；costs：key → 当前单价。金额单位：分。"""
    out, subtotal, missing, expired = [], 0, 0, 0
    for line in lines + [m | {"manual": True, "included": False, "key": ""} for m in manual]:
        line = dict(line)
        cost = None if line["manual"] or line["included"] else costs.get(line["key"])
        unit = line.get("unit_cost") if line["manual"] else (cost["amount_cents"] if cost else None)
        line["unit_cost"] = unit
        line["cost_valid_until"] = cost["valid_until"] if cost else None
        line["cost_sample"] = bool(cost and cost["sample"])
        line["cost_expired"] = bool(cost and cost["valid_until"] and date.fromisoformat(cost["valid_until"]) < today)
        qty = line.get("qty")
        line["subtotal"] = round(unit * qty) if unit is not None and isinstance(qty, (int, float)) else None
        if not line["included"]:
            if line["subtotal"] is None:
                missing += 1
            else:
                subtotal += line["subtotal"]
            expired += line["cost_expired"]
        out.append(line)
    priced = [x for x in out if not x["included"]]
    return {"lines": out, "subtotal": subtotal, "priced": len(priced) - missing, "count": len(priced),
            "missing": missing, "expired": expired}
