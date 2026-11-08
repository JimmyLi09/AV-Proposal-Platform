"""第 6 步验收（方案演示稿 PPT）：16:9，文字和表格是原生可编辑对象；封面字段可改、随 Rev 保存；封面和最后一页固定，
其余可以勾掉；每页页眉页脚和页码；没批准带 DRAFT 水印；可选英文、中文或中英双语；可用公司 .potx 母版。"""
import io
import shutil

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.util import Emu

from conftest import count_grouping
from app.main import create_app
from app.rules.engine import load_seed

_, SAMPLE = load_seed("LED")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        count_grouping(c.app)  # 网线按箱数：Royal 3 个网口，SC-4 够用（见 conftest）
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza", "location": "Lobby",
                                            "project_no": "143"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"]
        c.base = f"/api/proposals/{c.proposal}"
        c.put(f"{c.base}/inputs", json={"inputs": SAMPLE["input"]})
        c.app_state = c.app.state
        yield c


def texts(slide):
    out = []
    for sh in slide.shapes:
        if sh.has_text_frame:
            out.append(sh.text_frame.text)
        if sh.has_table:
            out += [c.text for row in sh.table.rows for c in row.cells]
    return out


def deck(client, lang="en"):
    r = client.get(f"{client.base}/proposal.pptx?lang={lang}")
    assert r.status_code == 200, r.text
    return Presentation(io.BytesIO(r.content)), r


def test_draft_deck_is_16_9_with_editable_text_and_tables(client):
    prs, r = deck(client)
    assert "_DRAFT.pptx" in r.headers["content-disposition"]
    assert (prs.slide_width, prs.slide_height) == (Emu(12192000), Emu(6858000))
    assert len(prs.slides) == 9  # LED：封面、概况、配置、系统图、示意图 L2、图纸、BOQ、风险、下一步（没有标注副本 → 不出标注页）
    cover = texts(prs.slides[0])
    assert "Proposal · LED-1 Lobby" in cover and any("143-Royal Plaza LED · 143" in t for t in cover)
    for i, slide in enumerate(prs.slides, 1):
        t = texts(slide)
        assert "DRAFT" in t and str(i) in t and any(x.startswith("Confidential · Rev 0") for x in t)
    boq = texts(prs.slides[6])
    assert "Quantities and BOQ" in boq and any(x.startswith("P2.5 Indoor LED screen on wall") for x in boq)
    assert any(sh.has_table for sh in prs.slides[2].shapes)  # 配置是原生表格
    assert prs.core_properties.subject.endswith("DRAFT")


def test_cover_and_slides_are_saved_with_the_rev(client):
    v = client.get(client.base).json()["deck"]
    assert [s["key"] for s in v["slides"]][:3] == ["cover", "overview", "config"]
    assert client.put(f"{client.base}/deck", json={"off": ["cover"]}).status_code == 422  # 封面固定
    v = client.put(f"{client.base}/deck", json={"cover": {"title": "Lobby LED Wall"}, "off": ["schematic", "risks"]}).json()["deck"]
    assert v["cover"]["title"] == "Lobby LED Wall" and not next(s for s in v["slides"] if s["key"] == "risks")["included"]
    prs, _ = deck(client)
    assert len(prs.slides) == 7 and "Lobby LED Wall" in texts(prs.slides[0])
    client.post(f"{client.base}/submit")
    assert client.put(f"{client.base}/deck", json={}).status_code == 409  # 锁定后不能改


def test_chinese_and_bilingual(client):
    prs, _ = deck(client, "zh")
    assert "数量与 BOQ" in texts(prs.slides[6])
    prs, _ = deck(client, "bi")
    assert "Quantities and BOQ · 数量与 BOQ" in texts(prs.slides[6])


def test_approved_deck_has_no_watermark_and_is_archived(client):
    client.post(f"{client.base}/submit")
    client.post(f"{client.base}/approve", json={})
    prs, r = deck(client)
    assert "_DRAFT" not in r.headers["content-disposition"]
    assert all("DRAFT" not in texts(s) for s in prs.slides)
    assert [f["kind"] for f in client.get(client.base).json()["locked"]["files"]] == ["pptx"]


def test_company_potx_master(client, tmp_path):
    # 用一份 .potx（这里把默认母版另存成模板格式）当公司母版
    src = tmp_path / "Audax.pptx"
    Presentation().save(src)
    import zipfile
    potx = tmp_path / "Audax.potx"
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(potx, "w") as b:
        for item in a.infolist():
            data = a.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"presentationml.presentation.main+xml", b"presentationml.template.main+xml")
            b.writestr(item, data)
    client.app_state.deck_template = potx
    prs, _ = deck(client)
    assert prs.slides[0].shapes.title.text == "Proposal · LED-1 Lobby"  # 封面用母版的标题版式
    assert prs.slides[1].shapes.title.text == "Project overview"
    assert potx.exists()  # 母版原文件不动
