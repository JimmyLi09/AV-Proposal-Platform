"""CR-10 验收：带载预算。F5 用每箱最大功率，F6 先算线的带载（空开、线径、负载系数、单箱电流）再算串接上限，两者取大；
F9 默认按行整行（W1 从上往下装整行），按箱数时网口最少；F11 的网口要求 = 网线路数。金标准 led_royal_plaza（已在
test_rules_led.py）和 led_wiring_28_cabinets 都要通过；改参数生成新的规则版本，结果跟着变。"""
import copy
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.db import MIGRATIONS, make_engine, migrate
from app.main import create_app
from app.products.library import load_seed as load_library
from app.rules import wiring
from app.rules.engine import calculate, load_seed, validate

CASES = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
CASE = CASES["led_wiring_28_cabinets"]
RULES, SAMPLE = load_seed("LED")
LEGACY = json.loads((Path(__file__).parent / "fixtures" / "rules_led_v1_5.json").read_text(encoding="utf-8"))


def library_640x640():
    """用例是全 640×640 箱体（7 × 4）：IC-25 只留这一种尺寸。"""
    lib = copy.deepcopy(load_library("LED"))
    next(p for p in lib["products"] if p["id"] == "IC-25")["cabinet_sizes_mm"] = CASE["input"]["cabinet_sizes_mm"]
    return lib


def inputs():
    return SAMPLE["input"] | {k: CASE["input"][k] for k in ("pixel_pitch_mm", "width_mm", "height_mm")}


def with_params(**values):
    content = copy.deepcopy(RULES)
    for p in content["params"]:
        if p["name"] in values:
            p["value"] = values[p["name"]]
    return content


def run(content=RULES, overrides=None):
    out = calculate(content, library_640x640(), inputs(), overrides=overrides)
    rules = {r["id"]: r for r in out["rules"]}
    values = {ln["name"]: ln["value"] for r in out["rules"] for ln in r["lines"]}
    return rules, values, out


def plan(values, content=RULES):
    params = {p["name"]: p["value"] for p in content["params"]} | {"usable_a": values["usable_a"]}
    cabinet = next(p for p in library_640x640()["products"] if p["id"] == "IC-25")
    return wiring.plan(CASE["input"]["width_mm"], values["cabinet_counts"], CASE["input"]["pixel_pitch_mm"],
                       cabinet["cabinet_max"], values["circuits"], params)


def test_wiring_28_cabinets_golden():
    e, c = CASE["expect"], CASE["constants"]
    params = {p["name"]: p["value"] for p in RULES["params"]}
    for name in ("mcb_a", "mains_v", "load_factor", "power_cable_mm2", "chain_max", "px_per_data_cable",
                 "wiring_orientation", "power_route", "data_route"):
        assert params[name] == c[name], name
    r, v, _ = run()
    assert v["cabinets"] == 28 and v["power_kw"] == e["F5_power_kw"]
    t = e["F6_trace"]
    assert [v["usable_a"], v["cab_per_circuit"], v["circuits_by_load"], v["circuits_by_chain"]] == \
        [t["usable_a"], t["cab_per_circuit"], t["by_load"], t["by_chain"]]
    assert r["F6"]["display"] == "3（带载 2 / 串接 3，取大）"
    assert v["circuits"] == e["F6_circuits"] and v["power_cables"] == e["F7_power_cables"]

    p = plan(v)
    assert [len(g["cabinets"]) for g in p["power"]] == e["W1_power_groups_cabinets"]
    assert [float(g["amps"]) for g in p["power"]] == e["W1_power_group_current_a"]
    assert v["power_jumpers"] == e["W1_power_jumpers"] and v["power_jumper_m"] == e["W1_power_jumper_m"]

    rows = e["F9_rows"]
    assert [v["data_runs"], v["data_cables"]] == [rows["data_runs"], rows["data_cables"]]
    assert v["data_group_sizes"] == rows["W1_data_groups_cabinets"]
    assert [int(g["px"]) for g in p["data"]] == rows["group_px"]
    assert v["data_jumpers"] == rows["data_jumpers"] and v["data_jumper_m"] == rows["data_jumper_m"]
    f11 = e["F11"]
    assert [v["controller"], v["ports_used"], v["ports"], r["F11"]["check"]] == [f11["model"], f11["ports_used"], f11["ports"],
                                                                                 f11["check"]]
    assert r["W1"]["check"] == "PASS"

    _, count, _ = run(with_params(data_grouping="count"))
    assert [count["data_runs"], count["data_cables"]] == [e["F9_count"]["data_runs"], e["F9_count"]["data_cables"]]


def test_wiring_28_cabinets_behaviour():
    by_change = {b["change"]: b["expect"] for b in CASE["behaviour"]}
    _, v, _ = run(with_params(chain_max=6))
    assert v["circuits"] == by_change["chain_max = 6"]["F6_circuits"]

    # F6 手动改成 2 路（写了原因）：W1 按手动值分组，两路都超过串接上限 10，标红并阻断
    r, v, _ = run(overrides={"circuits": 2})
    manual = by_change["F6 manual = 2 with reason"]
    assert v["power_group_sizes"] == manual["W1_power_groups_cabinets"]
    assert r["W1"]["check"] == "BLOCK" and "串接 14 箱 > 上限 10" in r["W1"]["note"]

    _, v, _ = run(with_params(power_cable_mm2=1.5))
    thin = by_change["power_cable_mm2 = 1.5 (16 A)"]
    assert [v["usable_a"], v["cab_per_circuit"], v["circuits"]] == [thin["F6_trace"]["usable_a"],
                                                                    thin["F6_trace"]["cab_per_circuit"], thin["F6_circuits"]]


@pytest.mark.parametrize("orientation", ["row", "col"])
@pytest.mark.parametrize("power_route", ["S", "straight"])
@pytest.mark.parametrize("data_route", ["S", "straight"])
def test_direction_and_routing_change_groups_and_jumpers_not_counts(orientation, power_route, data_route):
    content = with_params(wiring_orientation=orientation, power_route=power_route, data_route=data_route)
    validate(content, RULES)
    r, v, _ = run(content)
    assert (v["circuits"], v["data_runs"]) == (3, 4) and r["W1"]["check"] == "PASS"
    assert v["power_jumpers"] == 25 and v["data_jumpers"] == 24  # 根数 = 箱数 − 组数
    if power_route == "straight" and orientation == "row":
        assert v["power_jumper_m"] > 16  # 直走跨行时要加回线


def test_count_grouping_packs_cabinets_and_flags_nothing_when_it_fits():
    content = with_params(data_grouping="count")
    r, v, _ = run(content)
    assert v["data_group_sizes"] == [10, 10, 8] and v["data_runs"] == v["data_runs_count"] == 3
    assert r["F11"]["check"] == "PASS" and v["ports_used"] == 3


def test_cabinet_without_ratings_falls_back_for_power_but_needs_current_for_circuits():
    lib = library_640x640()
    del next(p for p in lib["products"] if p["id"] == "IC-25")["cabinet_max"]
    out = calculate(RULES, lib, inputs())
    r = {x["id"]: x for x in out["rules"]}
    assert r["F5"]["lines"][0]["when"] == "environment == 'indoor'"  # 退回按面积 × 每平米功耗，追溯里看得到
    assert "cabinet_max_a" in r["F6"]["missing"]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.base = "/api/proposals/" + str(c.post(f"/api/projects/{pid}/proposals",
                                                json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"])
        yield c


def circuits(view):
    return next(ln["value"] for r in view["result"]["rules"] for ln in r["lines"] if ln["name"] == "circuits")


def test_changing_a_parameter_saves_a_new_rule_version_and_the_proposal_follows(client):
    v = client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]}).json()
    assert circuits(v) == 4 and v["rules_version"] == "v1.3"
    rules = client.get("/api/rules/LED").json()
    content = copy.deepcopy(rules["content"])
    next(p for p in content["params"] if p["name"] == "load_factor")["value"] = 0.4  # 8 A 可用 → 每回路 8 箱
    r = client.post("/api/rules/LED", json={"base_id": rules["id"], "reason": "按旧项目实测", "content": content})
    assert r.status_code == 201 and r.json()["version"] == "v1.4"
    v = client.get(client.base).json()
    f6 = next(x for x in v["result"]["rules"] if x["id"] == "F6")
    assert v["rules_version"] == "v1.4" and circuits(v) == 5 and f6["display"] == "5（带载 5 / 串接 4，取大）"
    old = client.post("/api/rules/LED/run", json={"inputs": SAMPLE["input"], "version_id": rules["id"]}).json()
    assert next(ln["value"] for x in old["rules"] for ln in x["lines"] if ln["name"] == "circuits") == 4


def test_upgrade_saves_new_led_rule_and_library_versions_and_keeps_user_edits(tmp_path):
    engine = make_engine(tmp_path / "avp.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0013")
    old = copy.deepcopy(LEGACY)
    next(p for p in old["params"] if p["name"] == "spare_module_ratio")["value"] = 0.07  # 用户改过的参数
    lib = copy.deepcopy(load_library("LED"))
    for p in lib["products"]:
        p.pop("cabinet_max", None)
    cols = lambda name: sa.table(name, sa.column("business_line"), sa.column("version"), sa.column("content", sa.JSON),  # noqa: E731
                                 sa.column("reason"), sa.column("created_at", sa.DateTime))
    with engine.begin() as conn:
        conn.execute(cols("rule_set_versions").insert().values(business_line="LED", version="v1.5", content=old,
                                                               reason="试用", created_at=sa.func.now()))
        conn.execute(cols("product_library_versions").insert().values(business_line="LED", version="v1.2", content=lib,
                                                                      reason="试用", created_at=sa.func.now()))
    migrate(engine)
    with engine.connect() as conn:
        sets = conn.execute(sa.text("select version, content, reason from rule_set_versions order by id")).all()
        libs = conn.execute(sa.text("select version, content from product_library_versions order by id")).all()
    assert [s.version for s in sets] == ["v1.5", "v1.6"] and "CR-10" in sets[1].reason
    assert json.loads(sets[0].content) == old  # 旧版本原样保留
    new = json.loads(sets[1].content)
    params = {p["name"]: p["value"] for p in new["params"]}
    assert "circuit_kw" not in params and params["px_per_data_cable"] == 655360 and params["mcb_a"] == 20
    assert params["spare_module_ratio"] == 0.07
    assert [r["id"] for r in new["rules"]][7:10] == ["F8", "W1", "F9"]
    validate(new, new)
    assert [l.version for l in libs] == ["v1.2", "v1.3"]
    ic25 = next(p for p in json.loads(libs[1].content)["products"] if p["id"] == "IC-25")
    assert ic25["cabinet_max"]["640x640"] == {"a": 0.96, "w": 200, "sample": False}
    out = calculate(new, json.loads(libs[1].content), SAMPLE["input"])
    assert next(ln["value"] for r in out["rules"] for ln in r["lines"] if ln["name"] == "circuits") == 4
