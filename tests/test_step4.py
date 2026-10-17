"""第 4 步验收：样本文件逐个记录识别结果；未确认字段无法进入计算。"""
import hashlib
import os
import shutil
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.extract.fields import find_in_text, parse_value, to_mm
from app.extract.run import extract
from app.main import create_app

SAMPLES = Path(__file__).parent / "fixtures" / "samples"


# ---- 认字段 ----

@pytest.mark.parametrize("text, unit, mm", [("5000", None, 5000), ("5,000", None, 5000), ("5", "m", 5000),
                                            ("4.48", "m", 4480), ("4.48", None, 4480), ("50", None, None)])
def test_common_size_notations(text, unit, mm):  # 清单 G5：5000 / 5,000 / 5m / W5000×H3000
    assert to_mm(text, unit) == mm


def fields(text, ocr=False):
    return {(f, str(v), c) for f, v, c, _ in find_in_text(text, ocr)}


def test_explicit_size_pairs_are_high_from_text_layer():
    assert fields("W5000×H3000") == {("width_mm", "5000", "high"), ("height_mm", "3000", "high")}
    assert fields("LED SCREEN 4500 (W) x 2560 (H)") == {("width_mm", "4500", "high"), ("height_mm", "2560", "high")}
    assert fields("Screen width: 4.48 m") == {("width_mm", "4480", "high")}


def test_ocr_without_spaces_and_unlabeled_pairs():
    assert fields("LEDSCREENW4480XH2560", ocr=True) == {("width_mm", "4480", "medium"), ("height_mm", "2560", "medium")}
    assert fields("4480 x 2560") == {("width_mm", "4480", "medium"), ("height_mm", "2560", "medium")}
    assert fields("4480 x 2560", ocr=True) == {("width_mm", "4480", "low"), ("height_mm", "2560", "low")}


def test_pitch_brightness_viewing_and_keywords():
    assert fields("PIXEL PITCH P2.5") == {("pixel_pitch_mm", "2.5", "high")}
    assert fields("pitch 1.9 mm") == {("pixel_pitch_mm", "1.9", "high")}
    assert fields("Brightness 1,200 nits") == {("brightness_required_nits", "1200", "high")}
    assert fields("Viewing distance 4-6m") == {("viewing_distance_m", "[4, 6]", "high")}
    assert fields("OUTDOOR LED, WALL MOUNTED, FRONT MAINTENANCE") == {
        ("environment", "outdoor", "medium"), ("installation", "wall", "medium"), ("maintenance", "front", "medium")}
    assert fields("LOBBY WALL ELEVATION, FRONT VIEW") == set()  # 自由文字里的 wall / front 不算


def test_excel_cell_values():
    assert parse_value("environment", "Indoor") == "indoor"
    assert parse_value("installation", "Wall mount") == "wall"
    assert parse_value("viewing_distance_m", "4 - 6 m") == [4, 6]
    assert parse_value("pixel_pitch_mm", "P2.5") == 2.5
    assert parse_value("width_mm", "4,480") == 4480


# ---- 样本文件逐个记录（自制样本；真实样本到了以后照这个格式加）----

EXPECTED = {
    "Lobby_Elevation_RevB.pdf": ("A", "text_layer", {
        ("width_mm", 4500, "high", "p.2"), ("height_mm", 2560, "high", "p.2"),
        ("pixel_pitch_mm", 2.5, "high", "p.2"), ("environment", "indoor", "medium", "p.2")}),
    "LED_Requirement.xlsx": ("A", "excel", {
        ("environment", "indoor", "high", "LED!B4"), ("pixel_pitch_mm", 2.5, "high", "LED!B6"),
        ("installation", "wall", "high", "LED!B9"), ("maintenance", "front", "high", "LED!B10"),
        ("brightness_required_nits", 600, "high", "LED!B11")}),
    "Lobby_site_photo.jpg": ("B", "ocr", {
        ("width_mm", 4480, "medium", "文字识别"), ("height_mm", 2560, "medium", "文字识别"),
        ("viewing_distance_m", (4, 6), "medium", "文字识别")}),
    "Scanned_Plan.pdf": ("B", "ocr", {
        ("width_mm", 4480, "low", "p.1 · 文字识别"), ("height_mm", 2560, "low", "p.1 · 文字识别")}),
    "Elevation.dxf": ("A", "dxf", {
        ("width_mm", 4480, "high", "A-ANNO · (0, 3000)"), ("height_mm", 2560, "high", "A-ANNO · (0, 3000)"),
        ("pixel_pitch_mm", 2.5, "high", "A-ANNO · (0, 2700)"), ("environment", "indoor", "medium", "A-ANNO · (0, 2700)")}),
    "Concept_render.png": ("C", "ocr", set()),
}


def record(result):
    return (result["grade"], result["method"],
            {(f["field"], tuple(f["value"]) if isinstance(f["value"], list) else f["value"], f["confidence"],
              f["location"]) for f in result["fields"]})


@pytest.mark.parametrize("name", EXPECTED)
def test_sample_results(name, tmp_path):
    path = SAMPLES / name
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = extract(path, path.suffix[1:].lower(), tmp_path, "derived/1", None)
    assert record(result) == EXPECTED[name]
    assert result["status"] == ("attached" if not result["fields"] else "read")
    for f in result["fields"]:  # 原文截图另存副本
        if f["crop"]:
            assert (tmp_path / f["crop"]).read_bytes()[:4] == b"\x89PNG"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before  # 原件没被改


def test_dwg_needs_oda_then_reads_converted_copy(tmp_path):
    dwg = tmp_path / "Elevation.dwg"
    dwg.write_bytes(b"AC1032 fake dwg")
    r = extract(dwg, "dwg", tmp_path, "derived/1", None)
    assert (r["grade"], r["status"]) == ("C", "attached") and "ODA" in r["note"]

    # 测试用：假装 ODA 把 DWG 转成了 DXF
    if os.name == "nt":
        oda = tmp_path / "fake_oda.cmd"
        oda.write_text(f'@copy "{SAMPLES / "Elevation.dxf"}" "%~2\\source.dxf" >nul\n')
    else:
        oda = tmp_path / "fake_oda.sh"
        oda.write_text(f'#!/bin/sh\ncp "{SAMPLES / "Elevation.dxf"}" "$2/source.dxf"\n')
        oda.chmod(oda.stat().st_mode | stat.S_IEXEC)
    r = extract(dwg, "dwg", tmp_path, "derived/1", str(oda))
    assert (r["grade"], r["method"]) == ("A", "dwg")
    assert {f["field"] for f in r["fields"]} == {"width_mm", "height_mm", "pixel_pitch_mm", "environment"}
    assert (tmp_path / "derived/1/converted.dxf").exists() and dwg.read_bytes() == b"AC1032 fake dwg"


def test_unreadable_types_are_only_attached(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("W4480 x H2560")
    assert record(extract(txt, "txt", tmp_path, "derived/1", None)) == ("C", "none", set())
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    r = extract(broken, "pdf", tmp_path, "derived/2", None)
    assert (r["grade"], r["status"]) == ("C", "failed")


# ---- 确认关 ----

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        c.project = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.proposal = c.post(f"/api/projects/{c.project}/proposals",
                            json={"name": "LED-1 Lobby", "business_line": "LED"}).json()["id"]
        yield c


def upload(client, *names):
    files = [("files", (n, (SAMPLES / n).read_bytes())) for n in names]
    r = client.post(f"/api/projects/{client.project}/files", files=files)
    assert r.status_code == 201, r.text


def post(client, path, body=None):
    r = client.post(f"/api/proposals/{client.proposal}/{path}", json=body or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_unconfirmed_fields_cannot_be_calculated(client):
    upload(client, "Lobby_Elevation_RevB.pdf", "LED_Requirement.xlsx", "Lobby_site_photo.jpg", "Concept_render.png")
    files = client.get(f"/api/projects/{client.project}").json()["files"]
    assert [(f["grade"], f["read_status"]) for f in files] == [("A", "read"), ("A", "read"), ("B", "read"), ("C", "attached")]

    v = post(client, "fill-from-files")
    assert v["rev"]["inputs"]["width_mm"] == 4500  # 文字层 high
    assert v["rev"]["inputs"]["environment"] == "indoor"  # Excel high 排在 PDF medium 前面
    assert v["pending"] == ["viewing_distance_m"]  # 照片文字识别 medium
    assert v["rev"]["status"] == "confirming" and v["result"] is None  # 确认之前不计算

    v = post(client, "confirm", {"field": "viewing_distance_m"})
    assert v["pending"] == [] and v["rev"]["input_meta"]["viewing_distance_m"]["confirmed_by"] == "Jimmy"
    assert v["result"]["choices"] == {"width_mm": [4480, 4800]}  # 4500 不是模组整数倍，让人选

    photo_width = next(c for c in v["candidates"]["width_mm"] if c["filename"] == "Lobby_site_photo.jpg")
    v = post(client, "pick", {"extracted_id": photo_width["id"]})
    assert v["pending"] == ["width_mm"] and v["result"] is None  # 换成 medium 的值又要确认

    v = post(client, "confirm", {"field": "width_mm"})
    assert v["pending"] == [] and v["rev"]["status"] == "draft"  # 还缺信号源数（F13）

    r = client.put(f"/api/proposals/{client.proposal}/inputs",
                   json={"inputs": v["rev"]["inputs"] | {"signal_sources": 1}})
    v = r.json()
    assert v["rev"]["input_meta"]["signal_sources"]["source"] == "manual"  # 手填 = 录入人已确认
    assert v["rev"]["input_meta"]["width_mm"]["source"] == "file"  # 没改的字段保持原来的来源和确认记录
    assert v["pending"] == [] and v["rev"]["status"] == "calculated"
    assert next(x for x in v["result"]["rules"] if x["id"] == "F3")["display"].startswith("35 个")


def test_reread_and_crop(client):
    upload(client, "Lobby_site_photo.jpg")
    cands = client.get(f"/api/proposals/{client.proposal}").json()["candidates"]
    crop = client.get(f"/api/extracted/{cands['width_mm'][0]['id']}/crop")
    assert crop.status_code == 200 and crop.content[:4] == b"\x89PNG"

    stored = next((client.app.state.data_dir / "files").rglob("Lobby_site_photo.jpg"))
    before = stored.read_bytes()
    r = client.post(f"/api/projects/{client.project}/read")
    assert r.status_code == 200
    files = client.get(f"/api/projects/{client.project}").json()["files"]
    assert files[0]["read_status"] == "read" and files[0]["fields_found"] == 3
    assert stored.read_bytes() == before  # 重新读取不碰原件


def test_confirm_and_pick_need_valid_targets(client):
    assert client.post(f"/api/proposals/{client.proposal}/confirm", json={"field": "width_mm"}).status_code == 404
    assert client.post(f"/api/proposals/{client.proposal}/pick", json={"extracted_id": 999}).status_code == 404
