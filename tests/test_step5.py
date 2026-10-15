"""第 5 步验收：示意图里每台设备都能在 BOQ 中找到。外加 PDF / JPG 标注另存副本、原件不动。"""
import copy
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.products.library import load_seed as load_library
from app.rules.engine import calculate, load_seed

RULES, SAMPLE = load_seed("LED")
LIBRARY = load_library("LED")
SAMPLES = Path(__file__).parent / "fixtures" / "samples"


# ---- 示意图 ----

def test_every_device_and_cable_in_diagram_is_in_boq():
    out = calculate(RULES, LIBRARY, SAMPLE["input"])
    d, keys = out["diagram"], {line["key"] for line in out["boq"]}
    assert d["unmatched"] == []
    supplied = [n for n in d["nodes"].values() if n["supply"] == "boq"]
    assert {n["title"] for n in supplied} == {"Video processor 视频处理器", "Controller 控制器", "LED wall LED 屏",
                                              "DB box 配电箱"}
    for n in supplied:
        assert n["boq"] and set(n["boq"]) <= keys, n
    for link in d["links"]:
        assert link["boq"] in keys if link["supply"] == "boq" else link["supply"] in ("owner", "included")
    others = {n["title"]: n["supply"] for n in d["nodes"].values() if n["supply"] != "boq"}
    assert others == {"Content source 信号源": "owner"}  # 业主提供，图上虚线标出


def test_diagram_follows_boq_and_flags_a_blocked_controller():
    library = copy.deepcopy(LIBRARY)
    next(p for p in library["products"] if p["id"] == "SC-4")["capacity_px"] = 1_000_000
    d = calculate(RULES, library, SAMPLE["input"])["diagram"]
    assert d["nodes"]["controller"]["supply"] == "missing"
    assert any("控制器" in u for u in d["unmatched"])


def test_concept_svg_escapes_product_text():
    library = copy.deepcopy(LIBRARY)
    next(p for p in library["products"] if p["id"] == "SC-4")["model"] = "<b>SC-4</b>"
    svg = calculate(RULES, library, SAMPLE["input"])["diagram"]["svg"]
    assert "&lt;b&gt;SC-4&lt;/b&gt;" in svg and "<b>" not in svg
    assert svg.startswith("<svg") and "Cat6 × 4 + 1 备用" in svg and "业主提供" in svg


# ---- 标注 ----

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        c.project = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{c.project}/proposals",
                            json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"]
        names = ["Lobby_site_photo.jpg", "Lobby_Elevation_RevB.pdf", "LED_Requirement.xlsx"]
        files = c.post(f"/api/projects/{c.project}/files",
                       files=[("files", (n, (SAMPLES / n).read_bytes())) for n in names]).json()
        c.files = {f["filename"]: f["id"] for f in files}
        yield c


def annotate(client, body):
    return client.put(f"/api/proposals/{client.proposal}/annotations", json=body)


def test_annotated_copy_is_saved_and_original_untouched(client):
    photo, pdf = client.files["Lobby_site_photo.jpg"], client.files["Lobby_Elevation_RevB.pdf"]
    assert client.get(f"/api/files/{photo}/pages").json() == {"pages": 1}
    assert client.get(f"/api/files/{pdf}/pages").json() == {"pages": 2}
    page = client.get(f"/api/files/{pdf}/page/2")
    assert page.status_code == 200 and abs(max(Image.open(io.BytesIO(page.content)).size) - 2000) <= 2

    stored = next((client.app.state.data_dir / "files").rglob("Lobby_site_photo.jpg"))
    before = stored.read_bytes()
    body = {"file_id": photo, "page": 1,
            "scale": {"a": {"x": 0.1, "y": 0.5}, "b": {"x": 0.5, "y": 0.5}, "mm": 4480},
            "marks": [{"type": "area", "x": 0.1, "y": 0.2, "w": 0.4, "h": 0.2, "label": "LED-1 区域", "note": "底边 +0.900 FFL"},
                      {"type": "device", "x": 0.8, "y": 0.6, "label": "DB box 配电箱", "boq_key": "db_box"},
                      {"type": "point", "x": 0.7, "y": 0.9, "label": "Power point 电源点", "note": "假设 25 m 以内"},
                      {"type": "text", "x": 0.05, "y": 0.05, "label": "LOBBY 大堂"}]}
    r = annotate(client, body)
    assert r.status_code == 200, r.text
    doc = r.json()["annotations"][f"{photo}:1"]
    assert doc["copy_name"] == "Lobby_site_photo_annotated_Rev0.jpg" and doc["updated_by"] == "Jimmy"
    w_mm, h_mm = doc["marks"][0]["size_mm"]
    assert w_mm == 4480 and h_mm == round(0.2 * doc["height"] / (0.4 * doc["width"]) * 4480)

    copy_resp = client.get(f"/api/proposals/{client.proposal}/annotations/{photo}/1/copy")
    assert copy_resp.status_code == 200 and copy_resp.content[:3] == b"\xff\xd8\xff"  # JPG
    marked = Image.open(io.BytesIO(copy_resp.content))
    assert marked.size[0] == doc["width"] and marked.size[1] > doc["height"]  # 下方加了图例
    assert stored.read_bytes() == before  # 原件没被改

    r = annotate(client, {"file_id": pdf, "page": 2, "marks": [{"type": "point", "x": 0.5, "y": 0.5}]})
    assert r.json()["annotations"][f"{pdf}:2"]["copy_name"] == "Lobby_Elevation_RevB_p2_annotated_Rev0.jpg"

    view = client.get(f"/api/proposals/{client.proposal}").json()
    assert set(view["rev"]["annotations"]) == {f"{photo}:1", f"{pdf}:2"}
    assert annotate(client, {"file_id": photo, "page": 1, "marks": []}).json()["annotations"].keys() == {f"{pdf}:2"}


def test_annotation_validation(client):
    photo = client.files["Lobby_site_photo.jpg"]
    assert annotate(client, {"file_id": photo, "marks": [{"type": "point", "x": 1.5, "y": 0.5}]}).status_code == 422
    assert annotate(client, {"file_id": photo, "marks": [{"type": "circle", "x": 0.5, "y": 0.5}]}).status_code == 422
    xlsx = client.files["LED_Requirement.xlsx"]
    assert annotate(client, {"file_id": xlsx, "marks": [{"type": "point", "x": 0.5, "y": 0.5}]}).status_code == 422
    assert annotate(client, {"file_id": 999, "marks": []}).status_code == 404
