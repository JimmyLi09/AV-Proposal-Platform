"""CR-1 验收：图纸上尺寸线旁边单独的数字（「6400mm」在框上方、「3520mm」在框右侧）能读成屏宽 / 屏高候选。
OCR 读到的给 low，PDF 文字层给 medium，DXF 的尺寸标注（DIMENSION）给 medium；都要在确认关逐项确认。"""
from pathlib import Path

import ezdxf
import pytest
from reportlab.pdfgen import canvas

from app.extract.dimensions import lone_value, pair
from app.extract.run import extract

SAMPLES = Path(__file__).parent / "fixtures" / "samples"
FRAME = (250, 220, 1050, 660)
TITLE = ("P2.5 LED SCREEN", (500, 420, 800, 460))


def fields(result):
    return {(f["field"], f["value"], f["confidence"]) for f in result["fields"]}


@pytest.mark.parametrize("text,value", [("6400mm", 6400), (" 3520 mm ", 3520), ("← 4,480 →", 4480), ("4.48m", None),
                                        ("2560", 2560), ("W4480", None), ("12", None), ("FFL +0.900", None)])
def test_lone_value(text, value):
    assert lone_value(text) == value


def test_pair_by_position_around_the_frame():
    lines = [TITLE, ("6400mm", (600, 90, 720, 130)), ("3520mm", (1180, 420, 1300, 460))]
    assert [(f, v) for f, v, *_ in pair(lines, [FRAME, (0, 0, 1400, 900)])] == [("width_mm", 6400), ("height_mm", 3520)]


def test_vertical_text_beside_the_frame_is_height_and_far_numbers_are_ignored():
    lines = [TITLE, ("3520", (1100, 300, 1130, 420)),  # 竖排
             ("12000", (100, 880, 220, 900)),  # 离框体太远（房间尺寸）
             ("6400", (1150, 400, 1260, 430))]  # 右侧，但比竖排的大
    assert [(f, v) for f, v, *_ in pair(lines, [FRAME])] == [("height_mm", 6400)]


def test_largest_per_side_and_one_number_never_both():
    lines = [TITLE] + [(f"640", (260 + i * 110, 170, 330 + i * 110, 200)) for i in range(7)] + [
        ("4480", (600, 100, 700, 130)), ("4480", (1100, 420, 1200, 450)), ("2560", (40, 420, 140, 450))]
    assert [(f, v) for f, v, *_ in pair(lines, [FRAME])] == [("width_mm", 4480), ("height_mm", 2560)]


def test_without_a_frame_falls_back_to_the_text_centre():
    lines = [("LED WALL", (550, 420, 750, 460)), ("6400mm", (600, 90, 720, 130)), ("3520mm", (1180, 420, 1300, 460))]
    assert [(f, v) for f, v, *_ in pair(lines, [])] == [("width_mm", 6400), ("height_mm", 3520)]


def test_test_image_gives_width_height_and_pitch(tmp_path):
    r = extract(SAMPLES / "Dimension_lines.png", "png", tmp_path, "derived/1", None)
    assert fields(r) == {("width_mm", 4480, "low"), ("height_mm", 2560, "low"), ("pixel_pitch_mm", 2.5, "medium")}
    assert {f["location"] for f in r["fields"] if f["field"] != "pixel_pitch_mm"} == {"文字识别 · 尺寸线"}
    assert all((tmp_path / f["crop"]).exists() for f in r["fields"])  # 原文截图另存


def test_pdf_text_layer_dimensions_are_medium(tmp_path):
    pdf = tmp_path / "elevation.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(1190, 842))
    c.rect(300, 250, 560, 320)
    c.drawCentredString(580, 410, "P2.5 LED SCREEN")
    c.drawCentredString(580, 610, "6400mm")
    c.drawString(900, 405, "3520mm")
    c.save()
    r = extract(pdf, "pdf", tmp_path, "derived/1", None)
    assert fields(r) == {("width_mm", 6400, "medium"), ("height_mm", 3520, "medium"), ("pixel_pitch_mm", 2.5, "high")}


def test_dxf_dimension_entities(tmp_path):
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (6400, 0), (6400, 3520), (0, 3520)], close=True)
    msp.add_linear_dim(base=(0, 4000), p1=(0, 3520), p2=(6400, 3520)).render()
    msp.add_linear_dim(base=(7000, 0), p1=(6400, 0), p2=(6400, 3520), angle=90).render()
    msp.add_linear_dim(base=(0, 4500), p1=(0, 3520), p2=(640, 3520)).render()  # 单个箱体，不是总宽
    path = tmp_path / "elevation.dxf"
    doc.saveas(path)
    r = extract(path, "dxf", tmp_path, "derived/1", None)
    assert fields(r) == {("width_mm", 6400, "medium"), ("height_mm", 3520, "medium")}


def test_existing_samples_are_unchanged(tmp_path):
    """原有的成对写法、带栏名写法和 Excel 不受影响（逐项结果见 test_step4.EXPECTED）。"""
    from tests.test_step4 import EXPECTED, record
    for name, expected in EXPECTED.items():
        path = SAMPLES / name
        assert record(extract(path, path.suffix[1:].lower(), tmp_path, f"derived/{name}", None)) == expected
