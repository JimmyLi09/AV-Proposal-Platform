"""第 8 步验收（投影专属图）：立面融合区图、平面机位图、剖面遮挡图。

- 图上不另算数量：台数、画面宽高、融合带、机位距离、挡光距离都和 P2–P10 的结果一致（金标准 114 Showroom：5 台、
  画面 4.48 × 2.8 m、融合带 ≈ 1.02 m / 22.7 %、离墙 2.24 m、1.44 m 以内挡光）；改了输入，图跟着规则结果变。
- 06 页、方案 PDF / Word / JPG Boards、演示稿用同一张图；投影演示稿 11 页（多出立面融合区、平面与剖面两页）。
- 中英文；没批准带 DRAFT。LED 和多面投影没有这三张图。
"""
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pptx import Presentation

from conftest import official
from app import deck
from app.main import create_app
from app.rules.engine import load_seed

_, PJ = load_seed("PJ")
_, LED = load_seed("LED")
CASES = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
CJK = re.compile(r"[　-〿一-鿿＀-￯]")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        p = c.post("/api/projects", json={"name": "114 Showroom", "client": "Showroom", "business_line": "PJ"}).json()
        c.base = f"/api/proposals/{p['proposals'][0]['id']}"
        c.project = p["id"]
        c.put(f"{c.base}/inputs", json={"inputs": PJ["input"]})
        yield c


def svg(client, kind, lang="zh"):
    r = client.get(f"{client.base}/projection/{kind}.svg?lang={lang}")
    assert r.status_code == 200, r.text
    return r.text


def value(v, name):
    return next(ln["value"] for r in v["result"]["rules"] for ln in r["lines"] if ln["name"] == name)


def rects(s, cls):
    return [tuple(float(x) for x in m) for m in re.findall(
        rf'<rect class="{cls}" x="([\d.]+)" y="[\d.-]+" width="([\d.]+)"', s)]


def test_drawings_use_the_rule_results_of_114(client):
    v = client.get(client.base).json()
    d, g = v["projection"], CASES["projection_114"]["expect"]
    assert d["n"] == value(v, "projectors") == g["P2_count"]
    assert (d["img_w"] / 1000, d["img_h"] / 1000) == (g["P4_actual_width_m"], g["P4_actual_height_m"])
    assert round(d["overlap"] / 1000, 2) == g["P5_overlap_m"] and d["within"] / 1000 == g["P10_occlusion_within_m"]
    assert (d["img_w"], d["img_h"]) == (round(value(v, "image_w_m") * 1000), round(value(v, "image_h_m") * 1000)) == (4480, 2800)
    assert d["overlap"] == round(value(v, "overlap_m") * 1000) == 1019 and d["pitch"] == 3461
    assert d["distance"] == 2240 and d["within"] == round(value(v, "occlusion_within_m") * 1000) == 1440
    assert abs(d["lefts"][-1] + d["img_w"] - d["wall_w"]) <= d["n"]  # 5 张画面正好铺满 18325 墙宽（每台四舍五入到 mm）

    el = svg(client, "elevation")
    images, blends = rects(el, "image"), rects(el, "blend")
    assert len(images) == 5 and len(blends) == 4
    scale = images[0][1] / 4480
    assert all(abs(b[1] - 1019 * scale) < 0.2 for b in blends)  # 每条融合带宽 = P5 的融合带
    assert all(abs((b[0] - a[0]) - 3461 * scale) < 0.2 for a, b in zip(images, images[1:]))
    assert "融合带 22.7 % ≈ 1019 × 4" in el and "墙宽 18325" in el and "上下各超出墙面 50" in el

    plan = svg(client, "plan")
    assert plan.count('class="cone"') == 5 and plan.count('class="projector"') == 5
    assert "镜头前端离墙 2.24 m（P3 / P4）；可用进深 3.2 m" in plan and "中心间距 3461 mm" in plan
    assert "镜头前端后方余 0.96 m" in plan

    sec = svg(client, "section")
    assert sec.count('class="shadow"') == 1 and sec.count('class="ray"') == 2
    assert "人高 1.8 m 时，离墙 1.44 m 以内会挡光" in sec and "天花 3 m（手填）" in sec


def test_drawings_follow_the_inputs(client):
    """机位往后移到 2.3 m：P4 画面变宽、P5 融合带变大，图跟着规则结果变（不在图上另算）。"""
    v = client.put(f"{client.base}/inputs", json={"inputs": PJ["input"] | {"mount_distance_m": 2.3}}).json()
    d = v["projection"]
    assert d["img_w"] == round(value(v, "image_w_m") * 1000) == 4600 and d["distance"] == 2300
    assert d["overlap"] == round(value(v, "overlap_m") * 1000) and d["pitch"] == d["img_w"] - d["overlap"]
    assert f"融合带 {value(v, 'overlap_pct'):.1f} %" in svg(client, "elevation")


def test_english_and_draft_stamp(client):
    for kind in ("elevation", "plan", "section"):
        s = svg(client, kind, "en")
        assert not CJK.search(s) and "DRAFT" in s
    assert "Shadow within 1.44 m" in svg(client, "section", "en")
    official(client, client.base)
    client.post(f"{client.base}/submit")
    client.post(f"{client.base}/approve", json={})
    assert "DRAFT" not in svg(client, "elevation")


def test_led_and_multiface_projection_have_no_projection_drawings(client):
    pid = client.post(f"/api/projects/{client.project}/proposals", json={"business_line": "LED"}).json()["id"]
    client.put(f"/api/proposals/{pid}/inputs", json={"inputs": LED["input"]})
    assert client.get(f"/api/proposals/{pid}").json()["projection"] is None
    assert client.get(f"/api/proposals/{pid}/projection/plan.svg").status_code == 409
    faces = [{"id": "A", "name": "Left", "orientation": "wall", "width_mm": 6000, "height_mm": 2700},
             {"id": "B", "name": "Main", "orientation": "wall", "width_mm": 9000, "height_mm": 2700}]
    v = client.put(f"{client.base}/inputs", json={"inputs": PJ["input"] | {"shape": "L", "faces": faces,
                                                                           "corners": [{"between": ["A", "B"], "type": "inside_90"}]}}).json()
    assert v["result"]["faces"] and v["projection"] is None


def test_proposal_documents_and_deck_carry_the_drawings(client):
    doc = Document(io.BytesIO(client.get(f"{client.base}/proposal.docx").content))
    heads = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert {"立面融合区图", "平面机位图", "剖面遮挡图"} <= set(heads)

    z = zipfile.ZipFile(io.BytesIO(client.get(f"{client.base}/proposal.boards").content))
    assert len(z.namelist()) == 6  # 封面、配置、BOQ、系统图、立面融合区、平面与剖面

    assert len(deck.SLIDES["PJ"]) == 11  # 方案：投影 11 页
    settings = client.get(client.base).json()["deck"]["slides"]
    assert [s["key"] for s in settings] == [k for k in deck.SLIDES["PJ"] if k != "annotated"]  # 没有标注副本：不出标注页
    prs = Presentation(io.BytesIO(client.get(f"{client.base}/proposal.pptx?lang=en").content))
    titles = [next((sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text in
                    ("Elevation · blend zones", "Plan and section")), None) for s in prs.slides]
    assert len(prs.slides) == 10 and "Elevation · blend zones" in titles and "Plan and section" in titles
    both = prs.slides[titles.index("Plan and section")]
    assert sum(1 for sh in both.shapes if sh.shape_type == 13) == 2  # 平面、剖面两张图并排
