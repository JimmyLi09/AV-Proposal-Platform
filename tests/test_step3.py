"""第 3 步验收：推荐全部来自产品库；控制器带载不够时阻断。外加内部明细的数量来源（客户版 BOQ 见 test_cr6_boq.py）。"""
import copy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.products.library import LibraryError, load_seed as load_library, validate
from app.rules import led
from app.rules.engine import calculate, load_seed

RULES, SAMPLE = load_seed("LED")
LIBRARY = load_library("LED")
INPUT = SAMPLE["input"]  # 143-Royal Plaza LED-1


def product(library, pid):
    return next(p for p in library["products"] if p["id"] == pid)


def rules_by_id(out):
    return {r["id"]: r for r in out["rules"]}


# ---- 推荐 ----

def test_recommends_preferred_cabinet_matching_pitch_environment_maintenance():
    rec = led.recommend(INPUT, LIBRARY)
    assert rec["cabinet"]["id"] == "IC-25" and [c["id"] for c in rec["candidates"]] == ["IC-25"]
    assert led.recommend(INPUT | {"pixel_pitch_mm": 1.9}, LIBRARY)["cabinet"]["id"] == "IC-19"


def test_no_matching_cabinet_blocks_instead_of_inventing_one():
    rec = led.recommend(INPUT | {"environment": "outdoor"}, LIBRARY)
    assert rec["cabinet"] is None and "产品库里没有符合的箱体" in rec["block"]


def test_retired_products_are_never_recommended():
    library = copy.deepcopy(LIBRARY)
    product(library, "IC-25")["status"] = "retired"
    assert led.recommend(INPUT, library)["cabinet"] is None


def test_preferred_before_approved_and_model_can_be_changed():
    library = copy.deepcopy(LIBRARY)
    alt = copy.deepcopy(product(library, "IC-25")) | {"id": "IC-25B", "model": "IC-25B", "status": "approved"}
    library["products"].insert(0, alt)
    rec = led.recommend(INPUT, library)
    assert [c["id"] for c in rec["candidates"]] == ["IC-25", "IC-25B"]
    assert led.recommend(INPUT, library, "IC-25B")["cabinet"]["id"] == "IC-25B"
    assert led.recommend(INPUT, library, "OF-40")["cabinet"]["id"] == "IC-25"  # 不符合条件的型号不能选


def test_everything_recommended_comes_from_the_library():
    out = calculate(RULES, LIBRARY, INPUT)
    ids = {p["id"] for p in LIBRARY["products"]}
    r = rules_by_id(out)
    assert out["recommendation"]["cabinet"]["id"] in ids
    assert {r["F11"]["lines"][1]["value"], r["F13"]["lines"][1]["value"]} <= ids  # controller_id, processor_id
    for line in out["boq"]:
        if line["key"] and ":" in line["key"] and not line["key"].startswith("install:"):
            assert line["key"].split(":")[0] in ids


def test_controller_too_small_blocks():
    library = copy.deepcopy(LIBRARY)
    product(library, "SC-4")["capacity_px"] = 1_000_000  # SC-2 只有 1.3 MP，也不够 1.84 MP
    out = calculate(RULES, library, INPUT)
    assert rules_by_id(out)["F11"]["check"] == "BLOCK"
    assert not any(line["item"].startswith("Controller") for line in out["boq"])


# ---- 产品库校验 ----

@pytest.mark.parametrize("change", [
    lambda c: c["products"].append(copy.deepcopy(c["products"][0])),  # 编号重复
    lambda c: c["products"][0].update(status="maybe"),
    lambda c: c["products"][0].update(category="speaker"),
    lambda c: c["products"][0].update(brightness_nits=-1),
    lambda c: c["products"][0].update(cabinet_sizes_mm=[[640]]),
    lambda c: c["products"][0].update(model=" "),
])
def test_library_validation(change):
    content = copy.deepcopy(LIBRARY)
    change(content)
    with pytest.raises(LibraryError):
        validate(content, "LED")


# ---- 内部明细 ----


def test_boq_quantities_come_from_rules():
    lines = {(x["item"], x["model"]): (x["qty"], x["why"]) for x in calculate(RULES, LIBRARY, INPUT)["boq"]}
    assert lines == {
        ("LED cabinet 箱体 640 × 480", "IC-25"): (28, "主尺寸，F3"),
        ("LED cabinet 箱体 640 × 640", "IC-25"): (7, "F3"),
        ("Spare modules 备用模组 320 × 160", "IC-25"): (12, "F10"),
        ("Power supply 电源", "箱内"): (35, "每箱 1 个"),
        ("Receiving card 接收卡", "箱内"): (35, "每箱 1 张"),
        ("Spare PSU 备用电源", "IC-25"): (1, "F8"),
        ("Spare receiving card 备用接收卡", "IC-25"): (1, "F8"),
        ("Controller 控制器", "SC-4"): (1, "1.84 / 2.30 MP，F11"),
        ("Video processor 视频处理器", "SP-1"): (1, "1 路信号源，F13"),
        ("Power cable 电源线", "—"): (4, "3 回路 + 备用，F7"),
        ("DB box with MCB 配电箱（含 MCB）", "定制"): (1, "3 回路，F12"),
        ("Data cable 数据线", "Cat6"): (5, "4 路 + 备用，F9"),
        ("墙面支架 1 套（不含钢结构）", "—"): (1, "F16"),
    }


# ---- API 流程 ----

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"]
        yield c


def put_inputs(client, inputs, cabinet_id=None):
    r = client.put(f"/api/proposals/{client.proposal}/inputs", json={"inputs": inputs, "cabinet_id": cabinet_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_workspace_flow(client):
    v = client.get(f"/api/proposals/{client.proposal}").json()
    assert v["result"] is None and v["rules_version"] == "v1.3" and v["library_version"] == "v1.0"

    v = put_inputs(client, INPUT)
    assert v["rev"]["status"] == "calculated"
    assert v["result"]["recommendation"]["cabinet"]["id"] == "IC-25"
    assert len(v["boq"]["rows"]) == 7 and v["template_version"] == "v1.0"

    assert put_inputs(client, {k: x for k, x in INPUT.items() if k != "signal_sources"})["rev"]["status"] == "draft"
    bad = client.put(f"/api/proposals/{client.proposal}/inputs", json={"inputs": INPUT | {"module_w_mm": 300}})
    assert bad.status_code == 422  # 模组尺寸由产品库带出，不能手填


def test_library_edit_makes_new_version_and_controller_block(client):
    put_inputs(client, INPUT)
    lib = client.get("/api/products/LED").json()
    content = copy.deepcopy(lib["content"])
    product(content, "SC-4")["capacity_px"] = 1_000_000
    r = client.post("/api/products/LED", json={"base_id": lib["id"], "reason": "按规格书更正带载", "content": content})
    assert r.status_code == 201 and r.json()["version"] == "v1.1"
    v = client.get(f"/api/proposals/{client.proposal}").json()
    assert v["library_version"] == "v1.1"
    assert rules_by_id(v["result"])["F11"]["check"] == "BLOCK"

    stale = client.post("/api/products/LED", json={"base_id": lib["id"], "reason": "x", "content": content})
    assert stale.status_code == 409
    bad = copy.deepcopy(content)
    product(bad, "SC-2")["ports"] = 0
    latest = client.get("/api/products/LED").json()
    assert client.post("/api/products/LED", json={"base_id": latest["id"], "reason": "x", "content": bad}).status_code == 422
