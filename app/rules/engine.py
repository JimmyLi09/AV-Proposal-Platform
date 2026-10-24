"""规则引擎框架：按业务线跑规则，每个结果都带算式（代入数值）、参数与状态。"""
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from ..diagram import concept_svg
from ..i18n import text, tr, unit
from . import led, multiface, pj
from .expr import ExprError, evaluate, fmt, names, num, parse, substitute

SEED = Path(__file__).parent / "seed"
LINES = {"LED": {"steps": led.STEPS, "precheck": led.size_choices, "recommend": led.recommend,
                 "product_inputs": led.product_inputs, "catalog": led.catalog, "boq": led.boq,
                 "product_fed": led.PRODUCT_INPUTS, "diagram": led.diagram,
                 "boq_context": led.boq_context, "boq_extra": led.BOQ_EXTRA, "suggest": led.suggest,
                 "overridable": led.OVERRIDABLE},
         "PJ": {"steps": pj.STEPS, "precheck": pj.size_choices, "recommend": pj.recommend,
                "product_inputs": pj.product_inputs, "catalog": pj.catalog, "boq": pj.boq,
                "product_fed": pj.PRODUCT_INPUTS, "diagram": pj.diagram,
                "boq_context": pj.boq_context, "boq_extra": pj.BOQ_EXTRA, "suggest": pj.suggest,
                "overridable": pj.OVERRIDABLE}}
STATUSES = ["set", "review", "sample", "empty"]  # 越往后越不确定


def load_seed(line: str) -> tuple[dict, dict]:
    """(规则集初始内容, 试算样本)"""
    name = line.lower()
    return (json.loads((SEED / f"{name}.json").read_text(encoding="utf-8")),
            json.loads((SEED / f"{name}_sample.json").read_text(encoding="utf-8")))


def value_names(content: dict) -> set[str]:
    """规则集里所有输入和规则结果的名字（客户版 BOQ 模板只能引用这些）。"""
    line = LINES[content["business_line"]]
    out = {i["name"] for i in content["inputs"]}
    for rule in content["rules"]:
        out |= set(line["steps"][rule["step"]][2]) if "step" in rule else {o["name"] for o in rule["outputs"]}
    return out | set(line["boq_extra"])


def display_text(content: dict) -> dict[str, str]:
    """规则集里标签、分组、标题、说明、单位在当前界面语言下的写法（CR-4）。规则页按这个显示，保存时内容原样不变。"""
    out = {}
    for item in content["inputs"] + content["params"] + content["rules"]:
        for key in ("label", "group", "title", "note"):
            if item.get(key):
                out[item[key]] = text(item[key])
    for item in content["inputs"] + content["params"] + [o for r in content["rules"] for o in r.get("outputs", [])]:
        if item.get("unit"):
            out[item["unit"]] = unit(item["unit"])
    return out


def _quoted_text(expr: str) -> str:
    """算式里写的文字（例如 F16 的「墙面支架 1 套」）按界面语言显示；只用来显示，算式本身不变。"""
    return re.sub(r"'([^']*)'", lambda m: "'" + text(m[1]) + "'", expr)


def _worst(statuses) -> str:
    return max(statuses, key=STATUSES.index, default="set")


def _plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _show(v, decimals=None) -> str:
    if isinstance(v, Decimal) and decimals is not None:
        v = v.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return fmt(v) if not isinstance(v, str) else v


def validate(content: dict, base: dict) -> None:
    """保存前检查：结构不变（输入、参数、规则、产出名称），算式能解析且只引用已知名称。"""
    def sig(c):
        return ([i["name"] for i in c["inputs"]], [p["name"] for p in c["params"]],
                [(r["id"], r.get("step"), [o["name"] for o in r.get("outputs", [])]) for r in c["rules"]])

    if sig(content) != sig(base):
        raise ExprError(tr("只能改参数和算式，不能增删输入、参数、规则",
                              "Only parameters and formulas can change; inputs, parameters and rules cannot be added or removed"))
    for p in content["params"]:
        if p["status"] not in STATUSES:
            raise ExprError(tr(f"参数 {p['name']} 的状态不对", f"Parameter {p['name']}: invalid status"))
        if p["value"] is not None and (isinstance(p["value"], bool) or not isinstance(p["value"], (int, float))):
            raise ExprError(tr(f"参数 {p['name']} 要填数字", f"Parameter {p['name']} must be a number"))
    known = {i["name"] for i in content["inputs"]} | {p["name"] for p in content["params"]}
    steps = LINES[content["business_line"]]["steps"]
    for rule in content["rules"]:
        if "step" in rule:
            known |= set(steps[rule["step"]][2])
            continue
        for out in rule["outputs"]:
            if not out["cases"]:
                raise ExprError(f"{rule['id']} {out['name']}" + tr("：至少要有一条算式", ": needs at least one formula"))
            if any(not c.get("when") for c in out["cases"][:-1]):
                raise ExprError(f"{rule['id']} {out['name']}" + tr("：分档时除最后一行外每行都要写条件",
                                                                     ": every row except the last needs a condition"))
            for case in out["cases"]:
                for src in filter(None, (case.get("when"), case["expr"])):
                    unknown = {n for n in names(parse(src)) if n not in known and not n.startswith("cabinet_")}
                    if unknown:
                        raise ExprError(rule["id"] + tr("：不认识的名称 ", ": unknown names ") + ", ".join(sorted(unknown)))
            known.add(out["name"])


def run(content: dict, inputs: dict, catalog: dict, overrides: dict | None = None) -> dict:
    """overrides：手动覆盖的结果 {名字: 值}（CR-5）。规则照常算出规则值，再换成手动值，下游规则用手动值。"""
    line = LINES[content["business_line"]]
    ctx, status, params = {}, {}, {}
    for p in content["params"]:
        params[p["name"]] = p
        status[p["name"]] = p["status"]
        if p["value"] is not None:
            ctx[p["name"]] = num(p["value"])
    cabinet = catalog.get("cabinet") or {}
    for k, v in cabinet.items():
        ctx[f"cabinet_{k}"] = num(v)
        status[f"cabinet_{k}"] = "sample" if cabinet.get("sample") else "set"
    ctx.update({k: num(v) for k, v in inputs.items() if v not in (None, "", [])})

    choices = line["precheck"](ctx)
    if choices:
        return {"choices": {k: _plain(v) for k, v in choices.items()}, "rules": []}
    return {"choices": {}, "rules": [_run_rule(r, ctx, status, params, catalog, line["steps"], overrides or {})
                                     for r in content["rules"]]}


def _manual(line: dict, manual, decimals=None):
    """把规则值换成手动值：规则值留在 rule_value / rule_display 里，方便对比和回算。"""
    value = num(manual)
    line |= {"manual": True, "rule_value": line["value"], "rule_display": line["display"],
             "value": _plain(value), "display": _show(value, decimals)}
    return value


def _manual_trace(line: dict) -> str:
    return tr(f" → 手动 {line['display']}", f" → manual {line['display']}") if line.get("manual") else ""


def _run_rule(rule, ctx, status, params, catalog, steps, overrides) -> dict:
    result = {"id": rule["id"], "title": text(rule["title"]), "note": text(rule.get("note", "")), "lines": [],
              "display": "", "trace": "", "check": None, "status": rule.get("status", "set"),
              "params": [], "missing": [], "error": None, "manual": []}
    used: set[str] = set()
    try:
        if "step" in rule:
            fn, needs, _ = steps[rule["step"]]
            used = set(needs)
            missing = sorted(used - ctx.keys())
            if missing:
                result["missing"] = missing
                return result
            out = fn(ctx, catalog)
            outputs = dict(out.get("outputs", {}))
            for k, v in outputs.items():
                line = {"name": k, "value": _plain(v), "display": text(_show(v))}
                if k in overrides:
                    outputs[k] = _manual(line, overrides[k])
                ctx[k] = outputs[k]
                result["lines"].append(line)
            result["trace"] = out.get("trace", "") + "".join(
                tr(f"；手动 {ln['name']} = {ln['display']}", f"; manual {ln['name']} = {ln['display']}")
                for ln in result["lines"] if ln.get("manual"))
            result["check"] = out.get("check")
            result["note"] = out.get("note") or result["note"]
            if out.get("sample"):
                result["status"] = _worst([result["status"], "sample"])
            result["display"] = _step_display(rule["step"], outputs)
        else:
            for spec in rule["outputs"]:
                case = None
                for c in spec["cases"]:
                    when = parse(c["when"]) if c.get("when") else None
                    if when is not None:
                        used |= names(when)
                        if missing := sorted(names(when) - ctx.keys()):
                            result["missing"] = missing
                            return result
                        if not evaluate(when, ctx):
                            continue
                    case = c
                    break
                if case is None:
                    raise ExprError(spec["name"] + tr("：没有符合条件的算式，请检查输入", ": no formula matches; check the inputs"))
                tree = parse(case["expr"])
                used |= names(tree)
                if missing := sorted(names(tree) - ctx.keys()):
                    result["missing"] = missing
                    return result
                value = evaluate(tree, ctx)
                shown = text(_show(value, spec.get("decimals")))
                line = {
                    "name": spec["name"], "value": _plain(value), "display": shown, "unit": unit(spec.get("unit", "")),
                    "expr": _quoted_text(case["expr"]), "when": case.get("when"),
                    "substituted": _quoted_text(substitute(tree, ctx)),
                }
                if spec["name"] in overrides:
                    value = _manual(line, overrides[spec["name"]], spec.get("decimals"))
                result["lines"].append(line)
                ctx[spec["name"]] = value
            last = result["lines"][-1]
            if rule.get("check"):
                result["check"] = last["value"]
            template = rule.get("display")
            byname = {line["name"]: line["display"] for line in result["lines"]}
            result["display"] = (re.sub(r"\{(\w+)\}", lambda m: byname.get(m[1], m[0]), template) if template
                                 else f"{last['display']} {last.get('unit', '')}".strip())
            result["trace"] = tr("；", "; ").join(f"{ln['substituted']} = {ln.get('rule_display', ln['display'])}{_manual_trace(ln)}"
                                                  for ln in result["lines"])
    except (ExprError, ArithmeticError, TypeError) as e:
        result["error"] = str(e) if isinstance(e, ExprError) else tr("计算出错：", "Calculation error: ") + str(e)
        return result

    result["manual"] = [ln["name"] for ln in result["lines"] if ln.get("manual")]
    result["status"] = _worst([result["status"], *(status[n] for n in used if n in status)])
    for line in result["lines"]:
        status[line["name"]] = result["status"]  # 下游规则继承不确定程度
    result["params"] = [{"name": n, "label": text(params[n]["label"]), "value": params[n]["value"],
                         "unit": unit(params[n]["unit"]), "status": params[n]["status"]}
                        for n in sorted(used) if n in params]
    return result


def _step_display(step: str, outputs: dict) -> str:
    if step == "cabinet_layout" and outputs:
        return tr(f"{_show(outputs['cabinets'])} 个（{outputs['layout']}）", f"{_show(outputs['cabinets'])} ({outputs['layout']})")
    if step == "controller_pick" and outputs:
        return outputs["controller"] if not outputs["controller_qty"] else f"{_show(outputs['controller_qty'])} × {outputs['controller']}"
    if step == "processor_pick" and outputs:
        return f"{_show(outputs['processor_qty'])} × {outputs['processor']}"
    if step in pj.STEP_DISPLAY and outputs:
        return pj.STEP_DISPLAY[step](outputs)
    return ""


def calculate(content: dict, library: dict, inputs: dict, cabinet_id: str | None = None,
              overrides: dict | None = None) -> dict:
    """完整流程：从产品库推荐 → 带出产品参数 → 跑规则 → 内部明细，以及客户版 BOQ 模板要用的值。
    overrides：这个 Rev 的手动覆盖（CR-5），BOQ、示意图、图纸都用手动值。多面屏（CR-7）按面算，见 multiface.py。"""
    if multiface.is_multi(inputs):
        return multiface.calculate(content, library, inputs, cabinet_id, run)
    line = LINES[content["business_line"]]
    rec = line["recommend"](inputs, library, cabinet_id)
    out = run(content, {**inputs, **line["product_inputs"](rec["cabinet"])}, line["catalog"](library, rec["cabinet"]),
              overrides)
    values = {ln["name"]: ln["value"] for r in out["rules"] for ln in r["lines"]}
    manual = {n for r in out["rules"] for n in r["manual"]}
    out["manual"] = sorted(manual)
    out["recommendation"] = rec
    out["boq"] = line["boq"](values, rec["cabinet"], inputs, library, manual)
    out["values"] = line["boq_context"](values, rec["cabinet"], inputs)
    out["suggestions"] = line["suggest"](values, inputs, library)
    out["diagram"] = line["diagram"](values, out["boq"], inputs, rec["cabinet"], library, out["suggestions"], manual)
    if out["diagram"]:
        out["diagram"]["svg"] = concept_svg(out["diagram"])
    return out
