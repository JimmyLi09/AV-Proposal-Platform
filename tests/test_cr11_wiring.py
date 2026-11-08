"""CR-11 验收：W1 接线布置。方案配置页（推荐页）的接线图、图纸页、DXF、BOQ 用同一份 W1 结果，回路数、网口数处处一致；
手动改回路数（写原因）后 W1 按手动值分组；手动换箱体分组后图上跟着变、数量不变；标签不重叠，英文图里没有中文。"""
import io
import re

import ezdxf
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rules.engine import load_seed

_, SAMPLE = load_seed("LED")
CJK = re.compile(r"[　-〿一-鿿＀-￯]")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.base = "/api/proposals/" + str(c.post(f"/api/projects/{pid}/proposals",
                                                json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"])
        c.put(f"{c.base}/inputs", json={"inputs": SAMPLE["input"]})
        yield c


def value(view, name):
    return next(ln["value"] for r in view["result"]["rules"] for ln in r["lines"] if ln["name"] == name)


def runs(svg, layer):
    return len(re.findall(rf'<g class="{layer}"><polyline', svg))


def consistent(client):
    """推荐页（规则结果、接线图）、图纸、DXF、内部明细、客户版 BOQ 的回路数和网口数都一样。"""
    v = client.get(client.base).json()
    circuits, data_runs, d = value(v, "circuits"), value(v, "data_runs"), v["drawing"]
    svg = client.get(f"{client.base}/wiring.svg").text
    dxf = ezdxf.read(io.StringIO(client.get(f"{client.base}/drawing.dxf").content.decode("utf-8")))
    boq = {x["key"]: x for x in v["result"]["boq"]}
    assert len(d["circuits"]) == runs(svg, "layer-power") == circuits
    assert len(d["cables"]) == runs(svg, "layer-data") == len(dxf.modelspace().query('LWPOLYLINE[layer=="AVP-DATA"]')) == data_runs
    assert value(v, "power_group_sizes") == [len(c["path"]) for c in d["circuits"]] or d["manual"]["power"]
    assert boq["power_cable"]["qty"] == circuits + d["spare_circuits"] and boq["data_cable"]["qty"] == data_runs + d["spare_cables"]
    cabling = next(r for r in v["boq"]["rows"] if r["key"] == "power_cabling")
    assert f"MCB × {circuits} circuits" in cabling["specs"][0]
    return v, svg


def test_recommendation_wiring_drawing_dxf_and_boq_agree(client):
    v, svg = consistent(client)
    assert (value(v, "circuits"), value(v, "data_runs")) == (4, 5)
    # 回路标签在屏幕下方、网口标签在屏幕上方，平均分布不重叠
    labels = re.findall(r'<text x="([\d.]+)" y="([\d.]+)" font-size="11" text-anchor="middle" fill="[^"]+" font-weight="600">'
                        r'(回路|网口)', svg)
    power = sorted(float(x) for x, y, k in labels if k == "回路")
    data = sorted(float(x) for x, y, k in labels if k == "网口")
    assert len(power) == 4 and len(data) == 5
    assert {y for x, y, k in labels if k == "回路"} != {y for x, y, k in labels if k == "网口"}
    for xs in (power, data):
        gaps = [b - a for a, b in zip(xs, xs[1:])]
        assert max(gaps) - min(gaps) < 0.2 and min(gaps) > 100  # 等距，每个标签至少 100 px 宽
    assert "发送卡" in svg and "配电箱" in svg


def test_manual_circuits_regroup_everything(client):
    r = client.put(f"{client.base}/overrides", json={"values": {"circuits": 5}, "reason": "现场每两列一个回路"})
    assert r.status_code == 200
    v, _ = consistent(client)
    assert value(v, "circuits") == 5 and value(v, "power_group_sizes") == [7, 7, 7, 7, 7]


def test_moving_a_cabinet_changes_the_picture_not_the_counts(client):
    d = client.put(f"{client.base}/drawing", json={"power": {"R2C5": 1}, "data": {}}).json()["drawing"]
    assert "R2C5" in d["circuits"][0]["path"] and d["circuits"][0]["cabinets"] == 10
    v, svg = consistent(client)
    assert not v["drawing"]["blocked"]  # 10 箱 × 0.96 A = 9.6 A，没超载，也没超过串接上限
    d = client.put(f"{client.base}/drawing", json={"power": {"R2C5": 1, "R2C4": 1}, "data": {}}).json()["drawing"]
    assert d["blocked"] and d["circuits"][0]["over_chain"]  # 11 箱，超过串接上限：标红
    assert 'stroke="#A23A2A"' in client.get(f"{client.base}/wiring.svg").text


def test_english_wiring_diagram(client):
    svg = client.get(f"{client.base}/wiring.svg?lang=en").text
    assert "Sending card" in svg and "Circuit 1" in svg and not CJK.search(svg)
