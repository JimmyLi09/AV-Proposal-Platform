"""CR-5 验收：推荐结果可以手动覆盖。改回路数不填原因不能保存；填了原因后 BOQ、示意图、图纸和导出 PDF 都用手动值并标「手动」；
恢复后回到规则值。规则结果本身不改（规则值另存），用到它的下游规则按手动值算（2026-10-23 Jimmy 选「下游跟着变」）。"""
import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import create_app
from app.products.library import load_seed as load_library
from app.rules.engine import calculate, load_seed

RULES, SAMPLE = load_seed("LED")
LIBRARY = load_library("LED")


def rule(out, rid):
    return next(r for r in out["rules"] if r["id"] == rid)


def line(out, name):
    return next(ln for r in out["rules"] for ln in r["lines"] if ln["name"] == name)


def test_manual_value_replaces_the_rule_value_and_flows_downstream():
    out = calculate(RULES, LIBRARY, SAMPLE["input"], overrides={"circuits": 4})
    f6 = line(out, "circuits")
    assert (f6["rule_value"], f6["value"], f6["manual"]) == (3, 4, True)
    assert rule(out, "F6")["manual"] == ["circuits"] and out["manual"] == ["circuits"]
    assert rule(out, "F6")["trace"] == "ceil(5.7344 / 2.5) = 3 → 手动 4"
    assert line(out, "power_cables")["value"] == 5 and rule(out, "F7")["trace"] == "4 + 1 = 5"  # 下游按手动值算
    assert "manual" not in line(out, "power_cables")
    boq = {x["key"]: x for x in out["boq"]}
    assert boq["power_cable"]["qty"] == 5 and not boq["power_cable"]["manual"]  # 由手动值算出来的，不算手动
    assert out["values"]["power_spares"] == 1
    plain = calculate(RULES, LIBRARY, SAMPLE["input"])
    assert line(plain, "circuits")["value"] == 3 and plain["manual"] == []  # 不带覆盖时还是规则值


def test_step_rule_output_can_be_overridden():
    out = calculate(RULES, LIBRARY, SAMPLE["input"], overrides={"controller_qty": 2})
    assert rule(out, "F11")["display"] == "2 × Sample SC-4" and "手动 controller_qty = 2" in rule(out, "F11")["trace"]
    assert next(x for x in out["boq"] if x["rule"] == "F11")["manual"]
    assert out["diagram"]["nodes"]["controller"]["manual"] and "手动" in out["diagram"]["svg"]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"]
        c.put(f"/api/proposals/{c.proposal}/inputs", json={"inputs": SAMPLE["input"]})
        yield c


def put(client, values, reason=""):
    return client.put(f"/api/proposals/{client.proposal}/overrides", json={"values": values, "reason": reason})


def test_override_needs_a_reason_and_is_listed_for_review(client):
    r = put(client, {"circuits": 4})
    assert r.status_code == 422 and r.json()["detail"] == "手动修改要写原因"
    assert put(client, {"area_m2": 12}, "x").status_code == 422  # 只能改推荐页卡片上的结果
    assert put(client, {"circuits": -1}, "x").status_code == 422
    v = put(client, {"circuits": 4}, "现场要求每列独立回路").json()
    [m] = v["overrides"]
    assert (m["rule"], m["rule_value"], m["value"], m["reason"], m["by"]) == ("F6", 3, 4, "现场要求每列独立回路", "Jimmy")
    assert m["at"]
    # 客户版 BOQ 用手动值
    cabling = next(r for r in v["boq"]["rows"] if r["key"] == "power_cabling")
    assert cabling["specs"] == ["DB box with MCB × 4 circuits",
                                "Power cables 4 + 1 spare, data cables CAT6 4 + 1 spare"]
    # 示意图、图纸用手动值并标手动
    power = next(x for x in v["result"]["diagram"]["links"] if x["boq"] == "power_cable")
    assert power["qty"] == "4 + 1 备用" and power["manual"]
    d = v["drawing"]
    assert next(b for b in d["basis"] if b["rule"] == "F6")["result"] == "4 路（手动）"
    assert {"check": "NOTE", "text": "图上整列分组是 3 路，F6 手动值是 4 路"} in d["checks"]


def test_manual_value_is_in_the_exported_pdf_and_restore_goes_back(client):
    put(client, {"circuits": 4}, "site request")
    pdf = client.get(f"/api/proposals/{client.proposal}/drawing.pdf?lang=en")
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "4 (manual)" in text
    v = put(client, {"circuits": None}).json()  # 恢复，不用写原因
    assert v["overrides"] == [] and line(v["result"], "circuits")["value"] == 3
    put(client, {"circuits": 4}, "site request")
    v = put(client, {"circuits": 3}, "改回").json()  # 改回规则值 = 恢复
    assert v["overrides"] == [] and v["drawing"]["checks"] == []


def test_client_boq_row_from_an_overridden_result_is_marked(client):
    v = put(client, {"controller_qty": 2}, "两台控制器做备份").json()
    row = next(r for r in v["boq"]["rows"] if r["key"] == "controller")
    assert row["qty"] == 2 and row["rule_manual"] and not row["manual"]
    assert not next(r for r in v["boq"]["rows"] if r["key"] == "led_screen")["rule_manual"]


def test_two_values_on_one_card(client):
    """分辨率卡片有宽、高两个值，用同一个原因一起改。"""
    v = put(client, {"res_x": 1800, "res_y": 1024}, "按控制器带载取整").json()
    assert [m["name"] for m in v["overrides"]] == ["res_x"]  # 高度和规则值一样，不算手动
    assert rule(v["result"], "F4")["display"] == "1800 × 1024"
    assert line(v["result"], "total_pixels")["value"] == 1800 * 1024  # 同一条规则里后面的结果也按手动值算
