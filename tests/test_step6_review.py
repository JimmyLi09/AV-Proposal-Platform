"""第 6 步验收（审核关与 Rev 锁定）：提交审核时锁定，审核中 / 已批准都不能修改；可以自审；退回要写原因；
已批准的 Rev 要改就开新 Rev。锁定的 Rev 永远用锁定时的规则、产品库、模板版本，新版本出来也不变。"""
import copy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rules.engine import load_seed

_, SAMPLE = load_seed("LED")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"]
        c.base = f"/api/proposals/{c.proposal}"
        yield c


def calculated(client):
    v = client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]}).json()
    assert v["rev"]["status"] == "calculated" and v["blockers"] == []
    return v


def tile(v, name):
    return next(ln["value"] for r in v["result"]["rules"] for ln in r["lines"] if ln["name"] == name)


def test_cannot_submit_before_calculation(client):
    r = client.post(f"{client.base}/submit")
    assert r.status_code == 409
    assert client.get(client.base).json()["blockers"]


def test_submit_locks_the_rev_and_blocks_every_edit(client):
    calculated(client)
    v = client.post(f"{client.base}/submit").json()
    assert v["rev"]["status"] == "review" and v["readonly"]
    assert v["locked"]["rules_version"] == "v1.3" and v["locked"]["library_version"] == v["library_version"]
    assert [h["action"] for h in v["history"]] == ["submit"]
    for method, path, body in [
        ("PUT", "/inputs", {"inputs": SAMPLE["input"]}), ("POST", "/fill-from-files", None),
        ("PUT", "/overrides", {"values": {"circuits": 4}, "reason": "x"}), ("PUT", "/boq", {"rows": {}}),
        ("PUT", "/drawing", {"power": {}, "data": {}}), ("POST", "/confirm", {"field": "width_mm"}),
    ]:
        assert client.request(method, client.base + path, json=body).status_code == 409, path
    assert client.post(f"{client.base}/submit").status_code == 409  # 已经在审核中


def test_blocked_rev_cannot_be_submitted(client):
    calculated(client)
    client.put(f"{client.base}/drawing", json={"power": {"R1C7": 1, "R2C7": 1}, "data": {}})  # 回路 1 超载
    v = client.get(client.base).json()
    assert any("超载" in b for b in v["blockers"])
    r = client.post(f"{client.base}/submit")
    assert r.status_code == 409 and "超载" in r.json()["detail"]


def test_self_approval_and_export_without_draft(client):
    calculated(client)
    assert "DRAFT" in client.get(f"{client.base}/drawing.svg").text
    client.post(f"{client.base}/submit")
    v = client.post(f"{client.base}/approve", json={"note": "自审"}).json()
    assert v["rev"]["status"] == "approved" and v["reviewer"] == "Jimmy" and v["reviewed_at"]
    assert [h["action"] for h in v["history"]] == ["submit", "approve"]
    assert "DRAFT" not in client.get(f"{client.base}/drawing.svg").text
    assert client.post(f"{client.base}/approve", json={}).status_code == 409  # 已批准，不在审核中


def test_send_back_needs_a_reason_and_unlocks(client):
    calculated(client)
    client.post(f"{client.base}/submit")
    assert client.post(f"{client.base}/send-back", json={"note": " "}).status_code == 422
    v = client.post(f"{client.base}/send-back", json={"note": "回路要按列分"}).json()
    assert v["rev"]["status"] == "calculated" and v["locked"] is None and not v["readonly"]
    assert v["history"][-1]["action"] == "send_back" and v["history"][-1]["note"] == "回路要按列分"
    assert client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]}).status_code == 200


def test_locked_rev_keeps_its_versions_and_new_rev_uses_the_latest(client):
    calculated(client)
    client.post(f"{client.base}/submit")
    client.post(f"{client.base}/approve", json={})

    # 批准之后规则另存新版本（每根数据线带载改大）：已批准的 Rev 0 不变
    rules = client.get("/api/rules/LED").json()
    content = copy.deepcopy(rules["content"])
    next(p for p in content["params"] if p["name"] == "px_per_data_cable")["value"] = 716800
    assert client.post("/api/rules/LED", json={"base_id": rules["id"], "reason": "test", "content": content}).status_code == 201

    assert client.post(f"{client.base}/revisions").status_code == 201
    old = client.get(f"{client.base}?rev=0").json()  # 第一个 Rev 是 Rev 0
    assert old["rules_version"] == "v1.3" and tile(old, "data_cables") == 5 and old["snapshot_ok"]
    assert old["readonly"] and not old["viewing_latest"]

    new = client.get(client.base).json()
    assert new["rev"]["rev_no"] == 1 and new["rev"]["status"] == "calculated" and not new["readonly"]
    assert new["rev"]["inputs"] == old["rev"]["inputs"] and new["history"][0]["action"] == "created"
    assert [r["rev_no"] for r in new["revisions"]] == [1, 0]

    cmp = client.get(f"{client.base}/compare?a=0&b=1").json()
    assert {"item": "规则", "a": "v1.3", "b": "v1.4"} in cmp["versions"]
    assert cmp["inputs"] == []
    assert any(x["name"] == "data_cables" and x["a"].startswith("5") and x["b"].startswith("4") for x in cmp["results"])
    assert any(x["a"] != x["b"] for x in cmp["boq"])

    assert client.post(f"{client.base}/revisions").status_code == 409  # Rev 1 还没批准


def test_new_rev_only_from_approved(client):
    calculated(client)
    assert client.post(f"{client.base}/revisions").status_code == 409
