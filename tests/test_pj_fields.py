"""2026-11-13 试用反馈 4：投影的输入也从文件文字里认出来（只认带标注的写法，没标注的数字不猜；都要在确认关逐项确认）。"""
import io

import pytest
from openpyxl import Workbook

from app.extract.fields import find_in_text, parse_value


def found(text, ocr=True):
    return {(f, v) for f, v, _c, _s in find_in_text(text, ocr)}


@pytest.mark.parametrize("text, expected", [
    ("墙宽 6400mm 墙高 3520mm", {("width_mm", 6400), ("height_mm", 3520)}),
    ("Wall width: 6.4 m", {("width_mm", 6400)}),
    ("可用进深：8.5m", {("available_depth_mm", 8500)}),
    ("天花高度 3200", {("ceiling_height_mm", 3200)}),
    ("C.H. 2,800 mm", {("ceiling_height_mm", 2800)}),
    ("层高 4.2m，墙高 3.5m", {("ceiling_height_mm", 4200), ("height_mm", 3500)}),
    ("镜头高度 2.6m", {("mount_height_m", 2.6)}),
    ("Lens height 2600 mm", {("mount_height_m", 2.6)}),
    ("环境光 150 lux", {("ambient_lux", 150)}),
    ("信号距离 35m", {("signal_run_m", 35)}),
    ("Screen gain 1.0", {("surface_gain", 1)}),
    ("吊顶安装", {("mounting", "ceiling")}),
])
def test_projection_labels(text, expected):
    assert found(text) == expected


def test_ceiling_and_lens_height_are_not_screen_height():
    assert ("height_mm", 3200) not in found("天花高度 3200")
    assert ("height_mm", 2600) not in found("镜头高度 2600mm")
    assert found("屏幕高度 2560") == {("height_mm", 2560)}  # LED 原来的写法不受影响
    assert found("CHANNEL 3000") == set()


def test_projection_excel_columns():
    assert parse_value("available_depth_mm", "8.5 m") == 8500
    assert parse_value("ceiling_height_mm", "3,200") == 3200
    assert parse_value("mount_height_m", "2600") == 2.6
    assert parse_value("mounting", "吊装") == "ceiling"


def test_projection_proposal_gets_candidates_from_an_excel(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(tmp_path)) as c:
        u = c.post("/api/users", json={"name": "JM", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": u["id"]})
        p = c.post("/api/projects", json={"name": "Showroom", "client": "X", "business_line": "PJ"}).json()
        wb = Workbook()
        ws = wb.active
        for row in [("墙宽", "6400 mm"), ("墙高", "3520"), ("可用进深", "8.5 m"), ("天花高度", 3200), ("镜头高度", "2.6 m"),
                    ("环境光", "150 lux")]:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        r = c.post(f"/api/projects/{p['id']}/files", files=[("files", ("survey.xlsx", buf.getvalue()))])
        assert r.status_code == 201
        v = c.get(f"/api/proposals/{p['proposals'][0]['id']}").json()
        got = {k: v["candidates"][k][0]["value"] for k in v["candidates"]}
        assert got == {"wall_width_mm": 6400, "wall_height_mm": 3520, "available_depth_mm": 8500,
                       "ceiling_height_mm": 3200, "mount_height_m": 2.6, "ambient_lux": 150}
