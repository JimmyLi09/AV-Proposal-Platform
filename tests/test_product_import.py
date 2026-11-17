"""2026-11-17：产品库导入文件——Excel 导出 / 批量导入，规格书读参数。"""
import io
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook

from test_step1 import client, login  # noqa: F401

KB = Path(__file__).parent / "fixtures" / "knowledge" / "kb" / "规格书"


def _library(client, line="LED"):
    return client.get(f"/api/products/{line}").json()


def _import(client, wb, content, line="LED"):
    buf = io.BytesIO()
    wb.save(buf)
    return client.post(f"/api/products/{line}/excel", files={"file": ("p.xlsx", buf.getvalue())},
                       data={"content": json.dumps(content)})


def test_export_then_import_is_a_round_trip(client):
    login(client)
    lib = _library(client)
    r = client.get("/api/products/LED/excel")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["箱体", "控制器", "视频处理器"]
    assert wb["控制器"]["A1"].value == "编号 ID" and wb["控制器"]["A2"].value == "SC-4"
    out = _import(client, wb, lib["content"]).json()
    assert out["errors"] == [] and out["added"] == [] and out["updated"] == []
    assert out["products"] == lib["content"]["products"]


def test_import_adds_and_updates_without_saving(client):
    login(client)
    lib = _library(client)
    wb = Workbook()
    ws = wb.active
    ws.title = "Controller"  # 英文表名、只写英文的表头也认
    ws.append(["ID", "Brand", "Model", "Status", "Load px", "Ports", "Sample data"])
    ws.append(["VX1000", "NovaStar", "VX1000", "首选", "6,500,000", 10, "否"])
    ws.append(["SC-4", None, None, None, 2600000, None, None])        # 已有：只改带载，空格子不改
    ws.append(["BAD", "X", "Y", "首选", "很多", 4, "否"])               # 看不懂的数 → 这一行不导入
    ws.append([None, "no id", "Z", None, None, None, None])           # 没编号的行跳过
    out = _import(client, wb, lib["content"]).json()
    assert out["added"] == ["VX1000"] and out["updated"] == ["SC-4"]
    assert len(out["errors"]) == 1 and out["errors"][0].startswith("Controller!4")
    vx = next(p for p in out["products"] if p["id"] == "VX1000")
    assert (vx["category"], vx["capacity_px"], vx["ports"], vx["status"], vx["scenes"]) == \
        ("controller", 6500000, 10, "preferred", ["indoor"])
    sc4 = next(p for p in out["products"] if p["id"] == "SC-4")
    old = next(p for p in lib["content"]["products"] if p["id"] == "SC-4")
    assert sc4 == old | {"capacity_px": 2600000}
    assert _library(client)["version"] == lib["version"]  # 只是草稿，没有另存版本
    # 草稿照常保存成新版本
    r = client.post("/api/products/LED", json={"base_id": lib["id"], "reason": "Excel 导入", "content":
                                                {**lib["content"], "products": out["products"]}})
    assert r.status_code == 201, r.text


def test_cabinet_sizes_and_scenes(client):
    login(client)
    lib = _library(client)
    wb = Workbook()
    ws = wb.active
    ws.title = "箱体"
    ws.append(["编号", "型号", "适用场景", "点间距 mm", "模组宽 mm", "模组高 mm", "箱体尺寸 mm（第一个为主尺寸）", "维护方式"])
    ws.append(["P1538", "P1.538", "室内、租赁", 1.538, 320, 160, "640x480; 640 × 360", "前维护"])
    out = _import(client, wb, lib["content"]).json()
    assert out["errors"] == []
    p = next(p for p in out["products"] if p["id"] == "P1538")
    assert p["scenes"] == ["indoor", "rental"] and p["cabinet_sizes_mm"] == [[640, 480], [640, 360]]
    assert p["pixel_pitch_mm"] == 1.538 and p["maintenance"] == "front"


def test_not_an_excel(client):
    login(client)
    r = client.post("/api/products/LED/excel", files={"file": ("p.xlsx", b"nope")},
                    data={"content": json.dumps(_library(client)["content"])})
    assert r.status_code == 422


def test_datasheet_values_with_source_text(client):
    login(client)
    pdf = (KB / "VX1000_Spec_EN.pdf").read_bytes()
    r = client.post("/api/products/LED/datasheet", files={"file": ("VX1000_Spec_EN.pdf", pdf)},
                    data={"category": "controller"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["datasheet"] == "VX1000_Spec_EN.pdf" and out["read"] and not out["ocr"]
    assert out["values"]["capacity_px"]["value"] == 6500000
    assert out["values"]["ports"]["value"] == 10
    assert "6.5 million" in out["values"]["capacity_px"]["snippet"]
    saved = list(client.data_dir.glob("datasheets/*/VX1000_Spec_EN.pdf"))  # 原件存档
    assert len(saved) == 1 and saved[0].read_bytes() == pdf

    pj = (KB / "PT-BHZ611C_datasheet.pdf").read_bytes()
    out = client.post("/api/products/PJ/datasheet", files={"file": ("PT-BHZ611C.pdf", pj)},
                      data={"category": "projector"}).json()
    assert {f: v["value"] for f, v in out["values"].items()} == {
        "lumens": 6000, "native_px_w": 1920, "native_px_h": 1200, "power_w": 460, "weight_kg": 22.7, "noise_db": 37}


def test_datasheet_rejects(client):
    login(client)
    assert client.post("/api/products/LED/datasheet", files={"file": ("a.exe", b"x")},
                       data={"category": "controller"}).status_code == 422
    assert client.post("/api/products/LED/datasheet", files={"file": ("a.pdf", b"x")},
                       data={"category": "lens"}).status_code == 422
    client.delete("/api/session")
    assert client.post("/api/products/LED/datasheet", files={"file": ("a.pdf", b"x")},
                       data={"category": "controller"}).status_code == 401
