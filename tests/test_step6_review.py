"""第 6 步验收（审核关与 Rev 锁定）：提交审核时锁定，审核中 / 已批准的版本不再改；可以自审；退回要写原因；
锁定的 Rev 永远用锁定时的规则、产品库、模板版本，新版本出来也不变。
CR-9 起：只有正式版本能提交（草稿先在 05 / 06 保存）；提交过的版本再改自动开下一个草稿；再次提交替换还在等待的那条。"""
import copy

import pytest
from fastapi.testclient import TestClient

from conftest import count_grouping, official
from app.main import create_app
from app.rules.engine import load_seed

_, SAMPLE = load_seed("LED")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        count_grouping(c.app)  # 网线按箱数：Royal 3 个网口，SC-4 够用（见 conftest）
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


def test_a_draft_must_be_saved_as_an_official_version_before_submitting(client):
    calculated(client)
    r = client.post(f"{client.base}/submit")
    assert r.status_code == 409 and "草稿" in r.json()["detail"]
    v = official(client, client.base)
    assert v["flow"]["version"] == "v1" and not v["flow"]["dirty"] and v["revisions"][0]["saved_by"] == "Jimmy"
    assert client.post(f"{client.base}/submit").json()["rev"]["status"] == "review"


def test_submit_locks_the_version_and_edits_open_the_next_draft(client):
    calculated(client)
    official(client, client.base)
    v = client.post(f"{client.base}/submit").json()
    assert v["rev"]["status"] == "review" and v["flow"]["version"] == "v1 待审批"
    assert v["locked"]["rules_version"] == "v1.3" and v["locked"]["library_version"] == v["library_version"]
    assert [h["action"] for h in v["history"]] == ["saved", "submit"]
    for method, path, body in [
        ("PUT", "/inputs", {"inputs": SAMPLE["input"]}), ("POST", "/fill-from-files", None),
        ("PUT", "/overrides", {"values": {"circuits": 5}, "reason": "x"}), ("PUT", "/boq", {"rows": {}}),
        ("PUT", "/drawing", {"power": {}, "data": {}}), ("POST", "/confirm", {"field": "width_mm"}),
    ]:
        r = client.request(method, client.base + path, json=body)
        assert r.status_code == 200 and r.json()["rev"]["rev_no"] == 2, path  # 都改在自动开的 v2 草稿上
    first = client.get(f"{client.base}?rev=1").json()
    assert first["rev"]["status"] == "review" and first["readonly"] and first["overrides"] == []  # v1 不变
    assert [r["rev_no"] for r in client.get(client.base).json()["revisions"]] == [2, 1]
    assert client.post(f"{client.base}/submit").status_code == 409  # v2 是有改动的草稿


def test_blocked_draft_cannot_be_saved_or_submitted(client):
    calculated(client)
    official(client, client.base)
    client.put(f"{client.base}/drawing", json={"power": {"R3C1": 1, "R3C2": 1}, "data": {}})  # 回路 1 串 11 箱，超过上限
    v = client.get(client.base).json()
    assert any("超载" in b for b in v["blockers"]) and v["flow"]["gates"]["06"].startswith("1 个回路超出带载")
    r = client.post(f"{client.base}/next", json={"step": "06", "save": True})
    assert r.status_code == 409 and "超出带载" in r.json()["detail"]
    assert client.post(f"{client.base}/submit").status_code == 409


def test_self_approval_and_export_without_draft(client):
    calculated(client)
    assert "DRAFT" in client.get(f"{client.base}/drawing.svg").text
    official(client, client.base)
    client.post(f"{client.base}/submit")
    v = client.post(f"{client.base}/approve", json={"note": "自审"}).json()
    assert v["rev"]["status"] == "approved" and v["reviewer"] == "Jimmy" and v["reviewed_at"]
    assert [h["action"] for h in v["history"]] == ["saved", "submit", "approve"]
    assert v["flow"]["stage"] == 5 and v["flow"]["version"] == "v1 已批准"
    assert "DRAFT" not in client.get(f"{client.base}/drawing.svg").text
    assert client.post(f"{client.base}/approve", json={}).status_code == 409  # 已批准，没有在等审批的


def test_send_back_needs_a_reason_and_unlocks(client):
    calculated(client)
    official(client, client.base)
    client.post(f"{client.base}/submit")
    assert client.post(f"{client.base}/send-back", json={"note": " "}).status_code == 422
    v = client.post(f"{client.base}/send-back", json={"note": "回路要按列分"}).json()
    assert v["rev"]["status"] == "calculated" and v["locked"] is None and not v["readonly"]
    assert v["history"][-1]["action"] == "send_back" and v["history"][-1]["note"] == "回路要按列分"
    assert v["flow"]["version"] == "v1 已退回" and v["flow"]["reached"] == 3
    v = client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]}).json()
    assert v["rev"]["rev_no"] == 2  # 退回的 v1 不改，改在 v2 草稿上


def test_locked_rev_keeps_its_versions_and_the_next_draft_upgrades_by_hand(client):
    calculated(client)
    official(client, client.base)
    client.post(f"{client.base}/submit")
    client.post(f"{client.base}/approve", json={})

    # 批准之后规则另存新版本（每条电源线最多串接 6 箱）：已批准的 v1 不变
    rules = client.get("/api/rules/LED").json()
    content = copy.deepcopy(rules["content"])
    next(p for p in content["params"] if p["name"] == "chain_max")["value"] = 6
    assert client.post("/api/rules/LED", json={"base_id": rules["id"], "reason": "test", "content": content}).status_code == 201

    v = client.post(f"{client.base}/upgrade", json={"parts": ["rules"]}).json()  # 升级也是一次修改：自动开 v2 草稿
    assert v["flow"]["opened"] == 2 and v["rules_version"] == "v1.4" and v["flow"]["version"] == "v2（草稿）"
    old = client.get(f"{client.base}?rev=1").json()
    assert old["rules_version"] == "v1.3" and tile(old, "circuits") == 4 and old["snapshot_ok"]
    assert old["readonly"] and not old["viewing_latest"]

    new = client.get(client.base).json()
    assert new["rev"]["rev_no"] == 2 and new["rev"]["status"] == "calculated" and not new["readonly"]
    assert new["rev"]["inputs"] == old["rev"]["inputs"] and new["history"][0]["action"] == "created"
    assert [r["rev_no"] for r in new["revisions"]] == [2, 1]

    cmp = client.get(f"{client.base}/compare?a=1&b=2").json()
    assert {"item": "规则", "a": "v1.3", "b": "v1.4"} in cmp["versions"]
    assert cmp["inputs"] == []
    assert any(x["name"] == "circuits" and x["a"].startswith("4") and x["b"].startswith("6") for x in cmp["results"])
    assert any(x["a"] != x["b"] for x in cmp["boq"])


def test_resubmitting_replaces_the_version_waiting_for_approval(client):
    calculated(client)
    official(client, client.base)
    client.post(f"{client.base}/submit")
    client.put(f"{client.base}/overrides", json={"values": {"circuits": 5}, "reason": "现场每两列一个回路"})
    v = official(client, client.base)
    assert v["flow"]["version"] == "v2" and v["flow"]["stage"] == 4  # v1 还在等审批
    v = client.post(f"{client.base}/submit").json()
    assert v["rev"]["rev_no"] == 2 and v["rev"]["status"] == "review"
    first = client.get(f"{client.base}?rev=1").json()
    assert first["rev"]["status"] == "calculated" and first["locked"] is None
    assert first["history"][-1]["action"] == "replaced" and first["history"][-1]["note"] == "被 v2 替换"
    assert client.post(f"{client.base}/approve", json={}).json()["rev"]["rev_no"] == 2
