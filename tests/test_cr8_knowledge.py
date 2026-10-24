"""CR-8 资料库：导入与复扫、全文搜索、学到的内容（采用 / 不采用 / 撤销）、以往项目与回归对比、相似项目。"""
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.i18n import stored, use
from app.main import create_app
from app.rules.engine import load_seed

KB = Path(__file__).parent / "fixtures" / "knowledge" / "kb"
CJK = re.compile(r"[　-〿一-鿿＀-￯]")
_, LED_SAMPLE = load_seed("LED")


def digests(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def c(tmp_path):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        shutil.rmtree(app.state.kb_dir)
        shutil.copytree(KB, app.state.kb_dir)
        user = client.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        client.post("/api/session", json={"user_id": user["id"]})
        client.app_state = app.state
        yield client


def scan(c) -> dict:
    assert c.post("/api/kb/scan").status_code == 202
    return c.get("/api/kb").json()


def items(c, kind=None, status="pending"):
    return [i for i in c.get(f"/api/kb/items?status={status}").json() if kind is None or i["kind"] == kind]


def versions(c) -> dict:
    return {path: len(c.get(f"/api/{path}/versions").json()) for path in
            ("products/LED", "products/PJ", "templates/LED", "templates/PJ", "rules/LED", "rules/PJ")}


def test_scan_reads_every_type_folder_without_touching_originals(c):
    before, libs = digests(c.app_state.kb_dir), versions(c)
    kb = scan(c)
    assert kb["last_scan"] | {"at": None, "by": None} == {"at": None, "by": None, "new": 11, "changed": 0, "removed": 0,
                                                          "failed": 0, "total": 11}
    assert {t["key"]: t["files"] for t in kb["types"]} == {"projects": 5, "specs": 3, "drawings": 1, "boq": 1, "templates": 1}
    assert kb["counts"] | {"pending": 0} == {"files": 11, "read": 11, "failed": 0, "pending": 0}
    assert digests(c.app_state.kb_dir) == before  # 原文件只读：不移动、不改名、不写入
    assert versions(c) == libs  # 学到的内容不直接改任何库，只是建议
    projects = {p["key"]: p for p in c.get("/api/kb/projects").json()}
    assert sorted(projects) == ["114 Showroom", "143-Royal Plaza", "GMC Virtual Office"]
    assert projects["143-Royal Plaza"]["standard"] == {"manual": False, "list": True, "by": None, "at": None}
    assert projects["143-Royal Plaza"]["project_no"] == "143" and projects["143-Royal Plaza"]["record"] is None

    # 复扫：没改过的文件不重读，待确认的内容不重复
    ids = [i["id"] for i in items(c)]
    assert scan(c)["last_scan"]["new"] == 0 and [i["id"] for i in items(c)] == ids


def test_spec_sheets_suggest_product_values_and_adopting_creates_a_new_library_version(c):
    scan(c)
    products = {i["model"]: i for i in items(c, "product")}
    assert sorted(products) == ["NovaStar VX1000", "Panasonic PT-BHZ611C"]  # 选型手册里有好几个型号，不认
    pj = products["Panasonic PT-BHZ611C"]
    assert pj["source"]["name"] == "PT-BHZ611C_datasheet.pdf" and pj["confidence"] == "medium"
    assert {f["name"]: (f["value"], f["current"], f["changed"]) for f in pj["fields"]} == {
        "lumens": (6000, 6000, False), "native_px_w": (1920, 1920, False), "native_px_h": (1200, 1200, False),
        "power_w": (460, 450, True), "weight_kg": (22.7, None, True), "noise_db": (37, None, True)}

    r = c.post(f"/api/kb/items/{pj['id']}/adopt").json()
    assert r["status"] == "adopted" and r["decided_by"] == "Jimmy" and r["result"] == {"target": "products", "version": "v1.1"}
    lib = c.get("/api/products/PJ").json()
    p = next(x for x in lib["content"]["products"] if x["id"] == "PT-BHZ611C")
    assert (p["power_w"], p["weight_kg"], p["noise_db"], p["datasheet"]) == (460, 22.7, 37, "PT-BHZ611C_datasheet.pdf")
    assert lib["reason"] == f"资料库 #{pj['id']}：更新 Panasonic PT-BHZ611C（按规格书 PT-BHZ611C_datasheet.pdf p.1）"
    with use("en"):
        assert stored(lib["reason"]).startswith(f"Knowledge base #{pj['id']}: updated Panasonic PT-BHZ611C (from datasheet")
    assert c.post(f"/api/kb/items/{pj['id']}/adopt").status_code == 409

    # 撤销：另存一个新版本改回原值，这条回到待确认
    r = c.post(f"/api/kb/items/{pj['id']}/undo").json()
    assert r["status"] == "pending"
    lib = c.get("/api/products/PJ").json()
    p = next(x for x in lib["content"]["products"] if x["id"] == "PT-BHZ611C")
    assert lib["version"] == "v1.2" and (p["power_w"], p["weight_kg"], p["datasheet"]) == (450, None, "")

    # 参考型号表里的 VX1000：采用 = 按规格书加进产品库
    vx = products["NovaStar VX1000"]
    assert vx["from_reference"] and [f["name"] for f in vx["fields"] if f["changed"]] == ["inputs"]
    c.post(f"/api/kb/items/{vx['id']}/adopt")
    added = next(x for x in c.get("/api/products/LED").json()["content"]["products"] if x["id"] == "VX1000")
    assert (added["capacity_px"], added["ports"], added["inputs"]) == (6500000, 10, 6)
    c.post(f"/api/kb/items/{vx['id']}/undo")
    assert all(x["id"] != "VX1000" for x in c.get("/api/products/LED").json()["content"]["products"])


def test_past_boq_wording_becomes_template_rows_with_names_instead_of_numbers(c):
    scan(c)
    rows = {i["original"]: i for i in items(c, "template")}
    # 模板里已有的写法（屏、处理器、钢结构）不出现；数量不是 1、也不按面积的接收卡不收；投影 BOQ 的写法和模板一样
    assert sorted(rows) == ["Content production (30 s loop video)", "P2.5 Curve LED screen on wall 6400 × 3600 mm",
                            "Training for operators"]
    curve = rows["P2.5 Curve LED screen on wall 6400 × 3600 mm"]
    assert curve["row"] == {"title": "P{pixel_pitch_mm} Curve LED screen {installation_label} {width_mm} × {height_mm} mm",
                            "specs": ["Overall dimension: {width_mm} × {height_mm} mm", "Curve radius R5000"],
                            "qty": "area_m2", "unit": "sqm", "source": "Discussion_Area_BOQ.xlsx · BOQ!8"}
    assert rows["Training for operators"]["row"]["qty"] == 1 and curve["location"] == "BOQ!8"

    r = c.post(f"/api/kb/items/{curve['id']}/adopt").json()
    assert r["result"] == {"target": "templates", "version": "v1.1"}
    template = c.get("/api/templates/LED").json()
    assert template["content"]["boq"]["rows"][-1]["key"] == "p_curve_led_screen"
    assert "加入一行" in template["reason"]
    c.post(f"/api/kb/items/{curve['id']}/undo")
    template = c.get("/api/templates/LED").json()
    assert template["version"] == "v1.2" and template["content"]["boq"]["rows"][-1]["key"] == "install"


def test_project_records_reference_projects_and_rule_comparison(c):
    scan(c)
    records = {i["key"]: i for i in items(c, "project")}
    assert sorted(records) == ["114 Showroom", "143-Royal Plaza", "GMC Virtual Office"]
    r143 = records["143-Royal Plaza"]["record"]
    assert r143["line"] == "LED" and r143["shape"] == "flat"
    assert r143["inputs"] == {k: v for k, v in LED_SAMPLE["input"].items() if k != "signal_sources"}
    assert r143["actual"] == {"area_m2": 11.47, "controller_qty": 1, "circuits": 4, "power_cables": 5, "data_runs": 4,
                              "data_cables": 5, "spare_modules": 12}
    assert records["GMC Virtual Office"]["record"]["shape"] == "U"
    pj = records["114 Showroom"]["record"]
    assert pj["line"] == "PJ" and pj["inputs"]["wall_width_mm"] == 18325 and pj["inputs"]["projector"] == "PT-BHZ611C"
    assert pj["actual"] == {"projectors": 5, "video_lines": 5, "control_lines": 5}
    assert items(c, "rule") == []  # 项目记录还没确认，不对比

    rules_before = versions(c)["rules/LED"]
    c.post(f"/api/kb/items/{records['143-Royal Plaza']['id']}/adopt")
    project = next(p for p in c.get("/api/kb/projects").json() if p["key"] == "143-Royal Plaza")
    assert project["record_version"] == 1 and project["record_by"] == "Jimmy"
    compare = {r["name"]: (r["rule_id"], r["rule"], r["actual"], r["match"]) for r in project["compare"]["rows"]}
    assert compare == {"area_m2": ("F1", 11.4688, 11.47, True), "circuits": ("F6", 3, 4, False),
                       "power_cables": ("F7", 4, 5, False), "data_runs": ("F9", 4, 4, True),
                       "data_cables": ("F9", 5, 5, True), "controller_qty": ("F11", 1, 1, True),
                       "spare_modules": ("F10", 12, 12, True)}
    diffs = {i["name"]: (i["rule_id"], i["rule_value"], i["actual"]) for i in items(c, "rule")}
    assert diffs == {"circuits": ("F6", 3, 4), "power_cables": ("F7", 4, 5)}

    # 规则参考只记录，不改规则
    f6 = next(i for i in items(c, "rule") if i["name"] == "circuits")
    assert (f6["source"]["name"], f6["location"]) == ("143_BOQ.xlsx", "BOQ!11")  # 来源写到 BOQ 的第几行
    c.post(f"/api/kb/items/{f6['id']}/adopt")
    assert versions(c)["rules/LED"] == rules_before
    refs = c.get("/api/kb/references/LED").json()
    assert [(r["rule_id"], r["key"], r["rule_value"], r["actual"]) for r in refs] == [("F6", "143-Royal Plaza", 3, 4)]

    # 页面上勾选标准答案：U 形的多面屏记录先不对比
    gmc = next(p for p in c.get("/api/kb/projects").json() if p["key"] == "GMC Virtual Office")
    c.post(f"/api/kb/items/{records['GMC Virtual Office']['id']}/adopt")
    gmc = c.put(f"/api/kb/projects/{gmc['id']}/standard", json={"standard": True}).json()
    assert gmc["standard"]["manual"] and gmc["standard"]["by"] == "Jimmy" and gmc["compare"]["skipped"]

    # 撤销项目记录：回到没有记录，规则对比的建议跟着消失（已采用的参考保留记录）
    c.post(f"/api/kb/items/{records['143-Royal Plaza']['id']}/undo")
    assert [i["name"] for i in items(c, "rule")] == []
    assert len(c.get("/api/kb/references/LED").json()) == 1


def test_search_finds_text_file_names_and_short_chinese_words(c):
    scan(c)
    hits = c.get("/api/kb/search", params={"q": "VX1000"}).json()
    assert {h["file"]["name"] for h in hits} == {"VX1000_Spec_EN.pdf", "Controller_Selection_Guide.pdf"}
    assert all(h["location"].startswith("p.") for h in hits) and "VX1000" in hits[0]["snippet"]
    assert [h["file"]["name"] for h in c.get("/api/kb/search", params={"q": "保修"}).json()] == ["Terms_and_Conditions.docx"]
    royal = c.get("/api/kb/search", params={"q": "royal 4480"}).json()
    assert {h["project"] for h in royal} == {"143-Royal Plaza"}
    assert c.get("/api/kb/search", params={"q": "VX1000", "doc_type": "boq"}).json() == []
    assert c.get("/api/kb/search", params={"q": "  "}).json() == []
    f = hits[0]["file"]
    assert c.get(f"/api/kb/files/{f['id']}").content == (c.app_state.kb_dir / f["rel_path"]).read_bytes()


def test_rescan_picks_up_changed_new_and_removed_files(c):
    scan(c)
    root = c.app_state.kb_dir
    vx = next(i for i in items(c, "product") if i["model"] == "NovaStar VX1000")
    (root / "规格书" / "VX1000_Spec_EN.pdf").unlink()
    shutil.copy(KB / "规格书" / "VX1000_Spec_EN.pdf", root / "规格书" / "VX1000 copy.pdf")
    kb = scan(c)
    assert {k: kb["last_scan"][k] for k in ("new", "changed", "removed")} == {"new": 1, "changed": 0, "removed": 1}
    names = [h["file"]["name"] for h in c.get("/api/kb/search", params={"q": "VX1000"}).json()]
    assert "VX1000_Spec_EN.pdf" not in names and "VX1000 copy.pdf" in names
    assert all(i["id"] != vx["id"] for i in items(c, "product"))  # 删掉的文件带出的待确认内容一起拿掉

    # 只勾选部分类型：没勾的类型不扫，已经读过的也不当作删掉
    c.put("/api/kb/types", json={"types": ["specs"]})
    kb = scan(c)
    assert kb["last_scan"]["total"] == 3 and kb["counts"]["files"] == 11
    assert [t["key"] for t in kb["types"] if t["enabled"]] == ["specs"]


def test_upload_saves_into_the_type_folder_without_overwriting(c):
    pdf = (KB / "规格书" / "VX1000_Spec_EN.pdf").read_bytes()
    up = lambda **form: c.post("/api/kb/upload", data=form, files=[("files", ("VX1000_Spec_EN.pdf", pdf))])  # noqa: E731
    assert up(doc_type="projects").status_code == 422  # 以往项目要写项目名
    assert up(doc_type="specs").status_code == 202
    assert up(doc_type="specs").status_code == 202
    root = c.app_state.kb_dir
    assert (root / "规格书" / "VX1000_Spec_EN (2).pdf").read_bytes() == pdf
    assert up(doc_type="projects", project="200-New Tower").status_code == 202
    assert (root / "以往项目" / "200-New Tower" / "VX1000_Spec_EN.pdf").exists()
    assert "200-New Tower" in [p["key"] for p in c.get("/api/kb/projects").json()]


def test_similar_past_projects_are_listed_when_confirming_inputs(c):
    scan(c)
    for i in items(c, "project"):
        c.post(f"/api/kb/items/{i['id']}/adopt")
    project = c.post("/api/projects", json={"name": "Royal Plaza Tower 2", "client": "Audax"}).json()["id"]
    pid = c.post(f"/api/projects/{project}/proposals", json={"name": "LED-1", "business_line": "LED"}).json()["id"]
    v = c.put(f"/api/proposals/{pid}/inputs", json={"inputs": LED_SAMPLE["input"]}).json()
    similar = v["similar"]
    assert [s["key"] for s in similar] == ["143-Royal Plaza", "GMC Virtual Office"]  # 投影项目不列
    top = similar[0]
    assert top["standard"] and top["score"] == 12.0
    assert [r["code"] for r in top["reasons"]] == ["area", "shape", "pitch_same", "same", "same", "word", "word"]
    assert top["reasons"][-2:] == [{"code": "word", "word": "Royal"}, {"code": "word", "word": "Plaza"}]
    assert similar[1]["reasons"][0] == {"code": "area", "mine": 11.47, "theirs": 23.96}


def test_english_view_of_the_knowledge_base(c):
    scan(c)
    h = {"X-Lang": "en"}
    for path in ("/api/kb/items", "/api/kb/projects", "/api/kb"):
        body = c.get(path, headers=h).json()
        # 文件名、资料库子文件夹名（规格书、以往项目…）、原文摘录和用户录入的内容不翻译
        for k in ("source", "files", "folder", "snippet", "failed"):
            for x in body if isinstance(body, list) else [body]:
                x.pop(k, None)
        if isinstance(body, dict):
            body["types"] = [t | {"folder": ""} for t in body["types"]]
        leaks = [s for s in json.dumps(body, ensure_ascii=False).split('"') if CJK.search(s)]
        assert leaks == [], path


def test_spec_patterns_read_chinese_and_english_datasheets():
    from app.knowledge.learn import norm_unit, placeholders, spec_values

    lines = [("p.1", "带载能力：650万像素"), ("p.1", "输出网口 10 个"), ("p.2", "Brightness 1,200 nits"),
             ("p.2", "Max. power consumption 480 W/m²"), ("p.3", "Throw ratio 0.50-0.60:1")]
    found = spec_values(lines, {"capacity_px", "ports", "brightness_nits", "max_power_w_m2", "throw_ratio", "throw_max"})
    assert {k: v[0] for k, v in found.items()} == {"capacity_px": 6500000, "ports": 10, "brightness_nits": 1200,
                                                   "max_power_w_m2": 480, "throw_ratio": 0.5, "throw_max": 0.6}
    assert found["capacity_px"][1] == "p.1" and found["throw_ratio"][1] == "p.3"
    assert [norm_unit(u) for u in ("SQM", "m²", "Lot", "L/S", "nos", "set", "box")] == \
        ["sqm", "sqm", "lot", "lot", "pcs", "set", None]
    assert placeholders("Outdoor LED screen hanging 6400 x 3200 mm", "LED") == \
        "{environment_label} LED screen {installation_label} {width_mm} × {height_mm} mm"


def test_a_broken_file_is_marked_failed_and_the_scan_goes_on(c):
    (c.app_state.kb_dir / "规格书" / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    kb = scan(c)
    assert kb["last_scan"]["failed"] == 1 and kb["counts"]["read"] == 11
    assert kb["failed"][0]["name"] == "broken.pdf" and kb["failed"][0]["note"].startswith("读取失败：")
    assert c.get("/api/kb", headers={"X-Lang": "en"}).json()["failed"][0]["note"].startswith("Read failed: ")
