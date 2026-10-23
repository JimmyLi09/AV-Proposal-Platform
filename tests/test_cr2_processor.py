"""CR-2 验收：处理器（含发送）优先，选到了就不再单独配控制器；信号源数量空着按 1 路算；
产品库里没有够用的型号时，从参考型号表给出建议型号（未入库），点一下加进产品库后重算。"""
import copy

import pytest
from fastapi.testclient import TestClient

from app.boq import build
from app.main import create_app
from app.products.library import load_reference, load_seed as load_library
from app.rules.engine import calculate, load_seed
from app.templates.content import load_seed as load_template

RULES, SAMPLE = load_seed("LED")
LIBRARY = load_library("LED")
EXAMPLE = {"environment": "indoor", "pixel_pitch_mm": 2.5, "width_mm": 6400, "height_mm": 3520,
           "installation": "wall", "maintenance": "front", "brightness_required_nits": 650,
           "viewing_distance_m": [4, 8]}  # 信号源数量空着


def by_id(out):
    return {r["id"]: r for r in out["rules"]}


def value(rule, name):
    return next(x["value"] for x in rule["lines"] if x["name"] == name)


def with_reference(library, *ids):
    lib = copy.deepcopy(library)
    lib["products"] += [p for p in load_reference("LED") if p["id"] in ids]
    return lib


def test_example_without_suitable_products_suggests_vx1000_and_vx16s():
    out = calculate(RULES, LIBRARY, EXAMPLE)
    r = by_id(out)
    assert value(r["F4"], "total_pixels") == 3_604_480 and value(r["F9"], "data_runs") == 7  # 3.60 MP，7 路 + 1 备用
    assert r["F11"]["check"] == "BLOCK" and "processor_id" not in {x["name"] for x in r["F13"]["lines"]}
    assert "按 1 路计算" in r["F13"]["note"]
    s = {x["model"]: (x["status"], x["reason"], x["load_pct"]) for x in out["suggestions"]}
    assert s == {"NovaStar VX400": ("no", "带载不够、网口不够", 139), "NovaStar VX600": ("no", "网口不够", 92),
                 "NovaStar VX1000": ("recommended", "", 55), "NovaStar VX16s": ("headroom", "", 35)}
    d = out["diagram"]
    assert d["chain"] == ["source", "processor", "screen"]  # 三个框
    assert d["nodes"]["processor"]["detail"] == "建议型号：NovaStar VX1000 / NovaStar VX16s（含发送，未入库）"


def test_example_after_adding_vx1000_uses_it_and_has_no_controller_line():
    out = calculate(RULES, with_reference(LIBRARY, "VX1000"), EXAMPLE)
    r = by_id(out)
    assert value(r["F13"], "processor") == "NovaStar VX1000" and value(r["F13"], "processor_sending") is True
    assert "55 %" in r["F13"]["trace"] and "7 路 ≤ 10 口" in r["F13"]["trace"]
    assert value(r["F11"], "controller_qty") == 0 and r["F11"]["check"] == "PASS"
    assert r["F11"]["display"] == "已包含在处理器 NovaStar VX1000 里"
    assert out["suggestions"] == []
    assert not [x for x in out["boq"] if x["rule"] == "F11"]  # 内部明细没有控制器
    d = out["diagram"]
    assert d["chain"] == ["source", "processor", "screen"] and d["unmatched"] == []
    assert d["nodes"]["processor"]["detail"] == "7 / 10 口 · 负载 55 %"
    assert [(x["from"], x["to"], x["cable"]) for x in d["links"][:2]] == [("source", "processor", "HDMI"), ("processor", "screen", "Cat6")]
    client = build(load_template("LED"), out["values"], None)
    assert [x["title"] for x in client["rows"]][:3] == [
        "P2.5 Indoor LED screen on wall 6400 × 3520 mm", "Video processor with sending",
        "Server PC set (includes monitor, wireless mouse and keyboard)"]  # 没有单独的控制器行
    assert client["rows"][1]["specs"] == ["NovaStar VX1000 · 1 input"]


def test_load_over_90_percent_is_noted():
    lib = copy.deepcopy(LIBRARY)
    lib["products"].append({"id": "T-1", "category": "processor", "brand": "Test", "model": "T-1", "status": "approved",
                            "scenes": ["indoor"], "sample": True, "sending": True, "capacity_px": 3_400_000, "ports": 8,
                            "inputs": 2, "max_px": None, "max_input_px": None, "datasheet": ""})
    out = calculate(RULES, lib, EXAMPLE | {"width_mm": 5760, "signal_sources": 1})  # 2304 × 1408 = 3.24 MP，95 %
    r = by_id(out)
    assert value(r["F13"], "processor") == "Test T-1" and r["F13"]["note"] == "负载超过 90 %，余量偏小"


def test_royal_plaza_with_an_integrated_processor_keeps_all_quantities():
    base = by_id(calculate(RULES, LIBRARY, SAMPLE["input"]))
    out = calculate(RULES, with_reference(LIBRARY, "VX400"), SAMPLE["input"])  # 2.6 MP，4 口：够 143 用
    r = by_id(out)
    for rid in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F12"):
        assert r[rid]["lines"] == base[rid]["lines"], rid
    assert value(r["F13"], "processor") == "NovaStar VX400" and value(r["F11"], "controller_qty") == 0
    assert out["diagram"]["chain"] == ["source", "processor", "screen"]
    titles = [x["title"] for x in build(load_template("LED"), out["values"], None)["rows"]]
    assert "Sending controller" not in titles and len(titles) == 6


def test_royal_plaza_with_only_standalone_controllers_is_unchanged():
    out = calculate(RULES, LIBRARY, SAMPLE["input"] | {"signal_sources": 1})
    r = by_id(out)
    assert value(r["F11"], "controller") == "Sample SC-4" and value(r["F13"], "processor") == "Sample SP-1"
    assert value(r["F13"], "processor_sending") is False and out["suggestions"] == []
    assert out["diagram"]["chain"] == ["source", "processor", "controller", "screen"]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "Showroom", "client": "Audax"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1", "business_line": "LED"}).json()["id"]
        yield c


def test_add_suggested_model_to_library_then_recalculate(client):
    v = client.put(f"/api/proposals/{client.proposal}/inputs", json={"inputs": EXAMPLE}).json()
    assert v["rev"]["status"] == "calculated"  # 信号源数量空着也能算
    assert [x["id"] for x in v["result"]["suggestions"] if x["status"] != "no"] == ["VX1000", "VX16s"]
    r = client.post("/api/products/LED/reference", json={"id": "VX1000"})
    assert r.status_code == 201 and r.json()["version"] == "v1.1" and "待核对规格书" in r.json()["reason"]
    added = next(p for p in r.json()["content"]["products"] if p["id"] == "VX1000")
    assert added["sample"] is True and added["sending"] is True
    assert client.post("/api/products/LED/reference", json={"id": "VX1000"}).status_code == 409
    assert client.post("/api/products/LED/reference", json={"id": "nope"}).status_code == 404
    v = client.get(f"/api/proposals/{client.proposal}").json()
    assert v["library_version"] == "v1.1" and v["result"]["suggestions"] == []
    rules = {x["id"]: x for x in v["result"]["rules"]}
    assert rules["F13"]["display"] == "1 × NovaStar VX1000"
    assert "Sending controller" not in [x["title"] for x in v["boq"]["rows"]]


def test_library_rejects_sending_processor_without_load_or_ports():
    from app.products.library import LibraryError, validate
    lib = with_reference(LIBRARY, "VX1000")
    validate(lib, "LED")
    del next(p for p in lib["products"] if p["id"] == "VX1000")["ports"]
    with pytest.raises(LibraryError, match="网口"):
        validate(lib, "LED")
