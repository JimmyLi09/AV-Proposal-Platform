"""第 2 步验收：规则可编辑、带版本（另存新版本，旧版本不变），结果可展开算式。"""
import copy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        c.data_dir = tmp_path
        yield c


def login(client):
    user = client.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
    client.post("/api/session", json={"user_id": user["id"]})


def sample(client):
    return client.get("/api/rules/LED/sample").json()["input"]


def rule(out, rule_id):
    return next(r for r in out["rules"] if r["id"] == rule_id)


def with_param(content, name, value):
    content = copy.deepcopy(content)
    next(p for p in content["params"] if p["name"] == name)["value"] = value
    return content


def test_seeded_v13_runs_with_expandable_formulas(client):
    v = client.get("/api/rules/LED").json()
    assert v["version"] == "v1.3" and len(v["content"]["rules"]) == 16
    out = client.post("/api/rules/LED/run", json={"inputs": sample(client)}).json()
    f9 = rule(out, "F9")
    assert f9["display"] == "5 根"
    assert f9["trace"] == "ceil(1,835,008 / 560,000) = 4；4 + 1 = 5"
    assert [p["name"] for p in f9["params"]] == ["px_per_data_cable", "spare_data_cables"]


def test_save_creates_new_version_and_keeps_old(client):
    login(client)
    v13 = client.get("/api/rules/LED").json()
    content = with_param(v13["content"], "px_per_data_cable", 716800)
    r = client.post("/api/rules/LED", json={"base_id": v13["id"], "reason": "C1：按图纸 71.68 万", "content": content})
    assert r.status_code == 201, r.text
    v14 = r.json()
    assert v14["version"] == "v1.4" and v14["created_by"] == "Jimmy"

    inputs = sample(client)
    latest = client.post("/api/rules/LED/run", json={"inputs": inputs}).json()
    old = client.post("/api/rules/LED/run", json={"inputs": inputs, "version_id": v13["id"]}).json()
    assert rule(latest, "F9")["display"] == "4 根"
    assert rule(old, "F9")["display"] == "5 根"  # 旧版本原样保留
    assert [x["version"] for x in client.get("/api/rules/LED/versions").json()] == ["v1.4", "v1.3"]
    assert client.get(f"/api/rules/LED/versions/{v13['id']}").json()["content"] == v13["content"]


def test_try_unsaved_changes_without_saving(client):
    v13 = client.get("/api/rules/LED").json()
    draft = with_param(v13["content"], "px_per_data_cable", 716800)
    out = client.post("/api/rules/LED/run", json={"inputs": sample(client), "content": draft}).json()
    assert rule(out, "F9")["display"] == "4 根"
    assert len(client.get("/api/rules/LED/versions").json()) == 1


def test_save_rejections(client):
    v13 = client.get("/api/rules/LED").json()
    changed = with_param(v13["content"], "circuit_kw", 3)
    body = {"base_id": v13["id"], "reason": "test", "content": changed}
    assert client.post("/api/rules/LED", json=body).status_code == 401  # 要先选名字

    login(client)
    bad = copy.deepcopy(v13["content"])
    bad["rules"][0]["outputs"][0]["cases"][0]["expr"] = "__import__('os').system('x')"
    assert client.post("/api/rules/LED", json=body | {"content": bad}).status_code == 422
    assert client.post("/api/rules/LED", json=body | {"content": v13["content"]}).status_code == 422  # 没有修改
    assert client.post("/api/rules/LED", json=body).status_code == 201
    assert client.post("/api/rules/LED", json=body).status_code == 409  # 基于旧版本
    assert len(client.get("/api/rules/LED/versions").json()) == 2


def test_restart_keeps_versions_and_does_not_reseed(client):
    login(client)
    v13 = client.get("/api/rules/LED").json()
    client.post("/api/rules/LED", json={"base_id": v13["id"], "reason": "x",
                                        "content": with_param(v13["content"], "circuit_kw", 3)})
    with TestClient(create_app(client.data_dir)) as again:
        assert [x["version"] for x in again.get("/api/rules/LED/versions").json()] == ["v1.4", "v1.3"]


def test_unknown_business_line(client):
    assert client.get("/api/rules/CCTV").status_code == 404
