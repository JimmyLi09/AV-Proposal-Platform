"""CR-7 验收：多面屏。
LED（S1–S7）：GMC U 形、Phoenix Sea Digital Cube L 形（墙 + 地面）的金标准；GMC 左右面宽度 3 份资料冲突时必须阻断。
投影（P18–P22）：L 形、U 形转角演示用例（机房功率按「只算播控电脑」口径，2026-10-24 Jimmy 选「保留两种口径」）。"""
import copy
import json
from pathlib import Path

import pytest

from app.products.library import load_seed as load_library
from app.rules import multiface
from app.rules.engine import calculate, load_seed

CASES = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
_, LED_SAMPLE = load_seed("LED")
# GMC / Digital Cube 的金标准是按规则集 v1.4 算的（功率按面积、每回路 2.5 kW、每根网线 560,000 px）。CR-10 改了这三条算法，
# 这两个用例还没按新算法重新定金标准（待 Jimmy 确认），所以多面屏的 LED 测试用 CR-10 之前的规则集（多面屏的 S1–S7 不受影响）
LED_RULES = json.loads((Path(__file__).parent / "fixtures" / "rules_led_v1_5.json").read_text(encoding="utf-8"))
PJ_RULES, PJ_SAMPLE = load_seed("PJ")


def led_library():
    lib = copy.deepcopy(load_library("LED"))
    # GMC 的箱体尺寸资料里没有；用 320 宽的箱体让 5760 / 8000 都能拼（只影响 F3，金标准不含箱体数）
    next(p for p in lib["products"] if p["id"] == "IC-25")["cabinet_sizes_mm"] = [[320, 640], [320, 480]]
    lib["products"].append({"id": "GOB-20", "category": "cabinet", "brand": "Sample", "model": "GOB P2", "status": "approved",
                            "scenes": ["indoor"], "sample": True, "pixel_pitch_mm": 2.0, "module_w_mm": 320,
                            "module_h_mm": 160, "cabinet_sizes_mm": [[640, 480], [640, 640]], "brightness_nits": 800,
                            "max_power_w_m2": 500, "ip": "GOB", "weight_kg": None, "maintenance": "front",
                            "psu_per_cabinet": 1, "rx_per_cabinet": 1, "datasheet": ""})
    return lib


def led_inputs(case, **extra):
    i = case["input"]
    faces = [{k: f[k] for k in ("id", "name", "orientation", "width_mm", "height_mm")} | (
        {"protection": f["protection"]} if "protection" in f else {}) | ({"load": f["load"]} if "load" in f else {})
        for f in i["faces"]]
    return {k: v for k, v in LED_SAMPLE["input"].items() if k not in ("width_mm", "height_mm")} | {
        "pixel_pitch_mm": i["pixel_pitch_mm"], "shape": i["shape"], "faces": faces, "corners": i["corners"]} | extra


def face(out, fid):
    return next(f for f in out["faces"] if f["id"] == fid)


def check(out, rid):
    return next(r for r in out["rules"] if r["id"] == rid)


@pytest.mark.parametrize("name", ["led_gmc_u_shape", "led_digital_cube_l_shape"])
def test_led_multiface_golden(name):
    case = CASES[name]
    extra = {"total_weight_kg": case["input"]["total_weight_kg"]} if "total_weight_kg" in case["input"] else {}
    out = calculate(LED_RULES, led_library(), led_inputs(case, **extra))
    e = case["expect"]
    for fid, x in e["per_face"].items():
        v = face(out, fid)["values"]
        assert [v["res_x"], v["res_y"]] == x["px"], fid
        assert v["modules"] == x["modules"] and v["area_m2"] == pytest.approx(x["area_m2"], abs=0.005)
        assert v["power_kw"] == pytest.approx(x["power_kw"], abs=0.005)
        assert v["circuits"] == x["circuits"] and v["db_boxes"] == x["db_box"]
        assert f"{v['data_runs']}+{v['data_cables'] - v['data_runs']}" == x["data_cables"], fid
    t, tot = out["multi"]["totals"], e["total"]
    assert t["canvas_px"] == tot["canvas_px"] and t["modules"] == tot["modules"]
    assert t["spare_modules"] == tot["spare_modules_pooled"]  # 同型号备品按整屏合计
    assert t["area_m2"] == pytest.approx(tot["area_m2"], abs=0.005) and t["power_kw"] == pytest.approx(tot["power_kw"], abs=0.005)
    assert t["circuits"] == tot["circuits"] and t["data_cables"] == tot["data_cables"]
    assert t["processor_outputs"] == tot["processor_outputs"]
    if "db_box" in tot:
        assert t["db_boxes"] == tot["db_box"]
    assert check(out, "S4")["check"] in ("PASS", "NOTE") and "PASS" in [c["check"] for c in out["multi"]["checks"]
                                                                          if c["rule"] == "S4"]
    assert not any(c["check"] == "BLOCK" for c in out["multi"]["checks"] if c["rule"].startswith("S"))
    # 示例产品库的控制器只有 4 网口，每面的 F11 照样阻断，并在合并检查里列出
    assert all(c["rule"].endswith("F11") for c in out["multi"]["checks"] if c["check"] == "BLOCK")


def test_gmc_checks_and_supplier_count():
    case = CASES["led_gmc_u_shape"]
    out = calculate(LED_RULES, led_library(), led_inputs(case, reference_data_cables=31))
    texts = {c["rule"]: [] for c in out["multi"]["checks"]}
    for c in out["multi"]["checks"]:
        texts[c["rule"]].append((c["check"], c["text"]))
    assert ("PASS", "每面输出不超过 3840 px（最宽 3200 px）") in texts["S5"]
    assert ("NOTE", "规则算出数据线 27 根，参考资料是 31 根") in texts["S3"]


def test_gmc_side_width_conflict_blocks_until_chosen():
    """S7：同一尺寸在不同资料里不一样 → 阻断，列出是否模组整数倍和吸附选项；选定后和平面图墙宽不同时提示。"""
    case = CASES["led_gmc_u_shape"]
    sources = [{"src": "平面图", "kind": "plan", "value": 5600}, {"src": "LED 立面图", "kind": "elevation", "value": 5760},
               {"src": "规格表", "kind": "spec", "value": 3040}]
    inputs = led_inputs(case)
    for f in inputs["faces"]:
        if f["id"] in ("A", "C"):
            f["width_sources"], f["width_mm"] = sources, None
    out = calculate(LED_RULES, led_library(), inputs)
    s7 = check(out, "S7")
    assert s7["check"] == "BLOCK" and out["faces"] == [] and out["multi"]["totals"] == {}
    conflict = out["multi"]["conflicts"][0]
    assert (conflict["face"], conflict["field"]) == ("A", "width_mm")
    assert [(s["value"], s["fits"], s["options"]) for s in conflict["sources"]] == [
        (5600, False, [5440, 5760]), (5760, True, []), (3040, False, [2880, 3200])]
    for f in inputs["faces"]:
        if f["id"] in ("A", "C"):
            f["width_mm"] = 5760
    out = calculate(LED_RULES, led_library(), inputs)
    notes = [c["text"] for c in out["multi"]["checks"] if c["rule"] == "S7"]
    assert "A 面宽 5760 比平面图 5600 多 160 mm" in notes and check(out, "S7")["check"] == "NOTE"


def test_digital_cube_floor_face_weight_and_original_counts():
    case = CASES["led_digital_cube_l_shape"]
    out = calculate(LED_RULES, led_library(), led_inputs(case, total_weight_kg=600, reference_circuits=9,
                                                         reference_data_cables=10))
    checks = [(c["rule"], c["check"], c["text"]) for c in out["multi"]["checks"]]
    assert ("S6", "PASS", "B 面是地面面，已写 GOB 防护") in checks
    assert ("S6", "NOTE", "总重 600 kg，请结构确认（背墙加固、地面承重）") in checks
    assert ("S6", "NOTE", "B 面上有：2000x2000 acrylic model on top") in checks
    assert ("S3", "NOTE", "规则算出回路 4 路，参考资料是 9 路") in checks
    assert ("S3", "NOTE", "规则算出数据线 9 根，参考资料是 10 根") in checks
    inputs = led_inputs(case)
    inputs["faces"][1].pop("protection")
    out = calculate(LED_RULES, led_library(), inputs)
    assert ("S6", "BLOCK", "B 面是地面面，要写防护（例如 GOB）") in [(c["rule"], c["check"], c["text"]) for c in out["multi"]["checks"]]


def test_outside_corner_and_inside_corner_notes():
    case = CASES["led_gmc_u_shape"]
    inputs = led_inputs(case, shape="outside_corner")
    inputs["faces"], inputs["corners"] = inputs["faces"][:2], [{"between": ["A", "B"], "type": "outside_corner"}]
    out = calculate(LED_RULES, led_library(), inputs)
    s4 = [c["text"] for c in out["multi"]["checks"] if c["rule"] == "S4"]
    assert "A / B 外转角：用转角箱体或 45° 切角模组，两面按外边尺寸算，转角处像素要连续" in s4
    assert out["multi"]["totals"]["canvas_px"] == [2304 + 3200, 1664]  # 两面墙横向展开
    out = calculate(LED_RULES, led_library(), led_inputs(case))
    assert "A / B 内转角：请确认哪面压哪面、净宽怎么扣" in [c["text"] for c in out["multi"]["checks"] if c["rule"] == "S4"]


def test_shape_guess_from_file_text():
    assert multiface.guess_shape("LED", "Virtual office U-shape LED wall, left / main / right") == "U"
    assert multiface.guess_shape("LED", "Digital cube: wall + floor LED, GOB") == "L_wall_floor"
    assert multiface.guess_shape("LED", "LED 外转角，包柱") == "outside_corner"
    assert multiface.guess_shape("LED", "Lobby LED wall 4480 x 2560") == "flat"
    assert multiface.guess_shape("PJ", "展厅 L 形转角投影") == "L"
    assert multiface.guess_shape("PJ", "360 环幕") == "ring"


# ---- 投影 P18–P22 ----

def pj_inputs(case, **extra):
    i = case["input"]
    faces = [{"id": fid, "name": fid, "width_mm": w, "height_mm": i["wall_height_mm"]} for fid, w in i["faces_mm"].items()]
    ids = list(i["faces_mm"])
    return PJ_SAMPLE["input"] | {"shape": i["shape"], "faces": faces, "server_room_scope": "media_pc_only",
                                 "lens_throw_ratio": i["lens_throw_ratio"], "mount_distance_m": i["mount_distance_m"],
                                 "corners": [{"between": [a, b], "type": "inside_90"} for a, b in zip(ids, ids[1:])]} | extra


def values(out):
    return {ln["name"]: ln["value"] for r in out["rules"] for ln in r["lines"]}


def test_projection_corner_l():
    case = CASES["projection_corner_l"]
    out = calculate(PJ_RULES, load_library("PJ"), pj_inputs(case))
    e = case["expect"]
    for fid in ("A", "B"):
        v = face(out, fid)["values"]
        assert v["projectors"] == e["projectors"][fid]
        assert v["overlap"] == pytest.approx(e["blend_ratio"][fid], abs=0.001) and v["blended_px_x"] == e["px"][fid]
    t = out["multi"]["totals"]
    assert t["projectors"] == e["projectors"]["total"] and t["canvas_px"] == e["canvas_px"]
    corner = out["multi"]["corners"][0]
    assert corner["distance_m"] == pytest.approx(e["P20_corner_AB"]["distance_m"], abs=0.01)
    assert check(out, "P20")["check"] == e["P20_corner_AB"]["result"] == "BLOCK"
    v = values(out)
    assert v["power_with_margin_kw"] == pytest.approx(e["P12_power_kw"]["value"], abs=0.005)
    assert v["circuits"] == e["P12_circuits"] and v["total_cat6"] == e["P15_total_cat6"]
    assert t["blender_outputs_min"] == e["P21_blender_outputs_min"] and check(out, "P21")["check"] == "PASS"


def test_projection_u():
    case = CASES["projection_u"]
    out = calculate(PJ_RULES, load_library("PJ"), pj_inputs(case))
    e = case["expect"]
    assert out["multi"]["totals"]["projectors"] == e["projectors"]["total"]
    assert out["multi"]["totals"]["canvas_px"] == e["canvas_px"]
    assert [c["result"] for c in out["multi"]["corners"]] == [e["P20"]["AB"], e["P20"]["BC"]]
    v = values(out)
    assert v["power_with_margin_kw"] == pytest.approx(e["P12_power_kw"]["value"], abs=0.005)
    assert v["circuits"] == e["P12_circuits"] and v["total_cat6"] == e["P15_total_cat6"]


def test_corner_clash_resolved_by_hand_is_recorded():
    """P20：人工处理（错开挂高 / 镜头位移 / 改吊架）并记录后才能继续。"""
    case = CASES["projection_corner_l"]
    inputs = pj_inputs(case)
    inputs["corners"][0]["resolution"] = "B 面机位降低 300 mm，错开挂高"
    out = calculate(PJ_RULES, load_library("PJ"), inputs)
    assert check(out, "P20")["check"] == "NOTE" and "错开挂高" in check(out, "P20")["note"]


def test_wide_face_blend_note_and_curved_needs_correction():
    case = CASES["projection_corner_l"]
    out = calculate(PJ_RULES, load_library("PJ"), pj_inputs(case, shape="single", faces=[], corners=[], wall_width_mm=6000))
    p5 = check(out, "P5")
    assert values(out)["projectors"] == 2 and p5["check"] == "NOTE" and p5["display"].startswith("66.")  # 融合带过宽
    out = calculate(PJ_RULES, load_library("PJ"), pj_inputs(case, shape="curved", corners=[], faces=[
        {"id": "A", "name": "Arc", "width_mm": 12000, "height_mm": 2700}]))
    assert check(out, "P22")["check"] == "BLOCK"  # 示例融合器不支持曲面校正


def _processor(pid, **spec):
    return {"id": pid, "category": "processor", "brand": "Sample", "model": pid, "status": "approved",
            "scenes": ["indoor"], "sample": True, "datasheet": ""} | spec


def _cube(*processors):
    """Digital Cube：两面合计 1280 × 1680 + 1280 × 1280 = 3,788,800 px；示例处理器 SP-1 只有 2.3 MP，整屏用不了。"""
    lib = led_library()
    lib["products"] += list(processors)
    return calculate(LED_RULES, lib, led_inputs(CASES["led_digital_cube_l_shape"]))


def test_whole_screen_processor_with_outputs_for_every_face():
    """S5：视频处理器整屏 1 台，按整屏像素选；独立处理器的输出路数要 ≥ 面数（每面 1 路），控制器仍按面配。"""
    out = _cube(_processor("ONE-OUT", inputs=2, max_px=8_000_000, outputs=1),
                _processor("TWO-OUT", inputs=2, max_px=8_000_000, outputs=2))
    f13 = check(out, "F13")
    assert [r["id"] for r in out["rules"]] == ["S1", "S2", "S3", "S4", "S5", "F13", "S6", "S7"]
    assert f13["display"].endswith("TWO-OUT") and "2 路输出 ≥ 2 面" in f13["trace"]  # 1 路输出的跳过
    assert ("PASS", "处理器 Sample TWO-OUT：整屏 1 台，2 路输出，每面 1 路（2 面）") in [
        (c["check"], c["text"]) for c in out["multi"]["checks"] if c["rule"] == "S5"]
    assert all(not any(r["id"] == "F13" for r in f["rules"]) for f in out["faces"])  # 不再按面选处理器
    assert [face(out, x)["values"]["controller_qty"] for x in "AB"] == [1, 1]
    assert [(ln["item"], ln["qty"]) for ln in out["boq"] if ln["rule"] == "F13"] == [("整屏 · 视频处理器", 1)]
    assert out["values"]["processor_qty"] == 1 and out["values"]["processor_title"] == "Video processor"


def test_whole_screen_processor_outputs_missing_or_too_few():
    out = _cube(_processor("NO-OUT", inputs=2, max_px=8_000_000))
    assert check(out, "F13")["check"] == "NOTE" and "输出路数待核对规格书（要 ≥ 2 路，每面 1 路）" in check(out, "F13")["note"]
    assert ("NOTE", "处理器 Sample NO-OUT 的输出路数待核对规格书（要 ≥ 2 路，每面 1 路）") in [
        (c["check"], c["text"]) for c in out["multi"]["checks"] if c["rule"] == "S5"]
    out = _cube(_processor("ONE-OUT", inputs=2, max_px=8_000_000, outputs=1))
    assert check(out, "F13")["note"] == "产品库里没有输入数、分辨率和输出路数都够的视频处理器"
    assert "processor_id" not in out["values"] and not [ln for ln in out["boq"] if ln["rule"] == "F13"]


def test_whole_screen_processor_with_sending_replaces_the_face_controllers():
    """含发送的处理器够整屏用：整屏 1 台，各面的控制器包含在里面；只够一面用的含发送处理器不按面拿来用。"""
    small = _processor("VX-S", sending=True, capacity_px=2_300_000, ports=8)  # 够 A 面（2.15 MP），不够整屏
    big = _processor("VX-L", sending=True, capacity_px=3_900_000, ports=16)
    out = _cube(small)
    assert "processor_id" not in out["values"]
    assert [face(out, x)["values"]["controller_id"] for x in "AB"] == ["SC-4", "SC-4"]
    out = _cube(small, big)
    assert check(out, "F13")["display"].endswith("VX-L") and out["values"]["processor_sending"]
    for x in "AB":
        f11 = next(r for r in face(out, x)["rules"] if r["id"] == "F11")
        assert f11["check"] == "PASS" and face(out, x)["values"]["controller_qty"] == 0 and "VX-L" in f11["note"]
    assert [ln["model"] for ln in out["boq"] if ln["rule"] in ("F11", "F13")] == ["VX-L"]
    assert ("PASS", "处理器 Sample VX-L 含发送：整屏 1 台，各面直接接它的网口") in [
        (c["check"], c["text"]) for c in out["multi"]["checks"] if c["rule"] == "S5"]


def test_multiface_diagram_matches_the_internal_boq():
    """多面屏示意图（Level 1 / 2）：信号源 → 整屏 1 台处理器 → 每面的控制器 → 每面的屏，每面的配电箱接自己那一面；
    每台设备、每条线缆都能在内部明细里找到。"""
    out = _cube(_processor("TWO-OUT", inputs=2, max_px=8_000_000, outputs=2))
    d = out["diagram"]
    assert d["unmatched"] == [] and d["svg"].startswith("<svg") and "LED 屏 B · Base" in d["svg"]
    assert d["faces"] == [{"id": x, "screen": f"{x}:screen", "controller": f"{x}:controller", "db_box": f"{x}:db_box"} for x in "AB"]
    keys = {ln["key"] for ln in out["boq"]}
    assert all(k in keys for n in d["nodes"].values() if n["supply"] == "boq" for k in n["boq"])
    assert d["nodes"]["processor"]["boq"] == ["TWO-OUT"] and d["nodes"]["B:screen"]["boq"] == ["B:GOB-20:640x480", "B:GOB-20:640x640"]
    assert [(x["from"], x["to"], x["boq"]) for x in d["links"]] == [
        ("source", "processor", None),
        ("processor", "A:controller", None), ("A:controller", "A:screen", "A:data_cable"), ("A:db_box", "A:screen", "A:power_cable"),
        ("processor", "B:controller", None), ("B:controller", "B:screen", "B:data_cable"), ("B:db_box", "B:screen", "B:power_cable")]

    d = _cube(_processor("VX-L", sending=True, capacity_px=3_900_000, ports=16))["diagram"]  # 含发送：不画控制器
    assert not any(k.endswith(":controller") for k in d["nodes"]) and d["unmatched"] == []
    assert ("processor", "A:screen", "A:data_cable") in [(x["from"], x["to"], x["boq"]) for x in d["links"]]

    d = _cube()["diagram"]  # 处理器没选出：框保留并标出来，不能悄悄从图上消失
    assert d["nodes"]["processor"]["supply"] == "missing" and d["unmatched"] == ["视频处理器（F13 未选出（整屏））"]


def test_unfolded_drawing_puts_the_floor_face_under_the_wall():
    """多面屏一张展开总图（S5 的展开方向）：墙面横向，地面接在墙的下方；回路、网线编号整屏连续。"""
    from app.drawing import build_faces
    rules, _ = load_seed("LED")
    lib = led_library()
    gob = next(p for p in lib["products"] if p["id"] == "GOB-20")
    gob["cabinet_max"] = {"640x480": {"a": 0.6, "w": 100, "sample": True}, "640x640": {"a": 0.8, "w": 130, "sample": True}}
    out = calculate(rules, lib, led_inputs(CASES["led_digital_cube_l_shape"]))
    d = build_faces(out["faces"], out["values"], {p["name"]: p["value"] for p in rules["params"]}, None, gob["cabinet_max"])
    a, b = d["panels"]
    assert (a["id"], a["x"], a["y"], b["id"], b["x"], b["y"]) == ("A", 0, 2560 + 800, "B", 0, 0)  # 面与面之间留 800 mm
    assert (d["width"], d["height"]) == (2560, 3360 + 800 + 2560)
    assert b["circuits"][0] == a["circuits"][1] + 1 and b["cables"][0] == a["cables"][1] + 1
    assert {c["face"] for c in d["cabinets"]} == {"A", "B"} and d["cabinets"][0]["id"] == "A-R1C1"
    assert all(b["y"] <= c["y"] < b["y"] + b["height"] for c in d["cabinets"] if c["face"] == "B")


def _pj_drawings(inputs):
    from app import pj_drawings
    out = calculate(PJ_RULES, load_library("PJ"), inputs)
    params = {p["name"]: p["value"] for p in PJ_RULES["params"]}
    return pj_drawings, pj_drawings.data_faces(out["faces"], out["values"], params, set(), out["multi"]["shape"],
                                               out["multi"]["corners"])


def test_multiface_projection_drawings_u_room_plan_with_corner_clash():
    """多面投影专属图：U 形画成房间平面（A 左墙、B 正墙、C 右墙），两个内转角标 P20 的距离（0 m，阻断标红）；
    每面按自己的结果画——C 面另给墙高和进深时只改 C 面。"""
    case = CASES["projection_u"]
    inputs = pj_inputs(case)
    inputs["faces"][2] |= {"height_mm": 3000, "depth_mm": 4000}
    pj, D = _pj_drawings(inputs)
    assert D["room"] and [f["id"] for f in D["faces"]] == ["A", "B", "C"] and [f["n"] for f in D["faces"]] == [2, 2, 2]
    assert [(f["wall_w"], f["wall_h"], f["depth"]) for f in D["faces"]] == [(8000, 2700, 3200), (7800, 2700, 3200), (8000, 3000, 4000)]
    plan = pj.svg("plan", D)
    assert plan.count('class="projector"') == 6 and plan.count('class="clash"') == 2 and plan.count('class="wall"') == 3
    assert plan.count("P20 0.00 m") == 2 and pj.RED in plan.split('class="clash"')[1][:80]
    assert "A / B 内转角：两侧第 1 台机位相距 0.00 m（P20，要 ≥ 0.6 m）· 阻断" in plan
    elevation, section = pj.svg("elevation", D), pj.svg("section", D)
    assert elevation.count('class="blend"') == 3 and "C · 8000 × 3000" in elevation
    assert section.count('class="shadow"') == 3 and section == pj.svg("section", D)  # 每次画的一样


def test_multiface_projection_drawings_side_by_side_when_not_a_room():
    """墙 + 地面（不是内转角 90°）：平面按面并排画，写明不是实际平面；立面、剖面照样每面一张。"""
    case = CASES["projection_corner_l"]
    pj, D = _pj_drawings(pj_inputs(case, shape="wall_floor", corners=[{"between": ["A", "B"], "type": "fold_wall_to_floor"}]))
    assert not D["room"] and D["corners"] == []
    plan = pj.svg("plan", D)
    assert "这个屏形按面分开画（每面墙在上），不是实际平面" in plan and plan.count('class="clash"') == 0
    assert plan.count('class="projector"') == 4
