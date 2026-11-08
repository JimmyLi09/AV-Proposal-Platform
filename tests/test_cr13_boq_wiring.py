"""CR-13 验收：客户版 BOQ「Power distribution and cabling」一行的规格子行由 W1 和 F6 / F7 / F9 自动生成（空开、线径、
电源线、跳线根数和长度、网线），数量仍是 1 lot、不含价格；手动改回路后子行跟着变；锁定的 Rev 不变；升级时只换没改过的写法。"""
import copy
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.boq import build
from app.db import MIGRATIONS, make_engine, migrate
from app.main import create_app
from app.products.library import load_seed as load_library
from app.rules.engine import calculate, load_seed
from app.templates.content import load_seed as load_template

CASES = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
RULES, SAMPLE = load_seed("LED")
OLD_SPECS = ["DB box with MCB × {circuits} circuits",
             "Power cables {circuits} + {power_spares} spare, data cables CAT6 {data_runs} + {data_spares} spare"]


def cabling(boq):
    return next(r for r in boq["rows"] if r["key"] == "power_cabling")


def test_28_cabinet_case_matches_the_change_order_example():
    case = CASES["led_wiring_28_cabinets"]
    lib = copy.deepcopy(load_library("LED"))
    next(p for p in lib["products"] if p["id"] == "IC-25")["cabinet_sizes_mm"] = case["input"]["cabinet_sizes_mm"]
    out = calculate(RULES, lib, SAMPLE["input"])
    row = cabling(build(load_template("LED"), out["values"], None))
    assert row["specs"] == case["expect"]["boq_power_cabling_specs"]
    assert (row["qty"], row["unit"]) == (1, "lot") and row["source"] == "F6 / F7 / F9 / F12 / W1"


def test_spec_lines_follow_parameters():
    content = copy.deepcopy(RULES)
    next(p for p in content["params"] if p["name"] == "power_cable_mm2")["value"] = 4
    next(p for p in content["params"] if p["name"] == "mcb_a")["value"] = 16
    out = calculate(content, load_library("LED"), SAMPLE["input"])
    specs = cabling(build(load_template("LED"), out["values"], None))["specs"]
    assert specs[0].startswith("DB box with 16 A single-phase MCB") and specs[1].startswith("3-core 4 mm² power cable")


def test_manual_circuits_and_locked_rev(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143", "client": "Royal Plaza"}).json()["id"]
        base = "/api/proposals/" + str(c.post(f"/api/projects/{pid}/proposals",
                                              json={"name": "LED-1", "business_line": "LED"}).json()["id"])
        v = c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"]}).json()
        assert cabling(v["boq"])["specs"][2] == "Power jumper cables between cabinets × 31 (≈ 19.3 m)"
        v = c.put(f"{base}/overrides", json={"values": {"circuits": 5}, "reason": "现场要求"}).json()
        specs = cabling(v["boq"])["specs"]
        assert specs[0] == "DB box with 20 A single-phase MCB × 5 circuits" and specs[1].endswith("× 6 (5 + 1 spare)")
        assert specs[2] == "Power jumper cables between cabinets × 30 (≈ 19.2 m)"


def test_upgrade_replaces_only_the_unchanged_wording(tmp_path):
    engine = make_engine(tmp_path / "avp.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0014")
    old = copy.deepcopy(load_template("LED"))
    cabling(old["boq"])["specs"] = OLD_SPECS
    cabling(old["boq"])["source"] = "F6 / F7 / F9 / F12"
    t = sa.table("template_versions", sa.column("business_line"), sa.column("version"), sa.column("content", sa.JSON),
                 sa.column("reason"), sa.column("created_at", sa.DateTime))
    with engine.begin() as conn:
        conn.execute(t.insert().values(business_line="LED", version="v1.2", content=old, reason="试用", created_at=sa.func.now()))
    migrate(engine)
    with engine.connect() as conn:
        rows = conn.execute(sa.text("select version, content, reason from template_versions order by id")).all()
    assert [r.version for r in rows] == ["v1.2", "v1.3"] and "CR-13" in rows[1].reason
    assert cabling(json.loads(rows[1].content)["boq"])["specs"] == cabling(load_template("LED")["boq"])["specs"]
    assert json.loads(rows[0].content) == old  # 旧版本不改

    # 用户改过写法的模板：不动
    engine2 = make_engine(tmp_path / "b.db")
    with engine2.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0014")
    custom = copy.deepcopy(old)
    cabling(custom["boq"])["specs"] = ["Our own wording × {circuits}"]
    with engine2.begin() as conn:
        conn.execute(t.insert().values(business_line="LED", version="v1.2", content=custom, reason="x", created_at=sa.func.now()))
    migrate(engine2)
    with engine2.connect() as conn:
        assert conn.execute(sa.text("select count(*) from template_versions")).scalar() == 1
