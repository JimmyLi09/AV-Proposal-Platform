"""2026-11-21：《项目需求单》Excel 模板——按表填好上传，每一栏都读成高置信度（A 级）。"""
import io
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.extract.run import extract
from app.requirement_form import FORMS, build
from test_step1 import client, login  # noqa: F401

EXPECT = {
    "LED": {"width_mm": 4480, "height_mm": 2560, "pixel_pitch_mm": 2.5, "environment": "indoor", "installation": "wall",
            "maintenance": "front", "brightness_required_nits": 600, "viewing_distance_m": [4, 6], "signal_sources": 1},
    "PJ": {"width_mm": 18325, "height_mm": 2700, "available_depth_mm": 3200, "ceiling_height_mm": 3000, "mounting": "ceiling",
           "mount_height_m": 2.8, "ambient_lux": 150, "surface_gain": 1, "nearest_viewing_m": 1.5, "signal_run_m": 35},
}


def _filled(line: str, tmp_path: Path) -> Path:
    wb = load_workbook(io.BytesIO(build(line)))
    ws = wb["需求单"]
    examples = {label: ex for label, _, ex, _ in FORMS[line][1]}
    for row in ws.iter_rows(max_col=1):
        if row[0].value in examples:
            ws.cell(row[0].row, 2, examples[row[0].value])
    path = tmp_path / "f.xlsx"
    wb.save(path)
    return path


@pytest.mark.parametrize("line", ["LED", "PJ"])
def test_every_field_reads_as_grade_a(line, tmp_path):
    out = extract(_filled(line, tmp_path), "xlsx", tmp_path, "x", None)
    assert out["grade"] == "A"
    assert {f["field"]: f["value"] for f in out["fields"]} == EXPECT[line]
    assert {f["confidence"] for f in out["fields"]} == {"high"}


def test_blank_form_and_instruction_sheet_give_nothing(tmp_path):
    """空表和「填写说明」页（里面有示例值）都不读出任何值。"""
    path = tmp_path / "blank.xlsx"
    path.write_bytes(build("LED"))
    assert extract(path, "xlsx", tmp_path, "x", None)["fields"] == []


def test_download(client):
    login(client)
    r = client.get("/api/templates/requirement/LED.xlsx")
    assert r.status_code == 200 and load_workbook(io.BytesIO(r.content)).sheetnames == ["需求单", "填写说明"]
    assert client.get("/api/templates/requirement/XX.xlsx").status_code == 404
