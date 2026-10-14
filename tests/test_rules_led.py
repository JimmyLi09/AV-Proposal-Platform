"""第 2 步验收：LED F1–F16 每条规则一个单元测试 + regression_cases.json 金标准 + 尺寸吸附。"""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.rules.engine import load_seed, run, validate
from app.rules.expr import ExprError, evaluate, parse, substitute

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
CASE = FIXTURE["led_royal_plaza"]
CONTENT, SAMPLE = load_seed("LED")


def fixture_input(**changes) -> dict:
    """金标准输入换成引擎的输入名称（模组宽高拆成两个字段）。"""
    inp = dict(CASE["input"])
    inp["module_w_mm"], inp["module_h_mm"] = inp.pop("module_mm")
    inp.pop("power_distance_m")  # V1 规则不用
    inp.update(changes)
    return inp


def calc(content=CONTENT, **changes) -> dict:
    out = run(content, fixture_input(**changes), SAMPLE["catalog"])
    return {r["id"]: r for r in out["rules"]}


def value(rule: dict, name: str):
    return next(line["value"] for line in rule["lines"] if line["name"] == name)


@pytest.fixture(scope="module")
def r():
    return calc()


# ---- 金标准 ----

def test_seed_constants_match_fixture():
    params = {p["name"]: p for p in CONTENT["params"]}
    for name, v in CASE["constants"].items():
        assert params[name]["value"] == v, name


def test_royal_plaza_golden(r):
    e = CASE["expect"]
    assert round(value(r["F1"], "area_m2"), 2) == e["F1_area_m2"]
    assert value(r["F2"], "modules") == e["F2_modules"]
    assert [value(r["F2"], "modules_x"), value(r["F2"], "modules_y")] == e["F2_grid"]
    assert value(r["F3"], "cabinets") == e["F3_cabinets"]
    assert value(r["F3"], "layout") == e["F3_layout"]
    assert [value(r["F4"], "res_x"), value(r["F4"], "res_y")] == e["F4_resolution"]
    assert round(value(r["F5"], "power_kw"), 2) == e["F5_power_kw"]
    assert value(r["F6"], "circuits") == e["F6_circuits"]
    assert value(r["F7"], "power_cables") == e["F7_power_cables"]
    assert value(r["F9"], "data_cables") == e["F9_data_cables"]
    assert value(r["F10"], "spare_modules") == e["F10_spare_modules"]
    c = e["F11_controller"]
    assert value(r["F11"], "controller") == c["model"]
    assert value(r["F11"], "controller_qty") == c["qty"]
    assert round(value(r["F11"], "load_mp"), 2) == c["load_mp"]
    assert round(value(r["F11"], "capacity_mp"), 2) == c["capacity_mp"]
    assert value(r["F11"], "ports_used") == c["ports_used"]
    assert value(r["F11"], "ports") == c["ports"]
    assert r["F11"]["check"] == c["check"]
    # 金标准里的英文说明 "all ports used, spare cable has no spare port"，界面说明句按规范写中文
    assert r["F11"]["note"] == "网口全部用满，备用线没有空余网口"
    assert value(r["F12"], "db_boxes") == e["F12_db_box"]
    assert r["F14"]["check"] == e["F14_viewing_check"]
    assert r["F15"]["check"] == e["F15_brightness_check"]["result"]
    assert (r["F15"]["status"] == "sample") == e["F15_brightness_check"]["sample"]
    # F13 要信号源数，金标准没有给，单独测
    assert [x["id"] for x in r.values() if x["error"] or x["missing"]] == ["F13"]


def test_size_snapping_offers_two_sizes_without_error():
    s = CASE["size_snapping_case"]
    out = run(CONTENT, fixture_input(width_mm=s["input_width_mm"]), SAMPLE["catalog"])
    assert out["choices"] == {"width_mm": s["expect_options_mm"]}
    assert out["rules"] == []  # 选定尺寸之前不计算


# ---- 每条规则 ----

def test_f1_area_keeps_full_precision_for_later_rules(r):
    assert value(r["F1"], "area_m2") == 11.4688
    assert r["F1"]["display"] == "11.47 ㎡"
    assert r["F1"]["trace"] == "4480 * 2560 / 1000000 = 11.47"


def test_f2_modules(r):
    assert r["F2"]["display"] == "224 块"


def test_f3_primary_cabinet_size_first(r):
    assert r["F3"]["trace"] == "cols 7 × 640 · rows 4 × 480 + 1 × 640 → 28 + 7"


def test_f3_blocks_when_cabinets_cannot_fill_width():
    x = calc(width_mm=4800)  # 4800 是模组整数倍，但不是箱体宽 640 的整数倍
    assert x["F3"]["check"] == "BLOCK" and "拼不出" in x["F3"]["note"]
    assert "cabinets" in x["F8"]["missing"]  # 下游规则标缺失，不报错


def test_f4_resolution(r):
    assert r["F4"]["display"] == "1792 × 1024"
    assert value(r["F4"], "total_pixels") == 1_835_008


def test_f5_power_tier_by_environment():
    assert value(calc(environment="outdoor")["F5"], "power_kw") == pytest.approx(11.4688 * 0.8)
    assert calc(environment="outdoor")["F5"]["status"] == "sample"  # 户外功率密度是示例值
    assert calc()["F5"]["status"] == "set"


def test_f6_circuits_round_up(r):
    assert r["F6"]["trace"] == "ceil(5.7344 / 2.5) = 3"


def test_f7_power_cables_inherits_review_status(r):
    assert r["F7"]["status"] == "review"


def test_f8_spare_psu_and_cards(r):
    assert r["F8"]["display"] == "1 + 1"
    assert r["F8"]["status"] == "sample"


def test_f9_data_cables(r):
    assert value(r["F9"], "data_runs") == 4
    assert r["F9"]["display"] == "5 根"


def test_f10_spare_modules_has_no_float_error():
    # 100 × 0.07 用浮点是 7.000000000000001，向上取整会变成 8；规则必须得 7
    content = copy.deepcopy(CONTENT)
    next(p for p in content["params"] if p["name"] == "spare_module_ratio")["value"] = 0.07
    x = calc(content, width_mm=3200, height_mm=1600)
    assert value(x["F2"], "modules") == 100
    assert value(x["F10"], "spare_modules") == 7


def test_f11_blocks_when_controller_too_small():
    catalog = copy.deepcopy(SAMPLE["catalog"])
    catalog["controllers"][0]["ports"] = 3
    x = {r["id"]: r for r in run(CONTENT, fixture_input(), catalog)["rules"]}
    assert x["F11"]["check"] == "BLOCK"


def test_f12_db_box(r):
    assert value(r["F12"], "db_boxes") == 1 and r["F12"]["status"] == "sample"


def test_f13_processor_needs_signal_sources(r):
    assert r["F13"]["missing"] == ["signal_sources"]  # 金标准没有信号源数，缺失要标出来
    assert calc(signal_sources=1)["F13"]["display"] == "1 × Sample SP-1"


def test_f14_viewing_distance_note_when_too_close():
    assert calc(viewing_distance_m=[2, 6])["F14"]["check"] == "NOTE"


def test_f15_brightness_note_when_too_dim():
    assert calc(brightness_required_nits=1000)["F15"]["check"] == "NOTE"


def test_f16_installation_items(r):
    assert value(r["F16"], "installation_items") == "墙面支架 1 套（不含钢结构）"
    assert r["F16"]["status"] == "sample"


# ---- 算式可编辑 ----

def edited(rule_id, name, expr):
    content = copy.deepcopy(CONTENT)
    out = next(o for rule in content["rules"] if rule["id"] == rule_id for o in rule["outputs"] if o["name"] == name)
    out["cases"] = [{"expr": expr}]
    return content


def test_edited_formula_changes_result():
    content = edited("F9", "data_runs", "ceil(total_pixels / 716800)")
    validate(content, CONTENT)
    assert value(calc(content)["F9"], "data_cables") == 4


def test_tiered_formula_by_pixel_pitch():
    content = edited("F10", "spare_modules", "ceil(modules * 0.1)")
    out = next(o for rule in content["rules"] if rule["id"] == "F10" for o in rule["outputs"])
    out["cases"].insert(0, {"when": "pixel_pitch_mm < 2", "expr": "ceil(modules * 0.08)"})
    validate(content, CONTENT)
    assert value(calc(content)["F10"], "spare_modules") == 23
    assert value(calc(content, pixel_pitch_mm=1.6)["F10"], "spare_modules") == 18


@pytest.mark.parametrize("expr", [
    "__import__('os')", "width_mm.__class__", "(lambda: 1)()", "[1, 2]", "open('x')", "width_mm[0]", "unknown_name",
])
def test_unsafe_or_unknown_formula_rejected(expr):
    with pytest.raises(ExprError):
        validate(edited("F1", "area_m2", expr), CONTENT)


def test_structure_cannot_change():
    content = copy.deepcopy(CONTENT)
    content["rules"].pop()
    with pytest.raises(ExprError):
        validate(content, CONTENT)


def test_substitute_shows_values():
    tree = parse("ceil(a / b) + 1")
    ctx = {"a": Decimal(1835008), "b": Decimal(560000)}
    assert substitute(tree, ctx) == "ceil(1,835,008 / 560,000) + 1"
    assert evaluate(tree, ctx) == 5
