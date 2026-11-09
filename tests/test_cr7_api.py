"""CR-7：投影方案和多面屏方案在页面接口上的行为（新建、录入、计算、客户版 BOQ、确认关、英文界面、升级）。"""
import copy
import io
import json
import re
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

from app.db import MIGRATIONS, make_engine, migrate
from app.main import create_app
from app.rules.engine import load_seed

SAMPLES = Path(__file__).parent / "fixtures" / "samples"
CASES = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
CJK = re.compile(r"[　-〿一-鿿＀-￯]")
LED_RULES, LED_SAMPLE = load_seed("LED")
_, PJ_SAMPLE = load_seed("PJ")


def start(tmp_path, line):
    c = TestClient(create_app(tmp_path))
    c.__enter__()
    user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
    c.post("/api/session", json={"user_id": user["id"]})
    c.project = c.post("/api/projects", json={"name": "CR-7", "client": "Audax"}).json()["id"]
    c.proposal = c.post(f"/api/projects/{c.project}/proposals", json={"name": "Wall-1", "business_line": line}).json()["id"]
    return c


def put_inputs(c, inputs):
    r = c.put(f"/api/proposals/{c.proposal}/inputs", json={"inputs": inputs})
    assert r.status_code == 200, r.text
    return r.json()


def test_projection_proposal_end_to_end(tmp_path):
    c = start(tmp_path, "PJ")
    v = put_inputs(c, PJ_SAMPLE["input"])
    assert v["rev"]["status"] == "calculated" and v["rules_version"] == "v1.5" and v["shapes"][0] == "single"
    rows = {r["key"]: r for r in v["boq"]["rows"]}
    assert rows["projector"]["title"] == "Panasonic PT-BHZ611C laser projector" and rows["projector"]["qty"] == 5
    assert rows["lens"]["qty"] == 5 and rows["blender"]["qty"] == 1 and rows["transmission"]["qty"] == 5
    assert rows["cabling"]["specs"] == ["Video 5 + 1 spare (HDBaseT)", "Control CAT6 5 + 1 spare"]
    assert v["result"]["diagram"]["unmatched"] == [] and v["drawing"] is None
    xlsx = load_workbook(io.BytesIO(c.get(f"/api/proposals/{c.proposal}/boq.xlsx").content))
    assert any(row[1] == "Content production" for row in xlsx.active.iter_rows(values_only=True))
    en = c.get(f"/api/proposals/{c.proposal}", headers={"X-Lang": "en"}).json()
    leaks = [s for s in json.dumps(en["result"]["rules"], ensure_ascii=False).split('"') if CJK.search(s)]
    assert leaks == []
    for path in ("/api/rules/PJ", "/api/products/PJ", "/api/templates/PJ"):
        assert c.get(path).status_code == 200


def test_conflicting_file_values_wait_for_confirmation_on_a_projection_proposal(tmp_path):
    """Phoenix Sea「正文 4 台、图注 6 台」：同一个字段几份文件读到的不一样，进确认关，确认前不能计算。"""
    c = start(tmp_path, "PJ")
    files = [("files", (n, (SAMPLES / n).read_bytes())) for n in ("Lobby_Elevation_RevB.pdf", "Lobby_site_photo.jpg")]
    assert c.post(f"/api/projects/{c.project}/files", files=files).status_code == 201
    v = c.post(f"/api/proposals/{c.proposal}/fill-from-files").json()
    assert "wall_width_mm" in v["pending"] and v["rev"]["input_meta"]["wall_width_mm"]["conflict"]
    assert v["rev"]["status"] == "confirming" and v["result"] is None


def gmc_inputs():
    i = CASES["led_gmc_u_shape"]["input"]
    faces = [{k: f[k] for k in ("id", "name", "orientation", "width_mm", "height_mm")} for f in i["faces"]]
    return {k: x for k, x in LED_SAMPLE["input"].items() if k not in ("width_mm", "height_mm")} | {
        "shape": "U", "faces": faces, "corners": i["corners"]}


def test_multiface_led_proposal(tmp_path):
    c = start(tmp_path, "LED")
    v = put_inputs(c, gmc_inputs())
    # 示例箱体 640 宽：B 面 8000 拼不出（F3 阻断），用到箱体数的规则（CR-10 起功率、回路、接线都按箱体算）缺数，方案停在草稿；
    # A、C 面照样按面算出：各 72 箱、8 路回路（串接上限 10 决定）
    missing = next(r for r in v["result"]["rules"] if r["id"] == "S3")["missing"]
    assert v["rev"]["status"] == "draft" and {"B · F6", "B · F8"} <= set(missing)
    assert [f["id"] for f in v["result"]["faces"]] == ["A", "B", "C"] and v["result"]["multi"]["totals"]["circuits"] == 16
    boq = v["boq"]
    assert [r["group"] for r in boq["rows"]][:1] == ["A · Left"]
    assert {r["group"] for r in boq["rows"]} == {"A · Left", "B · Main", "C · Right", "共用"}
    # 同型号备品按整屏合计（S3）：不在每面重复，只在共用组出一行；共用组的线缆备用数按面加总
    shared = [r for r in boq["rows"] if r["group"] == "共用"]
    assert [r["key"] for r in shared] == ["processor", "server_pc", "power_cabling", "pooled:led_screen"]
    assert shared[-1]["title"] == "Spares: 80 modules, 3 power supply, 3 receiving card"
    assert shared[2]["specs"][:2] == ["DB box with 20 A single-phase MCB × 16 circuits",
                                      "3-core 2.5 mm² power cable × 18 (16 + 2 spare)"]
    assert shared[2]["specs"][3] == "CAT6 data cable × 18 (16 + 2 spare)"
    assert not any(s.startswith("Spares") for r in boq["rows"] if r["group"] != "共用" for s in r["specs"])
    # 视频处理器整屏 1 台（S5），只在共用组；每面不再各有一行处理器
    assert not any(r["key"].endswith(":processor") for r in boq["rows"])
    # 和单屏一样能改：按面的行改数量要写原因、标「手动」；手动添加的行放在共用组；导出照改过的出
    url = f"/api/proposals/{c.proposal}/boq"
    assert c.put(url, json={"rows": {"A:led_screen": {"qty": 24}}}).status_code == 422
    boq = c.put(url, json={"rows": {"A:led_screen": {"qty": 24, "reason": "按现场复尺"},
                                    "C:structure": {"specs": ["Hot-dip galvanised frame"]}},
                           "added": [{"title": "Cable trunking", "specs": [], "qty": 1, "unit": "lot"}]}).json()["boq"]
    rows = {r["key"]: r for r in boq["rows"]}
    assert rows["A:led_screen"]["qty"] == 24 and rows["A:led_screen"]["rule_qty"] == 23.96 and rows["A:led_screen"]["manual"]
    assert rows["C:structure"]["specs"] == ["Hot-dip galvanised frame"] and rows["C:led_screen"]["qty"] == 23.96
    assert boq["rows"][-1]["title"] == "Cable trunking" and boq["rows"][-1]["group"] == "共用"
    assert [m["key"] for m in boq["manual"]] == ["A:led_screen", "x1"]
    rows = list(load_workbook(io.BytesIO(c.get(f"{url}.xlsx").content)).active.iter_rows(values_only=True))
    assert (None, "B · Main", None, None) in rows and (len(boq["rows"]), "Cable trunking", 1, "lot") in rows
    assert (None, "- Hot-dip galvanised frame", None, None) in rows
    assert v["result"]["diagram"] is None and v["drawing"] is None  # B 面算不出箱体数：没有示意图；图纸下一步做
    en = c.get(f"/api/proposals/{c.proposal}", headers={"X-Lang": "en"}).json()["result"]
    leaks = [s for s in json.dumps([en["rules"], en["multi"]], ensure_ascii=False).split('"') if CJK.search(s)]
    assert leaks == []

    conflict = gmc_inputs()
    conflict["faces"][0] |= {"width_mm": None, "width_sources": [{"src": "平面图", "kind": "plan", "value": 5600},
                                                                 {"src": "LED 立面图", "kind": "elevation", "value": 5760}]}
    v = put_inputs(c, conflict)
    assert v["rev"]["status"] == "confirming" and v["result"]["multi"]["conflicts"][0]["face"] == "A"


def test_upgrade_adds_the_s5_output_limit_as_a_new_rule_version(tmp_path):
    engine = make_engine(tmp_path / "avp.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0009")
    old = copy.deepcopy(LED_RULES)
    old["params"] = [p for p in old["params"] if p["name"] != "output_max_px_w"]
    sets = sa.table("rule_set_versions", sa.column("business_line"), sa.column("version"),
                    sa.column("content", sa.JSON), sa.column("reason"), sa.column("created_at", sa.DateTime))
    with engine.begin() as conn:
        conn.execute(sets.insert().values(business_line="LED", version="v1.4", content=old, reason="试用",
                                          created_at=sa.func.now()))
    migrate(engine)
    with engine.connect() as conn:
        rows = conn.execute(sa.text("select version, content, reason from rule_set_versions order by id")).all()
    assert [r.version for r in rows] == ["v1.4", "v1.5"] and "CR-7" in rows[1].reason
    new = json.loads(rows[1].content)
    assert new["rules"] == old["rules"] and new["params"][-1]["name"] == "output_max_px_w"


def gmc_library(c):
    """示例产品库拼不出 GMC：箱体改成 320 宽（尺寸资料里没有，只为让 5760 / 8000 能拼），加 16 口控制器、4 路输出的处理器。"""
    lib = c.get("/api/products/LED").json()
    content = lib["content"]
    cab = next(p for p in content["products"] if p["id"] == "IC-25")
    cab["cabinet_sizes_mm"] = [[320, 640], [320, 480]]
    cab["cabinet_max"] = {"320x640": {"a": 0.48, "w": 100, "sample": True}, "320x480": {"a": 0.48, "w": 60, "sample": True}}
    common = {"brand": "Sample", "status": "approved", "scenes": ["indoor"], "sample": True, "datasheet": ""}
    content["products"] += [common | {"id": "SC-16", "category": "controller", "model": "SC-16", "capacity_px": 10_400_000, "ports": 16},
                            common | {"id": "SP-8", "category": "processor", "model": "SP-8", "inputs": 4, "max_px": 13_500_000,
                                      "outputs": 4}]
    assert c.post("/api/products/LED", json={"base_id": lib["id"], "reason": "GMC", "content": content}).status_code == 201
    assert c.post(f"/api/proposals/{c.proposal}/upgrade", json={"parts": ["library"]}).status_code == 200


def test_multiface_led_diagram_in_the_proposal(tmp_path):
    c = start(tmp_path, "LED")
    gmc_library(c)
    v = put_inputs(c, gmc_inputs())
    assert v["rev"]["status"] == "calculated"
    d = v["result"]["diagram"]
    assert d["unmatched"] == [] and [r["id"] for r in d["faces"]] == ["A", "B", "C"]
    assert d["nodes"]["processor"]["model"] == "SP-8" and d["nodes"]["B:controller"]["model"] == "SC-16"
    doc = Document(io.BytesIO(c.get(f"/api/proposals/{c.proposal}/proposal.docx").content))
    assert "系统图（Level 1）" in [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    texts = [cell.text for t in doc.tables for row in t.rows for cell in row.cells]
    assert "控制器 B" in texts and "配电箱 C" in texts and "LED 屏 A · Left" in texts
    prs = Presentation(io.BytesIO(c.get(f"/api/proposals/{c.proposal}/proposal.pptx").content))
    assert any(sh.has_text_frame and sh.text_frame.text == "System diagram" for s in prs.slides for sh in s.shapes)
    en = c.get(f"/api/proposals/{c.proposal}", headers={"X-Lang": "en"}).json()["result"]["diagram"]
    assert not CJK.search(en["svg"].replace("Wall-1", "")) and en["nodes"]["A:db_box"]["title"] == "DB box A"
