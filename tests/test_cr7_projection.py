"""CR-7 / 第 7 步验收：投影单面墙 P1–P17。114 Showroom 金标准全部对上（5 台、0.5 镜头、融合带 ≈ 1.02 m、≈ 7854 px、2.3 mm、
CAT6 12 根），Phoenix Sea 的行为用例全部通过（数量不一致必须阻断）。"""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.products.library import load_seed as load_library
from app.rules import pj
from app.rules.engine import calculate, load_seed

CASES = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
C114 = CASES["projection_114"]
RULES, SAMPLE = load_seed("PJ")
LIBRARY = load_library("PJ")


def values(out):
    return {ln["name"]: ln["value"] for r in out["rules"] for ln in r["lines"]}


def rule(out, rid):
    return next(r for r in out["rules"] if r["id"] == rid)


@pytest.fixture(scope="module")
def r114():
    out = calculate(RULES, LIBRARY, SAMPLE["input"])
    assert not [r["id"] for r in out["rules"] if r["missing"] or r["error"]], out["rules"]
    return out


def test_sample_input_is_the_114_case():
    i = C114["input"]
    for k in ("wall_width_mm", "wall_height_mm", "available_depth_mm", "mount_height_m", "mount_distance_m",
              "surface_gain", "nearest_viewing_m", "signal_run_m"):
        assert SAMPLE["input"][k] == i[k], k


def test_114_geometry(r114):
    v, e, tol = values(r114), C114["expect"], C114["tolerance"]
    assert v["single_w_m"] == pytest.approx(e["P1_single_width_m"], abs=tol["length_m"])
    assert v["projectors"] == e["P2_count"] == 5
    assert v["min_distance_m"] == pytest.approx(e["P3_min_distance_m"], abs=tol["length_m"])
    assert v["throw_ratio"] == e["P3_lens"] and rule(r114, "P3")["check"] == "PASS"
    assert v["image_w_m"] == pytest.approx(e["P4_actual_width_m"], abs=tol["length_m"])
    assert v["image_h_m"] == pytest.approx(e["P4_actual_height_m"], abs=tol["length_m"])
    assert v["overlap"] == pytest.approx(e["P5_overlap_ratio"], abs=tol["ratio"])
    assert v["overlap_m"] == pytest.approx(e["P5_overlap_m"], abs=tol["length_m"])
    assert rule(r114, "P5")["check"] == e["P5_check"] and rule(r114, "P6")["check"] == e["P6_height_check"]
    assert [v["blended_px_x"], v["blended_px_y"]] == e["P7_blended_px"]
    assert rule(r114, "P8")["display"] == "2.3 mm" and rule(r114, "P8")["check"] == e["P8_check"]
    assert v["lumens_required"] == pytest.approx(e["P9_lumens_required"]["value"], abs=tol["lumens"])
    assert rule(r114, "P9")["status"] == "sample"  # 目标亮度、折减、PT-BHZ611C 流明都是示例值
    assert v["occlusion_within_m"] == pytest.approx(e["P10_occlusion_within_m"], abs=tol["length_m"])
    assert rule(r114, "P10")["check"] == e["P10_check"]


def test_114_system_and_cabling(r114):
    v, e = values(r114), C114["expect"]
    b = e["P11_blender"]
    assert v["blender_qty"] == b["qty"] and b["pick"] in v["blender"] and v["blender_outputs"] >= b["min_outputs"]
    assert v["power_kw"] == pytest.approx(e["P12_power_kw"]["value"], abs=0.005)
    assert v["power_with_margin_kw"] == pytest.approx(e["P12_power_kw"]["with_margin"], abs=0.005)
    assert v["circuits"] == e["P12_circuits"] == 2
    assert [v["canvas_px_x"], v["canvas_px_y"]] == e["P13_canvas_px"]
    assert v["transport"] == e["P14_transport"] == "HDBaseT"
    c = e["P15_cables"]
    assert (v["video_lines"], v["video_spare"], v["control_lines"], v["control_spare"], v["total_cat6"]) == (
        c["video"], c["video_spare"], c["control_cat6"], c["control_spare"], c["total_cat6"])
    p = e["P16_power"]
    assert (v["ceiling_outlets"], v["server_room_w"], v["server_room_w_margin"], v["server_room_plugs"],
            v["option_a_outlets"], v["option_b_ups_kva"]) == (
        p["ceiling_13a_outlets"], p["server_room_w"], p["server_room_w_with_margin"], p["server_room_plugs"],
        p["option_a_outlets"], p["option_b_ups_kva"])
    assert rule(r114, "P17")["check"] == e["P17_check"]["result"] and v["control_points"] == e["P17_check"]["control_points"]


def test_lens_is_picked_from_the_library_not_typed():
    """P3：可配镜头里取放得进进深、投射比最小的；0.46 不适配 PT-BHZ611C，所以是 0.5。进深不够时阻断。"""
    inputs = SAMPLE["input"] | {"mount_distance_m": None}
    v = values(calculate(RULES, LIBRARY, inputs))
    assert v["throw_ratio"] == 0.5 and v["distance_m"] == v["min_distance_m"] == pytest.approx(2.16)
    out = calculate(RULES, LIBRARY, inputs | {"available_depth_mm": 2000})
    assert rule(out, "P3")["check"] == "BLOCK"


# ---- Phoenix Sea 行为用例 ----

PHOENIX = {c["name"]: c for c in CASES["phoenix_sea_checks"]["cases"]}
PARAMS = {p["name"]: Decimal(str(p["value"])) for p in RULES["params"]}


def test_count_mismatch_blocks():
    c = PHOENIX["count mismatch"]["input"]
    out = pj.consistency(PARAMS | {"projectors": Decimal(c["projectors"]), "video_lines": Decimal(c["projectors"]),
                                   "control_lines": Decimal(c["projectors"]), "existing_video_lines": Decimal(c["video_lines"])},
                         {})
    assert out["check"] == "BLOCK" and "4" in out["note"] and "5" in out["note"]


@pytest.mark.parametrize("name, transport", [("long HDMI", "HDBaseT"), ("fiber", "Fiber HDMI")])
def test_transport_by_distance(name, transport):
    run = Decimal(PHOENIX[name]["input"]["signal_run_m"])
    assert pj.transport_pick(PARAMS | {"signal_run_m": run, "transport_mode": "by_distance"}, {})["outputs"]["transport"] == transport
    assert pj.transport_pick(PARAMS | {"signal_run_m": Decimal(10), "transport_mode": "by_distance"}, {})["outputs"]["transport"] == "HDMI"


def test_spares_for_two_projectors():
    inputs = SAMPLE["input"] | {"wall_width_mm": 8000}
    v = values(calculate(RULES, LIBRARY, inputs))
    assert v["projectors"] == 2 and (v["video_lines"], v["video_spare"], v["control_lines"], v["control_spare"]) == (2, 1, 2, 1)


def test_past_zone_cables_match_and_server_room_run():
    c = PHOENIX["Past Zone option 1 (slide 06)"]["input"]
    t = pj.transport_pick(PARAMS | {"source_location": c["source_location"], "transport_mode": "by_distance"}, {})
    assert t["outputs"]["transport"] == "HDBaseT" and t["check"] == "NOTE"  # 没填距离、播放源在机房：按超过 15 m
    n = Decimal(c["projectors"])
    out = pj.consistency(PARAMS | {"projectors": n, "video_lines": n, "control_lines": n, "video_spare": Decimal(1),
                                   "control_spare": Decimal(1), "existing_video_total": Decimal(c["hdmi"]),
                                   "existing_control_total": Decimal(c["cat6"])}, {})
    assert out["check"] == "PASS" and out["outputs"]["cables_match"] == "PASS"


def test_no_blender_for_one_projector_and_block_without_enough_outputs():
    v = values(calculate(RULES, LIBRARY, SAMPLE["input"] | {"wall_width_mm": 4400}))
    assert v["projectors"] == 1 and v["blender_qty"] == 0
    lib = copy.deepcopy(LIBRARY)
    for p in lib["products"]:
        if p["category"] == "blender":
            p["outputs"] = 4
    out = calculate(RULES, lib, SAMPLE["input"])
    assert rule(out, "P11")["check"] == "BLOCK"
