"""第 6 步验收（方案文档）：PDF、可编辑 Word、JPG Boards 用同一份内容；没批准的带 DRAFT；
文件属性写入 Rev、规则、产品库、模板版本；已批准的 Rev 第一次导出后存档，之后给同一份文件（锁定的「生成的文件」）。"""
import io
import zipfile

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

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
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza", "location": "Lobby"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"]
        c.base = f"/api/proposals/{c.proposal}"
        c.data_dir = tmp_path
        yield c


def test_no_document_before_calculation(client):
    assert client.get(f"{client.base}/proposal.pdf").status_code == 409


def test_draft_pdf_has_all_sections_and_version_properties(client):
    client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]})
    r = client.get(f"{client.base}/proposal.pdf")
    assert r.status_code == 200 and "_DRAFT.pdf" in r.headers["content-disposition"]
    pdf = PdfReader(io.BytesIO(r.content))
    assert pdf.metadata["/Subject"] == "Rev 1 · 规则 v1.3 · 产品库 v1.0 · 模板 v1.0 · DRAFT"
    text = "".join(p.extract_text() for p in pdf.pages)
    for title in ["概述", "推荐配置", "工程量清单", "系统图", "连接与线缆", "拼接与线路图", "风险与假设", "计算依据"]:
        assert title in text, title
    assert "P2.5 Indoor LED screen on wall" in text and "DRAFT" in text


def test_word_is_editable_with_native_tables(client):
    client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]})
    r = client.get(f"{client.base}/proposal.docx?lang=en")
    doc = Document(io.BytesIO(r.content))
    assert doc.core_properties.subject == "Rev 1 · Rules v1.3 · Product library v1.0 · Template v1.0 · DRAFT"
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert "Bill of quantities (BOQ)" in headings and "Appendix: calculation basis" in headings
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert any(c.startswith("P2.5 Indoor LED screen on wall") for c in cells) and "11.47" in cells
    assert len(doc.inline_shapes) == 2  # 系统图 + 拼接与线路图，图片可整张替换
    assert "DRAFT" in doc.sections[0].header.paragraphs[0].text


def test_jpg_boards(client):
    client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]})
    z = zipfile.ZipFile(io.BytesIO(client.get(f"{client.base}/proposal.boards").content))
    names = z.namelist()
    assert names[0] == "Board_01.jpg" and len(names) == 5  # 封面、配置、BOQ、系统图、图纸
    assert z.read(names[0])[:3] == b"\xff\xd8\xff"


def test_approved_rev_stores_its_files_once(client):
    client.put(f"{client.base}/inputs", json={"inputs": SAMPLE["input"]})
    official(client, client.base)
    client.post(f"{client.base}/submit")
    client.post(f"{client.base}/approve", json={})
    first = client.get(f"{client.base}/proposal.pdf")
    assert "_DRAFT" not in first.headers["content-disposition"]
    assert "DRAFT" not in PdfReader(io.BytesIO(first.content)).metadata["/Subject"]
    files = client.get(client.base).json()["locked"]["files"]
    assert [(f["kind"], f["lang"], f["by"]) for f in files] == [("pdf", "zh", "Jimmy")]
    assert (client.data_dir / files[0]["path"]).exists()
    assert client.get(f"{client.base}/proposal.pdf").content == first.content  # 永不重新生成
    client.get(f"{client.base}/proposal.pdf?lang=en")
    assert len(client.get(client.base).json()["locked"]["files"]) == 2
