"""CR-9 验收：流程对齐 PM Platform（工作台 + 01 → 07 一条线）。

- 用 143-Royal Plaza 走一遍：01 建项（不填编号）→ 02–04 确认，宽度 4500 吸附到 4480 → 05 改回路数必须写原因 →
  保存 v1 → 06 改一个 BOQ 数量 → 保存 v2 → 07 提交 → 自审批准 → 导出 PDF；再回 05 改一个值，自动出现 v3 草稿，已批准的不变。
- 工作台计数和进度与方案状态一致；售前接洽转正式项目后编号和文件都在。
- 04 改了确认值，05 不静默跟着变，提示重新带入 / 保留当前。
- 建项时绑定规则 / 产品库 / 模板版本，库更新不影响，手动升级才换。
"""
import copy
import json
import re

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.db import MIGRATIONS, make_engine, migrate
from app.main import create_app
from app.rules.engine import load_seed

_, SAMPLE = load_seed("LED")
CJK = re.compile(r"[　-〿一-鿿＀-￯]")


def start(tmp_path):
    c = TestClient(create_app(tmp_path))
    c.__enter__()
    user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
    c.post("/api/session", json={"user_id": user["id"]})
    return c


def new_project(c, **extra):
    """01 立项询价：项目资料 + 业务线，一次建好项目和第一个方案。"""
    body = {"name": "143-Royal Plaza Lobby LED", "client": "Royal Plaza", "location": "Singapore",
            "delivery": "2026-11-20", "notes": "大堂主屏", "business_line": "LED"} | extra
    p = c.post("/api/projects", json=body)
    assert p.status_code == 201, p.text
    return p.json(), f"/api/proposals/{p.json()['proposals'][0]['id']}"


def row(c, base):
    pid = int(base.rsplit("/", 1)[1])
    return next(r for r in c.get("/api/workbench").json()["rows"] if r["id"] == pid)


def value(v, name):
    return next(ln["value"] for r in v["result"]["rules"] for ln in r["lines"] if ln["name"] == name)


def step(v, key):
    return next(s for s in v["flow"]["steps"] if s["key"] == key)


def test_royal_plaza_end_to_end(tmp_path):
    c = start(tmp_path)
    project, base = new_project(c)
    assert project["project_no"] is None and project["proposals"][0]["name"] == "LED-1"
    r = row(c, base)
    assert r["lead"] and r["stage"] == 1 and r["version"] == "—" and r["updated_by"] == "Jimmy"

    # 02–04：宽度 4500 不是模组整数倍，不能往下走；选吸附值 4480 后可以
    v = c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"] | {"width_mm": 4500}}).json()
    assert v["flow"]["gates"]["02-04"] == "屏宽 4500 不是模组整数倍，先选吸附值"
    assert step(v, "05") == {"key": "05", "state": "lock", "note": "先完成 02–04", "why": v["flow"]["gates"]["02-04"]}
    r = c.post(f"{base}/next", json={"step": "02-04"})
    assert r.status_code == 409 and "吸附" in r.json()["detail"]
    c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"]})
    v = c.post(f"{base}/next", json={"step": "02-04"}).json()
    assert v["flow"]["reached"] == 2 and v["rev"]["rev_no"] == 1 and v["flow"]["pull"]["changed"] == []
    assert row(c, base)["stage"] == 2 and row(c, base)["version"] == "v1（草稿）"

    # 05：默认按行整行要 5 个网口，示例 SC-4 只有 4 口 → 不能往下走；把建议型号加进产品库、升级这个方案的产品库后可以
    assert v["flow"]["gates"]["05"].startswith("F11")
    assert c.post("/api/products/LED/reference", json={"id": "VX600"}).status_code == 201
    v = c.post(f"{base}/upgrade", json={"parts": ["library"]}).json()
    assert v["flow"]["gates"]["05"] == "" and v["library_version"] == "v1.1"
    assert c.put(f"{base}/overrides", json={"values": {"circuits": 5}, "reason": ""}).status_code == 422  # 改数量要写原因
    v = c.put(f"{base}/overrides", json={"values": {"circuits": 5}, "reason": "现场每两列一个回路"}).json()
    assert value(v, "circuits") == 5 and step(v, "05")["state"] == "draft"
    r = c.post(f"{base}/next", json={"step": "05"})
    assert r.status_code == 409 and "v1" in r.json()["detail"]  # 有改动：先弹窗保存为正式版本 v1
    assert v["flow"]["next_version"] == "v1"
    v = c.post(f"{base}/next", json={"step": "05", "save": True}).json()
    assert v["flow"]["version"] == "v1" and v["flow"]["reached"] == 3 and not v["flow"]["dirty"]
    assert row(c, base)["stage"] == 3

    # 06：改一个 BOQ 数量（写原因）→ 自动开 v2 草稿；点「下一步」保存为 v2
    key = v["boq"]["rows"][0]["key"]
    v = c.put(f"{base}/boq", json={"rows": {key: {"qty": 2, "reason": "两块屏"}}}).json()
    assert v["flow"]["opened"] == 2 and v["flow"]["version"] == "v2（草稿）" and v["flow"]["next_version"] == "v2"
    assert step(v, "06")["state"] == "draft" and row(c, base)["stage"] == 3
    v = c.post(f"{base}/next", json={"step": "06", "save": True}).json()
    assert v["flow"]["version"] == "v2" and v["flow"]["reached"] == 4 and row(c, base)["stage"] == 4

    # 07：提交 → 自审批准 → 导出 PDF（第一次导出存档，之后给同一份）
    v = c.post(f"{base}/submit").json()
    assert v["flow"]["version"] == "v2 待审批" and step(v, "07")["state"] == "pending"
    cmp = c.get(f"{base}/compare?a=1&b=2").json()
    assert any(x["a"] != x["b"] for x in cmp["boq"])  # 和上一版相比：BOQ 手动改动
    v = c.post(f"{base}/approve", json={"note": "自审"}).json()
    assert v["rev"]["status"] == "approved" and v["reviewer"] == "Jimmy" and step(v, "07")["state"] == "done"
    assert row(c, base)["stage"] == 5 and row(c, base)["version"] == "v2 已批准"
    pdf = c.get(f"{base}/proposal.pdf")
    assert pdf.status_code == 200 and "_DRAFT" not in pdf.headers["content-disposition"]
    assert c.get(f"{base}/proposal.pdf").content == pdf.content
    xlsx = c.get(f"{base}/boq.xlsx")
    assert c.get(f"{base}/boq.xlsx").content == xlsx.content
    assert {f["kind"] for f in c.get(base).json()["locked"]["files"]} == {"pdf", "boq"}

    # 再回 05 改一个值：自动开 v3 草稿，已批准的 v2 不变
    v = c.put(f"{base}/overrides", json={"values": {"circuits": 6}, "reason": "业主要多一路"}).json()
    assert v["flow"]["opened"] == 3 and v["flow"]["version"] == "v3（草稿）" and value(v, "circuits") == 6
    approved = c.get(f"{base}?rev=2").json()
    assert approved["rev"]["status"] == "approved" and value(approved, "circuits") == 5 and approved["snapshot_ok"]
    assert row(c, base)["stage"] == 3  # 有没保存的草稿：回到 05 / 06


def test_workbench_counts_follow_the_stage(tmp_path):
    c = start(tmp_path)
    _, inquiry = new_project(c, name="Phoenix Sea Office", delivery="")  # 立项信息不全、没传文件：立项中
    _, drawings = new_project(c, name="147-Senja Close")
    _, design = new_project(c, name="GMC")
    c.put(f"{design}/inputs", json={"inputs": SAMPLE["input"]})
    c.post(f"{design}/next", json={"step": "02-04"})
    wb = c.get("/api/workbench").json()
    assert wb["counts"] == [1, 1, 1, 0, 0]
    assert [r["stage"] for r in wb["rows"]] == [2, 1, 0]  # 新的在前
    v = c.get(inquiry).json()
    assert step(v, "01") == {"key": "01", "state": "draft", "note": "缺期望交付", "why": ""}


def test_lead_converts_to_a_project_and_keeps_its_files(tmp_path):
    c = start(tmp_path)
    project, base = new_project(c, name="新售前接洽")
    files = [("files", ("brief.txt", b"LED wall 4480 x 2560"))]
    assert c.post(f"/api/projects/{project['id']}/files", files=files).status_code == 201
    assert row(c, base)["lead"]
    r = c.patch(f"/api/projects/{project['id']}", json={"project_no": "P-2026-160"})
    assert r.status_code == 200 and r.json()["project_no"] == "P-2026-160"
    assert not row(c, base)["lead"] and row(c, base)["project_no"] == "P-2026-160"
    assert [f["filename"] for f in c.get(base).json()["files"]] == ["brief.txt"]


def test_04_changes_wait_for_pull_or_keep(tmp_path):
    c = start(tmp_path)
    _, base = new_project(c)
    c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"]})
    v = c.post(f"{base}/next", json={"step": "02-04"}).json()
    cabinets = value(v, "cabinets")

    # 04 改成 5120（8 列箱体）：05 不静默跟着变，提示「图纸校核有更新」
    v = c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"] | {"width_mm": 5120}}).json()
    assert value(v, "cabinets") == cabinets
    assert v["flow"]["pull"] == {"changed": [{"name": "width_mm", "label": "屏宽", "from": 4480, "to": 5120}], "ready": True}
    v = c.post(f"{base}/keep").json()  # 保留当前：04 改回 05 用的值
    assert v["rev"]["inputs"]["width_mm"] == 4480 and v["flow"]["pull"]["changed"] == []

    c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"] | {"width_mm": 5120}})
    v = c.post(f"{base}/pull").json()  # 重新带入
    assert value(v, "cabinets") > cabinets and v["flow"]["pull"]["changed"] == []

    v = c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"] | {"width_mm": 4500}}).json()
    assert not v["flow"]["pull"]["ready"] and c.post(f"{base}/pull").status_code == 409  # 先选吸附值才能带


def test_an_unchanged_draft_is_not_a_new_version(tmp_path):
    c = start(tmp_path)
    _, base = new_project(c)
    c.post("/api/products/LED/reference", json={"id": "VX600"})
    c.post(f"{base}/upgrade", json={"parts": ["library"]})
    c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"]})
    c.post(f"{base}/next", json={"step": "02-04"})
    c.post(f"{base}/next", json={"step": "05", "save": True})
    c.put(f"{base}/overrides", json={"values": {"circuits": 5}, "reason": "试一下"})
    v = c.put(f"{base}/overrides", json={"values": {"circuits": None}}).json()  # 改回规则值
    assert v["rev"]["rev_no"] == 2 and not v["flow"]["dirty"] and v["flow"]["version"] == "v1"
    v = c.post(f"{base}/next", json={"step": "06"}).json()
    assert [r["rev_no"] for r in v["revisions"]] == [1] and v["flow"]["reached"] == 4


def test_versions_are_bound_when_the_project_is_created(tmp_path):
    c = start(tmp_path)
    rules = c.get("/api/rules/LED").json()
    content = copy.deepcopy(rules["content"])
    next(p for p in content["params"] if p["name"] == "chain_max")["value"] = 6
    _, base = new_project(c)
    c.post("/api/rules/LED", json={"base_id": rules["id"], "reason": "test", "content": content})
    v = c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"]}).json()
    assert v["rules_version"] == "v1.3" and v["flow"]["upgrades"] == {"rules": "v1.4"}  # 库更新不影响已建的项目
    _, other = new_project(c, name="新项目")
    assert c.get(other).json()["rules_version"] == "v1.4"  # 新建的项目绑定最新版本


def test_english_flow_has_no_chinese(tmp_path):
    c = start(tmp_path)
    _, base = new_project(c, delivery="")
    c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"] | {"width_mm": 4500}})
    v = c.get(base, headers={"X-Lang": "en"}).json()
    assert v["flow"]["gates"]["02-04"] == "Screen width 4500 is not a module multiple: pick a snap value first"
    leaks = [s for s in json.dumps([v["flow"]["steps"], v["flow"]["version"]], ensure_ascii=False).split('"') if CJK.search(s)]
    assert leaks == []
    wb = c.get("/api/workbench", headers={"X-Lang": "en"}).json()
    assert not CJK.search(wb["rows"][0]["line_label"] + wb["rows"][0]["version"])


def test_upgrade_marks_old_revs_official_and_binds_versions(tmp_path):
    engine = make_engine(tmp_path / "avp.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0015")
        conn.execute(sa.text("insert into users (id, name, role, lang, created_at) values (1, 'Jimmy', 'PM', 'zh', '2026-11-01')"))
        conn.execute(sa.text("insert into projects (id, name, client, location, notes, owner_id, created_by, created_at) "
                             "values (1, 'Royal', 'Royal Plaza', '', '', 1, 1, '2026-11-01')"))
        conn.execute(sa.text("insert into proposals (id, project_id, name, business_line, mode, created_by, created_at) "
                             "values (1, 1, 'LED-1', 'LED', 'A', 1, '2026-11-01')"))
        locked = json.dumps({"rules_id": 1, "library_id": 1, "template_id": 1})
        conn.execute(sa.text("insert into revisions (proposal_id, rev_no, status, author_id, created_at, reviewed_at, locked) "
                             "values (1, 0, 'approved', 1, '2026-11-02', '2026-11-03', :l), "
                             "(1, 1, 'calculated', 1, '2026-11-04', null, null)"), {"l": locked})
    migrate(engine)  # 种子版本在 create_app 时才写入：这里没有，绑定留空 = 用最新
    with engine.connect() as conn:
        revs = conn.execute(sa.text("select rev_no, saved_at, saved_by, rules_id from revisions order by rev_no")).all()
        prop = conn.execute(sa.text("select reached, updated_by from proposals")).one()
    assert [(r.rev_no, r.saved_at is not None, r.saved_by, r.rules_id) for r in revs] == [(0, True, 1, 1), (1, False, None, None)]
    assert (prop.reached, prop.updated_by) == (4, 1)


def test_manual_overload_in_06_does_not_lock_06(tmp_path):
    """05 还没点过「下一步」就进了 06，在 06 手动换回路造成超载：06 不能被锁住（否则回到 05 也改不回来）。
    超载留在 06：标红、06 → 07 走不了、不能批准；在 06 改回后都恢复。参数造成的超载（05 改少回路数）照样挡 05 → 06。"""
    c = start(tmp_path)
    _, base = new_project(c)
    c.put(f"{base}/inputs", json={"inputs": SAMPLE["input"]})
    c.post(f"{base}/next", json={"step": "02-04"})
    c.post("/api/products/LED/reference", json={"id": "VX600"})
    v = c.post(f"{base}/upgrade", json={"parts": ["library"]}).json()
    assert v["flow"]["reached"] == 2 and v["flow"]["gates"]["05"] == "" and step(v, "06")["state"] == "todo"

    v = c.put(f"{base}/drawing", json={"power": {"R3C1": 1, "R3C2": 1}, "data": {}}).json()  # 回路 1 串 11 箱，超过上限
    assert v["drawing"]["blocked"] and v["flow"]["reached"] == 2
    assert v["flow"]["gates"]["05"] == "" and step(v, "06")["state"] != "lock"
    assert v["flow"]["gates"]["06"].startswith("1 个回路超出带载") and any("超载" in b for b in v["blockers"])
    v = c.put(f"{base}/drawing", json={}).json()  # 在 06 点「恢复自动」
    assert not v["drawing"]["blocked"] and v["flow"]["gates"]["06"] == ""

    v = c.put(f"{base}/overrides", json={"values": {"circuits": 2}, "reason": "试一下"}).json()  # 05 把回路数改少：自动分组就超载
    assert v["flow"]["gates"]["05"] == "2 个回路超出带载，加回路或改参数" and step(v, "06")["state"] == "lock"
