"""第 8 步验收（投影模板）：风险与假设的固定条款放进模板（界面可改、带版本，花括号填项目数据）；
投影的资料齐全度（平面图、立面图、剖面图、天花图）给出 A / B / C 级，不是 A 级时自动加一条条款，计算照常出；
投影方案书默认 A3 横向。升级时给已有服务器另存新的规则版本和模板版本。"""
import copy
import io

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.completeness import completeness
from app.db import MIGRATIONS, make_engine, migrate
from app.i18n import use
from app.main import create_app
from app.rules.engine import load_seed
from app.templates.content import load_seed as template_seed

PJ_RULES, PJ = load_seed("PJ")
_, LED = load_seed("LED")


def start(tmp_path, line="PJ", inputs=None):
    c = TestClient(create_app(tmp_path))
    c.__enter__()
    user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
    c.post("/api/session", json={"user_id": user["id"]})
    p = c.post("/api/projects", json={"name": "114 Showroom", "client": "Showroom", "business_line": line}).json()
    c.base = f"/api/proposals/{p['proposals'][0]['id']}"
    c.put(f"{c.base}/inputs", json={"inputs": inputs or (PJ if line == "PJ" else LED)["input"]})
    return c


def risks(c, lang="zh"):
    doc = Document(io.BytesIO(c.get(f"{c.base}/proposal.docx?lang={lang}").content))
    paras = [p.text for p in doc.paragraphs]
    head = "风险与假设" if lang == "zh" else "Risks and assumptions"
    i = paras.index(head)
    return paras[i + 1:paras.index(next(p for p in paras[i + 1:] if p.startswith(("附录", "Appendix"))))]


def test_grades():
    yes = {k: "yes" for k in ("doc_plan", "doc_elevation", "doc_section", "doc_rcp")}
    assert completeness({}) is None
    assert completeness(yes)["grade"] == "A"
    b = completeness(yes | {"doc_section": "no", "doc_rcp": "no"})
    assert b["grade"] == "B" and b["missing_drawings"] == "剖面图、天花图（RCP）" and b["affected_items"] == "天花高度、镜头高度、吊点位置"
    assert completeness(yes | {"doc_plan": "no"})["grade"] == "C"
    with use("en"):
        assert completeness(yes | {"doc_section": "no"})["missing_drawings"] == "section drawing"


def test_114_is_grade_b_and_gets_the_completeness_clause(tmp_path):
    c = start(tmp_path)
    v = c.get(c.base).json()
    assert v["completeness"]["grade"] == "B" and v["rev"]["status"] == "calculated"  # 计算照常出
    assert [d["name"] for d in v["input_defs"] if d["name"].startswith("doc_")] == ["doc_plan", "doc_elevation", "doc_section", "doc_rcp"]
    r = risks(c)
    assert r[:4] == [x["zh"].replace("{pixel_mm}", "2.33") for x in template_seed("PJ")["clauses"][:4]]
    assert "本方案未取得剖面图、天花图（RCP），天花高度、镜头高度、吊点位置按手填值计算，需现场复核后确认。" in r
    assert any("were calculated from values entered by hand" in x for x in risks(c, "en"))

    c.put(f"{c.base}/inputs", json={"inputs": PJ["input"] | {"doc_section": "yes", "doc_rcp": "yes"}})
    assert c.get(c.base).json()["completeness"]["grade"] == "A"
    assert not any("本方案未取得" in x for x in risks(c))


def test_clauses_are_edited_in_the_template_with_versions(tmp_path):
    c = start(tmp_path)
    t = c.get("/api/templates/PJ").json()
    assert t["content"]["page"] == "A3L" and [x["key"] for x in t["content"]["clauses"]][-1] == "completeness"
    content = copy.deepcopy(t["content"])
    content["clauses"][0]["zh"] = "融合带在暗场要现场校正（{projectors} 台）。"
    for bad, msg in ((dict(content["clauses"][0], zh="{nope}"), "nope"), (dict(content["clauses"][0], when="sometimes"), "always")):
        wrong = copy.deepcopy(content)
        wrong["clauses"][0] = bad
        r = c.post("/api/templates/PJ", json={"base_id": t["id"], "reason": "x", "content": wrong})
        assert r.status_code == 422 and msg in r.json()["detail"]
    r = c.post("/api/templates/PJ", json={"base_id": t["id"], "reason": "按公司写法", "content": content})
    assert r.status_code == 201 and r.json()["version"] == "v1.1"
    assert risks(c)[0] != "融合带在暗场要现场校正（5 台）。"  # 方案绑定建项时的模板版本，升级才换（CR-9）
    c.post(f"{c.base}/upgrade", json={"parts": ["template"]})
    assert risks(c)[0] == "融合带在暗场要现场校正（5 台）。"


def test_projection_proposal_is_a3_landscape_and_led_a4(tmp_path):
    for line, size in (("PJ", (1191, 842)), ("LED", (595, 842))):  # pt：A3 横向 420 × 297 mm、A4 竖向 210 × 297 mm
        c = start(tmp_path / line, line)
        box = PdfReader(io.BytesIO(c.get(f"{c.base}/proposal.pdf").content)).pages[0].mediabox
        assert abs(float(box.width) - size[0]) < 2 and abs(float(box.height) - size[1]) < 2, line
        c.__exit__(None, None, None)


def test_upgrade_adds_completeness_inputs_and_template_clauses(tmp_path):
    engine = make_engine(tmp_path / "avp.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0016")
    old_rules = copy.deepcopy(PJ_RULES)
    old_rules["inputs"] = [i for i in old_rules["inputs"] if not i["name"].startswith("doc_")]
    old_tpl = {k: v for k, v in template_seed("PJ").items() if k not in ("page", "clauses")}
    old_tpl["boq"] = dict(old_tpl["boq"], group="用户改过的组标题")
    cols = lambda name: sa.table(name, sa.column("business_line"), sa.column("version"), sa.column("content", sa.JSON),  # noqa: E731
                                 sa.column("reason"), sa.column("created_at", sa.DateTime))
    with engine.begin() as conn:
        conn.execute(cols("rule_set_versions").insert().values(business_line="PJ", version="v1.5", content=old_rules,
                                                               reason="试用", created_at=sa.func.now()))
        conn.execute(cols("template_versions").insert().values(business_line="PJ", version="v1.0", content=old_tpl,
                                                               reason="试用", created_at=sa.func.now()))
    migrate(engine)
    with engine.connect() as conn:
        rules = conn.execute(sa.text("select version, content from rule_set_versions order by id")).all()
        tpls = conn.execute(sa.text("select version, content from template_versions order by id")).all()
    import json
    assert [r.version for r in rules] == ["v1.5", "v1.6"]
    new = json.loads(rules[1].content)
    assert [i["name"] for i in new["inputs"]] == [i["name"] for i in PJ_RULES["inputs"]] and new["rules"] == old_rules["rules"]
    assert [t.version for t in tpls] == ["v1.0", "v1.1"]
    tpl = json.loads(tpls[1].content)
    assert tpl["boq"]["group"] == "用户改过的组标题" and tpl["page"] == "A3L" and len(tpl["clauses"]) == 5


def test_old_template_versions_keep_the_old_wording():
    """升级前锁定的 Rev 用的是没有条款的旧模板版本：风险与假设照旧，导出的文字不变。"""
    from app.proposal_doc import LEGACY_CLAUSES, clauses
    old = {k: v for k, v in template_seed("PJ").items() if k != "clauses"}
    assert clauses(old, "PJ", {}, completeness({"doc_section": "no"})) == [zh for zh, _ in LEGACY_CLAUSES["PJ"]]
