"""第 2 步验收：LED F1–F16 每条规则一个单元测试 + regression_cases.json 金标准 + 尺寸吸附。"""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.products.library import load_seed as load_library
from app.rules import led
from app.rules.engine import load_seed, run, validate
from app.rules.expr import ExprError, evaluate, parse, substitute

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
CASE = FIXTURE["led_royal_plaza"]
CONTENT, _ = load_seed("LED")
LIBRARY = load_library("LED")
IC25 = next(p for p in LIBRARY["products"] if p["id"] == "IC-25")
CATALOG = led.catalog(LIBRARY, IC25)  # 产品库示例 v1.0：IC-25 箱体，SC-4 / SC-2 控制器，SP-1 处理器
NO_MAX = led.catalog(LIBRARY, {k: v for k, v in IC25.items() if k != "cabinet_max"})  # 没有每箱最大电流 / 功率的箱体


def fixture_input(**changes) -> dict:
    """金标准输入换成引擎的输入名称（模组宽高拆成两个字段）。"""
    inp = dict(CASE["input"])
    inp["module_w_mm"], inp["module_h_mm"] = inp.pop("module_mm")
    inp.pop("power_distance_m")  # V1 规则不用
    inp.update(changes)
    return inp


def calc(content=CONTENT, catalog=CATALOG, **changes) -> dict:
    out = run(content, fixture_input(**changes), catalog)
    return {r["id"]: r for r in out["rules"]}


def grouping(mode: str) -> dict:
    content = copy.deepcopy(CONTENT)
    next(p for p in content["params"] if p["name"] == "data_grouping")["value"] = mode
    return content


def value(rule: dict, name: str):
    return next(line["value"] for line in rule["lines"] if line["name"] == name)


@pytest.fixture(scope="module")
def r():
    return calc()


# ---- 金标准 ----

def test_library_cabinet_matches_fixture_input():
    assert [IC25["module_w_mm"], IC25["module_h_mm"]] == CASE["input"]["module_mm"]
    assert IC25["cabinet_sizes_mm"] == CASE["input"]["cabinet_sizes_mm"]


def test_seed_constants_match_fixture():
    params = {p["name"]: p for p in CONTENT["params"]}
    c = dict(CASE["constants"])
    # 线径载流表：每种线径一个参数，都是示例值（CR-10）
    for mm2, amps in c.pop("cable_ampacity_a").items():
        p = params["ampacity_" + mm2.replace(".", "_") + "_mm2"]
        assert p["value"] == amps and (p["status"] == "sample") == c["cable_ampacity_sample"]
    c.pop("cable_ampacity_sample")
    # 每箱最大电流 / 功率在产品库里（IC-25 是规格书真实值）
    assert {k: {"a": v["a"], "w": v["w"]} for k, v in IC25["cabinet_max"].items()} == c.pop("cabinet_max")
    assert not any(v["sample"] for v in IC25["cabinet_max"].values())
    for name, v in c.items():
        assert params[name]["value"] == v, name
    assert "circuit_kw" not in params


def test_royal_plaza_golden(r):
    e = CASE["expect"]
    assert round(value(r["F1"], "area_m2"), 2) == e["F1_area_m2"]
    assert value(r["F2"], "modules") == e["F2_modules"]
    assert [value(r["F2"], "modules_x"), value(r["F2"], "modules_y")] == e["F2_grid"]
    assert value(r["F3"], "cabinets") == e["F3_cabinets"]
    assert value(r["F3"], "layout") == e["F3_layout"]
    assert [value(r["F4"], "res_x"), value(r["F4"], "res_y")] == e["F4_resolution"]
    assert round(value(r["F5"], "power_kw"), 2) == e["F5_power_kw"]
    t = e["F6_trace"]
    assert [value(r["F6"], n) for n in ("rated_a", "usable_a", "cab_per_circuit", "circuits_by_load", "circuits_by_chain")] \
        == [t["rated_a"], t["usable_a"], t["cab_per_circuit"], t["by_load"], t["by_chain"]]
    assert value(r["F6"], "circuits") == e["F6_circuits"]
    assert value(r["F7"], "power_cables") == e["F7_power_cables"]
    assert value(r["W1"], "power_group_sizes") == e["W1_power_groups_cabinets"]
    assert value(r["W1"], "power_jumpers") == e["W1_power_jumpers"]
    assert value(r["F10"], "spare_modules") == e["F10_spare_modules"]
    # 网线：默认按行整行（CASE["data_grouping_default"]），按箱数时网口最少；两种结果金标准都给了
    assert next(p for p in CONTENT["params"] if p["name"] == "data_grouping")["value"] == CASE["data_grouping_default"]["value"]
    for mode, x in e["F9_by_mode"].items():
        m = calc(grouping(mode))
        assert [value(m["F9"], "data_runs"), value(m["F9"], "data_cables")] == [x["data_runs"], x["data_cables"]], mode
        assert value(m["F9"], "data_runs_count") == e["F9_by_mode"]["count"]["data_runs"]  # 两种模式都显示「按箱数最少」
        assert m["F11"]["check"] == x["F11"]["check"], mode
        if "W1_data_groups_cabinets" in x:
            assert value(m["W1"], "data_group_sizes") == x["W1_data_groups_cabinets"]
            assert value(m["W1"], "data_jumpers") == x["data_jumpers"]
        if x["F11"]["check"] == "PASS":
            f = x["F11"]
            assert [value(m["F11"], k) for k in ("controller", "ports_used", "ports")] == [f["model"], f["ports_used"], f["ports"]]
            assert [round(value(m["F11"], k), 2) for k in ("load_mp", "capacity_mp")] == [f["load_mp"], f["capacity_mp"]]
        else:  # 按行整行要 5 口，SC-4 只有 4 口：阻断，建议型号里推荐 VX600（CR-2）
            values = {ln["name"]: ln["value"] for rule in m.values() for ln in rule["lines"]}
            picks = led.suggest(values, fixture_input(), LIBRARY)
            assert next(s["id"] for s in picks if s["status"] == "recommended") == x["F11"]["suggest"]
    assert value(r["F12"], "db_boxes") == e["F12_db_box"]
    assert r["F14"]["check"] == e["F14_viewing_check"]
    assert r["F15"]["check"] == e["F15_brightness_check"]["result"]
    assert (r["F15"]["status"] == "sample") == e["F15_brightness_check"]["sample"]
    # 金标准没有给信号源数：CR-2 起按 1 路算（F13 带一条提示，单独测）
    assert [x["id"] for x in r.values() if x["error"] or x["missing"]] == []


def test_size_snapping_offers_two_sizes_without_error():
    s = CASE["size_snapping_case"]
    out = run(CONTENT, fixture_input(width_mm=s["input_width_mm"]), CATALOG)
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
    assert r["F3"]["trace"] == "cols 7 × 640 · rows 4 × 480 + 1 × 640 → 28 + 7 · Σ 4760 W · max 0.96 A"
    assert value(r["F3"], "cabinets_w") == 4760 and r["F3"]["status"] == "set"  # IC-25 的最大功率 / 电流是规格书真实值


def test_f3_blocks_when_cabinets_cannot_fill_width():
    x = calc(width_mm=4800)  # 4800 是模组整数倍，但不是箱体宽 640 的整数倍（单屏时由 calculate 先替人选尺寸，见下）
    assert x["F3"]["check"] == "BLOCK" and "拼不出" in x["F3"]["note"]
    assert x["F8"]["waiting"] == ["F3"]  # 下游规则说「等 F3」，不报错
    assert led.cabinet_choices({k: Decimal(str(v)) for k, v in fixture_input(width_mm=4800).items()
                                if isinstance(v, (int, float))} | {"cabinet_sizes_mm": [[640, 480], [640, 640]]}) == {"width_mm": [4480, 5120]}


def test_f3_blocks_when_cabinet_widths_differ():
    x = calc(cabinet_sizes_mm=[[640, 480], [500, 500]])
    assert x["F3"]["check"] == "BLOCK" and "同宽" in x["F3"]["note"]
    assert "cabinets" in x["F8"]["missing"]  # 下游规则标缺失，不报错


def test_f4_resolution(r):
    assert r["F4"]["display"] == "1792 × 1024"
    assert value(r["F4"], "total_pixels") == 1_835_008


def test_f5_power_from_cabinet_max_power(r):
    assert r["F5"]["trace"] == "4760 / 1000 = 4.76" and r["F5"]["status"] == "set"  # 28 × 120 W + 7 × 200 W


def test_f5_falls_back_to_area_tier_without_cabinet_data():
    x = calc(catalog=NO_MAX, environment="outdoor")
    assert value(x["F5"], "power_kw") == pytest.approx(11.4688 * 0.8)
    assert x["F5"]["lines"][0]["when"] == "environment == 'outdoor'"  # 追溯里写明用的是面积算法
    assert x["F5"]["status"] == "sample"  # 户外功率密度是示例值
    # 2026-11-21：没有单箱电流时按箱体面积 × 每平米功耗 ÷ 电压估算（待确定），接着算回路，不再一路「缺少」
    assert not x["F6"]["missing"] and x["F6"]["status"] == "sample"
    assert "估算单箱电流" in x["F3"]["trace"] and x["F3"]["status"] == "sample"


def test_f6_load_budget_takes_the_larger_of_load_and_chain(r):
    lines = {ln["name"]: ln["substituted"] for ln in r["F6"]["lines"]}
    assert lines["rated_a"] == "min(20, 20)" and lines["usable_a"] == "20 * 0.85"
    assert lines["cab_per_circuit"] == "floor(17 / 0.96)" and lines["circuits_by_load"] == "ceil(35 / 17)"
    assert lines["circuits_by_chain"] == "ceil(35 / 10)" and lines["circuits"] == "max(3, 4)"
    assert r["F6"]["display"] == "4（带载 3 / 串接 4，取大）"
    assert r["F6"]["status"] == "sample"  # 线径载流是示例值
    thin = calc(next_param("power_cable_mm2", 1.5))  # 1.5 mm²：16 A × 0.85 = 13.6 A，每回路 14 箱
    assert [value(thin["F6"], n) for n in ("usable_a", "cab_per_circuit", "circuits")] == [13.6, 14, 4]


def next_param(name, v):
    content = copy.deepcopy(CONTENT)
    next(p for p in content["params"] if p["name"] == name)["value"] = v
    return content


def test_f7_power_cables_inherits_sample_status(r):
    assert r["F7"]["status"] == "sample" and value(r["F7"], "power_cables") == 5


def test_f8_spare_psu_and_cards(r):
    assert r["F8"]["display"] == "1 + 1"
    assert r["F8"]["status"] == "sample"


def test_f9_data_cables(r):
    assert value(r["F9"], "data_runs") == 5 and value(r["F9"], "data_runs_count") == 3  # 按行 5 路，按箱数最少 3 路
    assert r["F9"]["display"] == "6 根"


def test_f10_spare_modules_has_no_float_error():
    # 100 × 0.07 用浮点是 7.000000000000001，向上取整会变成 8；规则必须得 7
    content = copy.deepcopy(CONTENT)
    next(p for p in content["params"] if p["name"] == "spare_module_ratio")["value"] = 0.07
    x = calc(content, width_mm=3200, height_mm=1600)
    assert value(x["F2"], "modules") == 100
    assert value(x["F10"], "spare_modules") == 7


def test_f11_blocks_when_controller_too_small():
    library = copy.deepcopy(LIBRARY)
    next(p for p in library["products"] if p["id"] == "SC-4")["ports"] = 3  # SC-2 带载也不够
    x = {r["id"]: r for r in run(CONTENT, fixture_input(), led.catalog(library, IC25))["rules"]}
    assert x["F11"]["check"] == "BLOCK"


def test_f12_db_box(r):
    assert value(r["F12"], "db_boxes") == 1 and r["F12"]["status"] == "sample"


def test_f13_empty_signal_sources_count_as_one(r):
    # CR-2：信号源数量没填按 1 路算，并提示；填了就不提示
    assert r["F13"]["missing"] == [] and r["F13"]["display"] == "1 × Sample SP-1"
    assert (r["F13"]["check"], r["F13"]["note"]) == ("NOTE", "信号源数量没填，按 1 路计算")
    assert calc(signal_sources=1)["F13"]["check"] is None


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


def test_tier_without_condition_must_be_last():
    content = edited("F10", "spare_modules", "ceil(modules * 0.1)")
    out = next(o for rule in content["rules"] if rule["id"] == "F10" for o in rule["outputs"])
    out["cases"].insert(0, {"when": None, "expr": "1"})  # 没写条件的行挡住了后面的分档
    with pytest.raises(ExprError):
        validate(content, CONTENT)


# ---- 2026-11-21 Displan wall：模组整除但箱体拼不出 → 系统先选一个（待确定），接着算完 ----

def _cob_library():
    lib = copy.deepcopy(LIBRARY)
    cob = dict(IC25, id="COB-P093", model="Audax COB P0.93 600x337.5", pixel_pitch_mm=0.93, module_w_mm=150,
               module_h_mm=168.75, cabinet_sizes_mm=[[600, 337.5]], status="preferred")
    cob.pop("cabinet_max", None)
    lib["products"].append(cob)
    return lib


def test_cabinets_that_cannot_fill_the_height_get_two_sizes():
    ctx = {"width_mm": Decimal(9600), "height_mm": Decimal("1856.25"), "module_w_mm": Decimal(150),
           "module_h_mm": Decimal("168.75"), "cabinet_sizes_mm": [[Decimal(600), Decimal("337.5")]]}
    assert led.size_choices(ctx) == {}  # 模组整除
    assert led.cabinet_choices(ctx) == {"height_mm": [Decimal("1687.5"), Decimal(2025)]}
    assert led.auto_pick(Decimal("1856.25"), [Decimal("1687.5"), Decimal(2025)]) == Decimal("1687.5")  # 一样近取小的
    assert led.auto_pick(Decimal(2000), [Decimal("1687.5"), Decimal(2025)]) == Decimal(2025)


def test_system_picks_a_size_and_finishes_the_calculation():
    from app.rules.engine import calculate

    inputs = {k: v for k, v in fixture_input().items() if k not in ("module_w_mm", "module_h_mm")}
    inputs |= {"pixel_pitch_mm": 0.93, "width_mm": 9600, "height_mm": 1856.25}
    out = calculate(CONTENT, _cob_library(), inputs, "COB-P093")
    assert out["auto"] == {"height_mm": {"from": 1856.25, "to": 1687.5, "options": [1687.5, 2025]}}
    rules = {r["id"]: r for r in out["rules"]}
    assert rules["F3"]["check"] != "BLOCK" and rules["F3"]["display"].startswith("80")  # 16 列 × 5 行
    assert all(not r["missing"] for r in out["rules"]), [(r["id"], r["missing"]) for r in out["rules"] if r["missing"]]


def test_waiting_on_an_earlier_rule_names_the_rule():
    """F3 阻断（不同宽的箱体）时，后面的规则说「等 F3」，不列 cabinets_w 这种变量名。"""
    rules = {r["id"]: r for r in run(CONTENT, fixture_input(cabinet_sizes_mm=[[640, 480], [500, 500]]), CATALOG)["rules"]}
    assert rules["F3"]["check"] == "BLOCK"
    assert rules["F5"]["waiting"] == ["F3"]


def test_image_only_inputs_get_defaults_to_be_confirmed():
    """2026-11-21 只有图片：只读出宽、高、点间距，其它按规则集缺省值先算（待确定），不再「还缺 7 项」。"""
    from app.rules.engine import calculate

    out = calculate(CONTENT, LIBRARY, {"width_mm": 4480, "height_mm": 2560, "pixel_pitch_mm": 2.5})
    assert out["assumed"] == {"environment": "indoor", "installation": "wall", "maintenance": "front",
                              "brightness_required_nits": 600, "signal_sources": 1, "viewing_distance_m": [2.5, 7.5]}
    assert not out["recommendation"]["missing"] and all(not r["missing"] for r in out["rules"])
    # 填了的照填的算，不补
    out = calculate(CONTENT, LIBRARY, {"width_mm": 4480, "height_mm": 2560, "pixel_pitch_mm": 2.5, "environment": "indoor",
                                       "brightness_required_nits": 800})
    assert "environment" not in out["assumed"] and "brightness_required_nits" not in out["assumed"]
    # 老版本规则集没有缺省值参数：照旧缺什么说什么
    old = copy.deepcopy(CONTENT)
    old["params"] = [p for p in old["params"] if not p["name"].startswith("default_")]
    assert calculate(old, LIBRARY, {"width_mm": 4480, "height_mm": 2560, "pixel_pitch_mm": 2.5})["recommendation"]["missing"]


def test_pitch_is_picked_from_the_library_when_not_given():
    """只有现场照片：读出尺寸和观看距离，没有点间距 → 从产品库挑（待确定）。
    观看距离 4–6 m、每毫米 1 m：点间距不超过 4 mm，示例库里室内前维护有 P2.5、P1.9 → 取 P2.5。"""
    from app.rules.engine import calculate

    out = calculate(CONTENT, LIBRARY, {"width_mm": 4480, "height_mm": 2560, "viewing_distance_m": [4, 6]})
    assert out["assumed"]["pixel_pitch_mm"] == 2.5 and out["recommendation"]["cabinet"]["id"] == "IC-25"
    out = calculate(CONTENT, LIBRARY, {"width_mm": 4480, "height_mm": 2560, "viewing_distance_m": [2, 3]})
    assert out["assumed"]["pixel_pitch_mm"] == 1.9  # 近看只能用更小的点间距
    out = calculate(CONTENT, LIBRARY, {"width_mm": 4480, "height_mm": 2560})  # 观看距离也没写：取首选箱体
    assert out["assumed"]["pixel_pitch_mm"] == 2.5 and out["assumed"]["viewing_distance_m"] == [2.5, 7.5]


def test_assumptions_are_written_into_the_proposal_risks(tmp_path):
    """审批和导出：系统先定的（缺省值、先选的尺寸）写进「风险与假设」，客户看得到是待确定。"""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(tmp_path)) as c:
        u = c.post("/api/users", json={"name": "JM", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": u["id"]})
        p = c.post("/api/projects", json={"name": "Img", "client": "T"}).json()
        prop = c.post(f"/api/projects/{p['id']}/proposals", json={"business_line": "LED"}).json()
        base = f"/api/proposals/{prop['id']}"
        c.put(f"{base}/inputs", json={"inputs": {"width_mm": 4500, "height_mm": 2560, "pixel_pitch_mm": 2.5}})
        from app import proposal_doc
        v = c.get(base).json()
        assert v["result"]["assumed"]["environment"] == "indoor" and v["result"]["auto"]["width_mm"]["to"] == 4480
        from types import SimpleNamespace
        risks = proposal_doc._risks(SimpleNamespace(business_line="LED"), v, {"clauses": []})
        assert any("资料里没写" in r and "使用环境 室内" in r for r in risks), risks
        assert any(r.startswith("屏宽：设计 4500") and "按 4480 计算" in r for r in risks), risks


def test_recommendation_prefers_cabinets_with_complete_data():
    """2026-11-28 8SW Media Wall：P2 的箱体有 8 个，排第一的是规格书导入、没读到模组尺寸的 → 一路「还缺：模组宽」。
    资料齐的排前面；只剩缺资料的才用，并说清缺什么。"""
    lib = copy.deepcopy(LIBRARY)
    gap = dict(IC25, id="P25-GAP", model="P2.5 imported", module_w_mm=None, module_h_mm=None, status="preferred")
    lib["products"].insert(0, gap)
    rec = led.recommend(fixture_input(), lib)
    assert rec["cabinet"]["id"] == "IC-25" and rec["block"] is None and rec["candidates"][-1]["id"] == "P25-GAP"
    lib["products"] = [p for p in lib["products"] if p["id"] != "IC-25"]
    rec = led.recommend(fixture_input(), lib)
    assert rec["cabinet"]["id"] == "P25-GAP" and "没填模组宽、模组高" in rec["block"] and "产品库" in rec["block"]


# ---- 2026-11-28 全流程用真实项目跑一遍时找到的 ----

def _p2_library():
    lib = copy.deepcopy(LIBRARY)
    lib["products"].append(dict(IC25, id="P2-640x480", model="P2 640x480", pixel_pitch_mm=2, cabinet_sizes_mm=[[640, 480]],
                                status="preferred", brightness_nits=None))
    return lib


def test_snaps_to_the_module_then_to_the_cabinet():
    """8SW Media Wall 13500 × 5920、P2 640 × 480：宽不是模组整数倍，高是模组整数倍但 480 高的箱体拼不出——两个都先选好，接着算完。"""
    from app.rules.engine import calculate

    inputs = {k: v for k, v in fixture_input().items() if k not in ("module_w_mm", "module_h_mm", "cabinet_sizes_mm")}
    inputs |= {"pixel_pitch_mm": 2, "width_mm": 13500, "height_mm": 5920}
    out = calculate(CONTENT, _p2_library(), inputs, "P2-640x480")
    assert out["auto"] == {"width_mm": {"from": 13500, "to": 13440, "options": [13440, 13760]},
                           "height_mm": {"from": 5920, "to": 5760, "options": [5760, 6240]}}
    assert all(not r["missing"] and not r["error"] for r in out["rules"])


def test_unknown_product_brightness_is_to_be_confirmed_not_an_error():
    """Displan wall：产品库的 COB 箱体没填亮度，F15 写「待确定」，不再「计算出错」挡住整个方案。"""
    from app.rules.engine import calculate

    inputs = {k: v for k, v in fixture_input().items() if k not in ("module_w_mm", "module_h_mm", "cabinet_sizes_mm")}
    inputs |= {"pixel_pitch_mm": 2, "width_mm": 3840, "height_mm": 1920}
    f15 = next(r for r in calculate(CONTENT, _p2_library(), inputs, "P2-640x480")["rules"] if r["id"] == "F15")
    assert f15["error"] is None and f15["missing"] == [] and f15["check"] == "NOTE" and "亮度" in f15["note"]
