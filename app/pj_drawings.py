"""第 8 步：投影专属图——立面融合区图、平面机位图、剖面遮挡图（方案「专属图」）。

图上不另算数量：台数、单台画面宽高、融合带、机位距离、镜头高度、挡光距离都来自 P2–P10 的结果（手动改过的用手动值），
墙面、进深、天花、安装方式来自已确认的输入；这里只做几何摆放（第 i 台画面左边 = i × (w′ − o)，画面上下居中）。
页面、PDF、Word、JPG Boards 和演示稿用同一张 SVG。
多面投影（P18–P22）：每面按自己的 P2–P10 结果画；立面按面横向展开，剖面每面一张并排；平面在 L / U（内转角 90°）时
画成真实的房间平面，标出 P20 转角两侧第 1 台机位的距离，其它屏形按面并排画。
"""
from html import escape

from .i18n import tr

NAVY, MUTED, RED, ORANGE, BLUE, GREEN = "#15203A", "#6B6558", "#A23A2A", "#C2410C", "#2C5AA0", "#2F7A5B"
COLORS = ["#2C5AA0", "#2F7A5B", "#C2410C", "#7A4FA0", "#A0782C", "#1F7A8C", "#8C5A1F", "#D1495B"]
FONT = "-apple-system, 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif"
KINDS = ("elevation", "plan", "section")
NEED = ("projectors", "image_w_m", "image_h_m", "overlap_m", "distance_m", "wall_width_mm", "wall_height_mm")


def _mm(v) -> int:
    return int(round(float(v) * 1000))


def _m(mm: float) -> str:
    return f"{mm / 1000:.2f}".rstrip("0").rstrip(".")


def data(values: dict, params: dict, manual_inputs: set) -> dict | None:
    """三张图共用的数据（mm）。values：规则结果和输入（result["values"]）；params：规则参数；manual_inputs：手填的输入名。"""
    if any(values.get(k) in (None, "", "—") for k in NEED) or int(values["projectors"]) < 1:
        return None
    n = int(values["projectors"])
    img_w, img_h, overlap = _mm(values["image_w_m"]), _mm(values["image_h_m"]), _mm(values["overlap_m"]) if n > 1 else 0
    pitch = img_w - overlap  # 相邻两台画面（和机位）的中心间距
    wall_w, wall_h = int(values["wall_width_mm"]), int(values["wall_height_mm"])
    depth = values.get("available_depth_mm")
    ceiling = values.get("ceiling_height_mm")
    mount_h = values.get("mount_height_m")
    within = values.get("occlusion_within_m")
    return {
        "n": n, "wall_w": wall_w, "wall_h": wall_h, "img_w": img_w, "img_h": img_h, "overlap": overlap,
        "overlap_pct": float(values.get("overlap_pct") or 0), "pitch": pitch,
        "lefts": [i * pitch for i in range(n)],  # 每台画面左边离墙左端
        "distance": _mm(values["distance_m"]), "depth": int(depth) if depth else None,
        "ceiling": int(ceiling) if ceiling else None, "mount_h": _mm(mount_h) if mount_h is not None else None,
        "person": _mm(params.get("person_height_m", 1.8)), "within": _mm(within) if within is not None else None,
        "mounting": values.get("mounting") or "", "lens": values.get("lens") or "", "throw": values.get("throw_ratio"),
        "model": values.get("projector_model") or "",
        "blend_ok": values.get("blend_check") in (None, "PASS"), "height_ok": values.get("height_check") in (None, "PASS"),
        "manual": sorted(manual_inputs & {"ceiling_height_mm", "mount_height_m", "available_depth_mm", "mount_distance_m"}),
    }


def _text(x, y, s, size=11, fill=NAVY, anchor="middle", weight="normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" '
            f'font-weight="{weight}">{escape(str(s))}</text>')


def _dim_h(x1, x2, y, label, color=MUTED, above=True) -> str:
    """水平尺寸线：两端短竖线，中间写尺寸。"""
    ty = y - 5 if above else y + 14
    return (f'<g class="dim"><line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="1"/>'
            f'<line x1="{x1:.1f}" y1="{y - 5:.1f}" x2="{x1:.1f}" y2="{y + 5:.1f}" stroke="{color}"/>'
            f'<line x1="{x2:.1f}" y1="{y - 5:.1f}" x2="{x2:.1f}" y2="{y + 5:.1f}" stroke="{color}"/>'
            + _text((x1 + x2) / 2, ty, label, 10.5, color) + "</g>")


def _dim_v(x, y1, y2, label, color=MUTED, left=True) -> str:
    tx = x - 6 if left else x + 6
    return (f'<g class="dim"><line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="1"/>'
            f'<line x1="{x - 5:.1f}" y1="{y1:.1f}" x2="{x + 5:.1f}" y2="{y1:.1f}" stroke="{color}"/>'
            f'<line x1="{x - 5:.1f}" y1="{y2:.1f}" x2="{x + 5:.1f}" y2="{y2:.1f}" stroke="{color}"/>'
            + _text(tx, (y1 + y2) / 2 + 4, label, 10.5, color, "end" if left else "start") + "</g>")


def _frame(title: str, width: int, height: int, body: str, foot: list[str], stamp: str) -> str:
    lines = "".join(_text(16, height - 14 - 16 * (len(foot) - 1 - i), t, 11, MUTED, "start") for i, t in enumerate(foot))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'font-family="{FONT}"><rect width="{width}" height="{height}" fill="#fff"/>'
            + _text(16, 24, title, 15, NAVY, "start", "700")
            + (_text(width - 16, 24, stamp, 10, MUTED, "end") if stamp else "")
            + body + lines + "</svg>")


def _span(d: dict) -> int:
    """一面墙在图上占的宽度（mm）：墙宽和画面总宽取大。"""
    return max(d["wall_w"], d["lefts"][-1] + d["img_w"])


def _elevation_body(d: dict, left: float, top: float, s: float) -> tuple[list[str], float]:
    """一面墙的立面（墙左上角在 left, top，比例 s）；返回图形和最低点。"""
    wh, ih = d["wall_h"] * s, d["img_h"] * s
    img_top = top + (d["wall_h"] - d["img_h"]) / 2 * s  # 画面上下居中；比墙高时上下各超出一点
    body = [f'<rect class="wall" x="{left}" y="{top}" width="{d["wall_w"] * s:.1f}" height="{wh:.1f}" fill="#F1EEE8" '
            f'stroke="{NAVY}" stroke-width="1.5"/>']
    blend = RED if not d["blend_ok"] else ORANGE
    for i in range(1, d["n"]):  # 融合带：第 i 台画面左边到第 i−1 台画面右边
        x1, x2 = left + d["lefts"][i] * s, left + (d["lefts"][i - 1] + d["img_w"]) * s
        body.append(f'<rect class="blend" x="{x1:.1f}" y="{img_top:.1f}" width="{x2 - x1:.1f}" height="{ih:.1f}" '
                    f'fill="{blend}" fill-opacity="0.22"/>')
    for i, x in enumerate(d["lefts"]):
        c = COLORS[i % len(COLORS)]
        body.append(f'<rect class="image" x="{left + x * s:.1f}" y="{img_top:.1f}" width="{d["img_w"] * s:.1f}" height="{ih:.1f}" '
                    f'fill="none" stroke="{c}" stroke-width="1.5" stroke-dasharray="6 3"/>')
        body.append(_text(left + (x + d["img_w"] / 2) * s, img_top + ih / 2 + 4, f"PJ-{i + 1}", 12, c, weight="700"))
    body.append(_dim_h(left, left + d["img_w"] * s, img_top - 14, tr(f"单台画面宽 {d['img_w']}", f"Image width {d['img_w']}")))
    if d["n"] > 1:
        x1, x2 = left + d["lefts"][1] * s, left + d["img_w"] * s
        body.append(_dim_h(x1, x2, img_top - 40, tr(f"融合带 {d['overlap_pct']:.1f} % ≈ {d['overlap']} × {d['n'] - 1}",
                                                     f"Blend {d['overlap_pct']:.1f} % ≈ {d['overlap']} × {d['n'] - 1}"), blend))
    bottom = max(top + wh, img_top + ih)
    body.append(_dim_h(left, left + d["wall_w"] * s, bottom + 22, tr(f"墙宽 {d['wall_w']}", f"Wall width {d['wall_w']}"),
                       NAVY, above=False))
    body.append(_dim_v(left - 8, top, top + wh, str(d["wall_h"]), NAVY))
    return body, bottom


def elevation_svg(d: dict, stamp: str = "") -> str:
    """立面融合区图：墙面、每台画面（虚线框）、相邻画面的融合带（橙色），标墙宽、单台画面宽、融合带宽和比例。"""
    W, left, top = 880, 64, 92
    s = (W - 2 * left) / _span(d)
    body, bottom = _elevation_body(d, left, top, s)
    over = (d["img_h"] - d["wall_h"]) / 2
    foot = [tr(f"{d['n']} 台横向排开；相邻画面重叠 ≈ {d['overlap']} mm（P5，{d['overlap_pct']:.1f} %）；橙色是融合区。",
               f"{d['n']} projectors side by side; adjacent images overlap ≈ {d['overlap']} mm (P5, {d['overlap_pct']:.1f} %); "
               "the orange areas are the blend zones."),
            tr(f"单台画面 {d['img_w']} × {d['img_h']}" + (f"，上下各超出墙面 {over:.0f}" if over > 0 else "") + " · 单位 mm",
               f"Each image {d['img_w']} × {d['img_h']}" + (f", {over:.0f} beyond the wall top and bottom" if over > 0 else "")
               + " · units mm")]
    if not d["blend_ok"]:
        foot.append(tr("融合带不在 15–30 % 范围内（P5），换镜头或改台数", "Blend outside 15–30 % (P5): change the lens or the count"))
    return _frame(tr("立面融合区图", "Elevation · blend zones"), W, int(bottom + 50 + 16 * len(foot)), "".join(body), foot, stamp)


def _plan_body(d: dict, left: float, top: float, s: float) -> tuple[list[str], float, bool]:
    """一面墙的平面（墙在上，左端在 left, top，比例 s）；返回图形、最远处（px）和机位是否超出进深。"""
    depth = d["depth"] or 0
    far = max(depth, d["distance"]) * s
    lens_y = top + d["distance"] * s
    over = d["depth"] is not None and d["distance"] > d["depth"]
    body = [f'<line class="wall" x1="{left}" y1="{top}" x2="{left + d["wall_w"] * s:.1f}" y2="{top}" stroke="{NAVY}" stroke-width="4"/>',
            _text(left + d["wall_w"] * s / 2, top - 8, tr(f"投影墙 · {d['wall_w']}", f"Projection wall · {d['wall_w']}"), 11, NAVY)]
    if d["depth"]:
        y = top + depth * s
        body.append(f'<line class="depth" x1="{left}" y1="{y:.1f}" x2="{left + d["wall_w"] * s:.1f}" y2="{y:.1f}" '
                    f'stroke="{MUTED}" stroke-dasharray="8 4"/>')
        body.append(_text(left + d["wall_w"] * s, y + 14, tr("可用进深边界", "Available depth limit"), 10.5, MUTED, "end"))
    for i, x in enumerate(d["lefts"]):
        c = COLORS[i % len(COLORS)]
        cx = left + (x + d["img_w"] / 2) * s
        body.append(f'<polygon class="cone" points="{cx:.1f},{lens_y:.1f} {left + x * s:.1f},{top} {left + (x + d["img_w"]) * s:.1f},{top}" '
                    f'fill="{c}" fill-opacity="0.08" stroke="{c}" stroke-width="1"/>')
        body.append(f'<rect class="projector" x="{cx - 9:.1f}" y="{lens_y:.1f}" width="18" height="12" rx="2" '
                    f'fill="{RED if over else c}"/>')
        body.append(_text(cx, lens_y + 26, f"PJ-{i + 1}", 10.5, c, weight="700"))
    body.append(_dim_v(left - 8, top, lens_y, _m(d["distance"]) + " m", NAVY))
    if d["depth"]:
        body.append(_dim_v(left + d["wall_w"] * s + 8, top, top + depth * s, _m(depth) + " m", MUTED, left=False))
    if d["n"] > 1:
        c1, c2 = left + (d["img_w"] / 2) * s, left + (d["pitch"] + d["img_w"] / 2) * s
        body.append(_dim_h(c1, c2, lens_y + 46, tr(f"中心间距 {d['pitch']}", f"Spacing {d['pitch']}"), MUTED, above=False))
    return body, far, over


def plan_svg(d: dict, stamp: str = "") -> str:
    """平面机位图（俯视）：墙在上，镜头前端离墙 d（P3 / P4），每台到自己画面两端的投射锥，可用进深边界。"""
    W, left, top = 880, 70, 86
    s = (W - 2 * left) / _span(d)
    depth = d["depth"] or 0
    body, far, over = _plan_body(d, left, top, s)
    mount = {"ceiling": tr("吊顶", "ceiling"), "floor": tr("落地", "floor"), "wall": tr("壁挂", "wall")}.get(d["mounting"], d["mounting"])
    back = tr(f"镜头前端后方余 {_m(depth - d['distance'])} m（含机身）", f"{_m(depth - d['distance'])} m left behind the lens (incl. body)") \
        if d["depth"] and not over else ""
    foot = [tr(f"镜头前端离墙 {_m(d['distance'])} m（P3 / P4）" + (f"；可用进深 {_m(depth)} m" if d["depth"] else ""),
               f"Lens front {_m(d['distance'])} m from the wall (P3 / P4)" + (f"; available depth {_m(depth)} m" if d["depth"] else "")),
            " · ".join(x for x in [tr(f"{d['n']} 台{mount}安装", f"{d['n']} × {mount}-mounted"), d["lens"],
                                   tr(f"中心间距 {d['pitch']} mm", f"spacing {d['pitch']} mm") if d["n"] > 1 else "", back] if x)]
    if over:
        foot.append(tr("机位超出可用进深（P3），换短焦镜头", "The projector position is beyond the available depth (P3): use a shorter-throw lens"))
    return _frame(tr("平面机位图", "Plan · projector positions"), W, int(top + far + 70 + 16 * len(foot)), "".join(body), foot, stamp)


def section_svg(d: dict, stamp: str = "") -> str:
    """剖面遮挡图（侧视）：墙在左，镜头在离墙 d、高 H 处；光线打到画面顶边和底边（地面）；
    人高 h 时离墙 P10 算出的距离以内会挡光（灰色三角）。"""
    W, H0 = 880, 330
    left, floor = 120, 60 + H0
    s = min(H0 / _section_top(d), (W - left - 220) / _section_far(d))
    W = int(max(600, left + _section_far(d) * s + 200))  # 宽度按内容收窄（演示稿里和平面图并排）
    body = _section_body(d, left, floor, s)
    foot = _section_foot(d)
    return _frame(tr("剖面遮挡图", "Section · shadow check"), W, int(floor + 128 + 16 * len(foot)), "".join(body), foot, stamp)


def _section_top(d: dict) -> float:
    return max(d["wall_h"], d["ceiling"] or 0, d["mount_h"] or 0, (d["wall_h"] + d["img_h"]) / 2) + 200


def _section_far(d: dict) -> float:
    return max(d["depth"] or 0, d["distance"]) + 600


def _section_body(d: dict, left: float, floor: float, s: float) -> list[str]:
    """一面墙的剖面（墙在 left，地面在 floor，比例 s）。"""
    far_mm = _section_far(d)
    X = lambda mm: left + mm * s  # noqa: E731
    Y = lambda mm: floor - mm * s  # noqa: E731
    img_top = (d["wall_h"] + d["img_h"]) / 2
    img_bottom = max((d["wall_h"] - d["img_h"]) / 2, 0)  # 画面底边：P10 取地面
    body = [f'<line class="floor" x1="{left - 30}" y1="{floor}" x2="{X(far_mm):.1f}" y2="{floor}" stroke="{NAVY}" stroke-width="2"/>',
            _text(X(far_mm), floor + 16, tr("地面", "Floor"), 10.5, MUTED, "end"),
            f'<line class="wall" x1="{left}" y1="{floor}" x2="{left}" y2="{Y(d["wall_h"]):.1f}" stroke="{NAVY}" stroke-width="4"/>',
            f'<line class="image" x1="{left + 4}" y1="{Y(img_bottom):.1f}" x2="{left + 4}" y2="{Y(min(img_top, d["wall_h"])):.1f}" '
            f'stroke="{BLUE}" stroke-width="4"/>',
            _dim_v(left - 34, Y(0), Y(d["wall_h"]), tr(f"墙高 {_m(d['wall_h'])} m", f"Wall {_m(d['wall_h'])} m"), NAVY)]
    if d["ceiling"]:
        body.append(f'<line class="ceiling" x1="{left}" y1="{Y(d["ceiling"]):.1f}" x2="{X(far_mm):.1f}" y2="{Y(d["ceiling"]):.1f}" '
                    f'stroke="{MUTED}" stroke-dasharray="8 4"/>')
        body.append(_text(X(far_mm), Y(d["ceiling"]) - 6, tr(f"天花 {_m(d['ceiling'])} m", f"Ceiling {_m(d['ceiling'])} m")
                          + (tr("（手填）", " (manual)") if "ceiling_height_mm" in d["manual"] else ""), 10.5, MUTED, "end"))
    if d["mount_h"] is not None:
        lx, ly = X(d["distance"]), Y(d["mount_h"])
        if d["within"] is not None and d["within"] > 0:  # 挡光区：离墙 within 以内、低于光线的人会挡光
            ph = min(d["person"], d["mount_h"])
            body.append(f'<polygon class="shadow" points="{left},{floor} {X(d["within"]):.1f},{floor} {X(d["within"]):.1f},{Y(ph):.1f}" '
                        f'fill="{MUTED}" fill-opacity="0.25"/>')
            px = X(d["within"])  # 人：站在挡光区边上
            body.append(f'<g class="person" stroke="{NAVY}" stroke-width="1.5" fill="none">'
                        f'<circle cx="{px:.1f}" cy="{Y(d["person"]) + 7:.1f}" r="6"/>'
                        f'<line x1="{px:.1f}" y1="{Y(d["person"]) + 13:.1f}" x2="{px:.1f}" y2="{floor - 0.5 * d["person"] * s:.1f}"/>'
                        f'<line x1="{px:.1f}" y1="{floor - 0.5 * d["person"] * s:.1f}" x2="{px - 6:.1f}" y2="{floor}"/>'
                        f'<line x1="{px:.1f}" y1="{floor - 0.5 * d["person"] * s:.1f}" x2="{px + 6:.1f}" y2="{floor}"/></g>')
            body.append(_dim_h(left, X(d["within"]), floor + 30, tr(f"{_m(d['within'])} m 内会挡光", f"Shadow within {_m(d['within'])} m"),
                               RED, above=False))
        for y_mm in (img_top, img_bottom):
            body.append(f'<line class="ray" x1="{lx:.1f}" y1="{ly:.1f}" x2="{left + 4}" y2="{Y(y_mm):.1f}" stroke="{ORANGE}" '
                        f'stroke-width="1.2"/>')
        body.append(f'<rect class="projector" x="{lx:.1f}" y="{ly - 7:.1f}" width="34" height="14" rx="2" fill="{NAVY}"/>')
        body.append(_text(lx + 40, ly + 4, tr(f"机位高 {_m(d['mount_h'])} m", f"Lens height {_m(d['mount_h'])} m")
                          + (tr("（手填）", " (manual)") if "mount_height_m" in d["manual"] else ""), 10.5, NAVY, "start"))
    body.append(_dim_h(left, X(d["distance"]), floor + 58, tr(f"离墙 {_m(d['distance'])} m（镜头前端）",
                                                               f"{_m(d['distance'])} m from the wall (lens front)"), NAVY, above=False))
    if d["depth"]:
        body.append(_dim_h(left, X(d["depth"]), floor + 86, tr(f"可用进深 {_m(d['depth'])} m", f"Available depth {_m(d['depth'])} m"),
                           MUTED, above=False))
    return body


def _section_foot(d: dict) -> list[str]:
    foot = [tr(f"光线最低一条打到画面底边（地面）；人高 {_m(d['person'])} m 时，离墙 {_m(d['within'])} m 以内会挡光，在墙上留下人影（P10）。",
               f"The lowest ray reaches the image bottom (floor); a {_m(d['person'])} m tall person within {_m(d['within'])} m "
               "of the wall blocks the light and casts a shadow (P10).")] if d["within"] is not None else []
    if d["ceiling"] and d["mount_h"] is not None and d["mount_h"] > d["ceiling"]:
        foot.append(tr("机位高于天花，核对安装高度", "The lens is above the ceiling: check the mounting height"))
    if d["manual"]:
        foot.append(tr("手填的尺寸（没有剖面图）以现场复核为准", "Sizes filled in by hand (no section drawing) are subject to site checks"))
    return foot


# ---- 多面投影 ----

def data_faces(faces: list[dict], values: dict, params: dict, manual_inputs: set, shape: str, corners: list[dict]) -> dict | None:
    """多面投影三张图的数据：每面一份（和单面墙同样的结构，加面编号和名字），再加屏形和 P20 的转角结果。
    faces：多面投影结果里的每一面（values 是这面 P1–P10 的结果，inputs 是这面自己的墙宽、墙高、进深、镜头高）；
    values：整套方案的值（共用的输入：天花、安装方式、镜头型号…）；corners：P20 的结果（只有内转角 90° 才有）。"""
    out = []
    for f in faces:
        d = data(values | (f.get("inputs") or {}) | f["values"], params, manual_inputs)
        if d is None:
            return None
        named = f.get("name") and f["name"] != f["id"]
        out.append(d | {"id": f["id"], "label": f"{f['id']} · {f['name']}" if named else f["id"]})
    ids = [f["id"] for f in out]
    # 相邻两面之间都有 P20 的内转角：按真实房间画平面
    room = shape in ("L", "U") and [list(c["between"]) for c in corners] == [ids[i:i + 2] for i in range(len(ids) - 1)]
    return {"faces": out, "shape": shape, "corners": corners, "room": room,
            "clash_m": float(params.get("corner_clash_m") or 0)}


def _face_line(d: dict) -> str:
    return tr(f"{d['label']}：{d['n']} 台，单台画面 {d['img_w']} × {d['img_h']}"
              + (f"，融合带 {d['overlap_pct']:.1f} % ≈ {d['overlap']}" if d["n"] > 1 else "") + f"，镜头前端离墙 {_m(d['distance'])} m",
              f"{d['label']}: {d['n']} projectors, image {d['img_w']} × {d['img_h']}"
              + (f", blend {d['overlap_pct']:.1f} % ≈ {d['overlap']}" if d["n"] > 1 else "") + f", lens front {_m(d['distance'])} m from the wall")


def elevation_faces_svg(D: dict, stamp: str = "") -> str:
    """多面投影的立面：每面横向展开（不跨角投射，面与面之间留空），各画自己的画面和融合带，墙底对齐。"""
    faces, gap, left, top = D["faces"], 80, 64, 132
    W = max(880, 320 * len(faces) + 160)
    s = (W - 2 * left - gap * (len(faces) - 1)) / sum(_span(d) for d in faces)
    tallest = max(d["wall_h"] for d in faces)
    body, bottom, x = [], 0.0, left
    for d in faces:
        t = top + (tallest - d["wall_h"]) * s
        body.append(_text(x, top - 64, f"{d['label']} · {d['wall_w']} × {d['wall_h']}", 13, NAVY, "start", "700"))
        part, low = _elevation_body(d, x, t, s)
        body += part
        bottom, x = max(bottom, low), x + _span(d) * s + gap
    foot = [_face_line(d) for d in faces] + [tr(
        "每面单独排投影，不跨角投射；面与面之间的空白只为看得清 · 单位 mm",
        "Each face is laid out on its own, no projection across corners; gaps between faces are for legibility only · units mm")]
    if not all(d["blend_ok"] for d in faces):
        foot.append(tr("有面的融合带不在 15–30 % 范围内（P5），换镜头或改台数",
                       "A face's blend is outside 15–30 % (P5): change the lens or the count"))
    return _frame(tr("立面融合区图", "Elevation · blend zones"), W, int(bottom + 50 + 16 * len(foot)), "".join(body), foot, stamp)


def _room_walls(faces: list[dict]) -> list[tuple]:
    """L / U 房间平面（mm，y 向下）：第一面是左墙，从下往上走，每到内转角向右转 90°（房间在走向的右手边）。
    返回每面的（起点、走向、朝房间里的法线）；起点就是站在房间里看这面墙时的左端。"""
    pos, u, walls = (0.0, 0.0), (0.0, -1.0), []
    for d in faces:
        n = (-u[1], u[0])
        walls.append((pos, u, n))
        pos, u = (pos[0] + u[0] * d["wall_w"], pos[1] + u[1] * d["wall_w"]), n
    return walls


def plan_faces_svg(D: dict, stamp: str = "") -> str:
    """多面投影的平面：L / U（内转角 90°）画成房间平面，标 P20 转角两侧第 1 台机位的距离；其它屏形每面一张并排。"""
    faces = D["faces"]
    if not D["room"]:
        gap, left, top = 90, 70, 110
        W = max(880, 320 * len(faces) + 160)
        s = (W - 2 * left - gap * (len(faces) - 1)) / sum(_span(d) for d in faces)
        body, far, x = [], 0.0, left
        for d in faces:
            body.append(_text(x, top - 40, d["label"], 13, NAVY, "start", "700"))
            part, f_px, _ = _plan_body(d, x, top, s)
            body += part
            far, x = max(far, f_px), x + _span(d) * s + gap
        foot = [_face_line(d) for d in faces] + [tr("这个屏形按面分开画（每面墙在上），不是实际平面",
                                                    "This shape is drawn face by face (each wall on top), not as the real plan")]
        return _frame(tr("平面机位图", "Plan · projector positions"), W, int(top + far + 70 + 16 * len(foot)), "".join(body), foot, stamp)

    walls = _room_walls(faces)
    pts = []  # 每面每台机位（镜头前端）和画面两端，mm
    for d, (p0, u, n) in zip(faces, walls):
        row = []
        for x in d["lefts"]:
            a = (p0[0] + u[0] * x, p0[1] + u[1] * x)
            b = (p0[0] + u[0] * (x + d["img_w"]), p0[1] + u[1] * (x + d["img_w"]))
            c = (p0[0] + u[0] * (x + d["img_w"] / 2) + n[0] * d["distance"], p0[1] + u[1] * (x + d["img_w"] / 2) + n[1] * d["distance"])
            row.append((a, b, c))
        pts.append(row)
    (e0, eu, _), last = walls[-1], faces[-1]["wall_w"]  # 最后一面墙的终点
    xs = [w[0][0] for w in walls] + [e0[0] + eu[0] * last] + [c[0] for row in pts for _, _, c in row]
    ys = [w[0][1] for w in walls] + [e0[1] + eu[1] * last] + [c[1] for row in pts for _, _, c in row]
    W, margin, top = 880, 90, 70
    s = min((W - 2 * margin) / (max(xs) - min(xs) or 1), 520 / (max(ys) - min(ys) or 1))
    X = lambda v: margin + (v - min(xs)) * s  # noqa: E731
    Y = lambda v: top + (v - min(ys)) * s  # noqa: E731
    body = []
    for d, (p0, u, n), row in zip(faces, walls, pts):
        p1 = (p0[0] + u[0] * d["wall_w"], p0[1] + u[1] * d["wall_w"])
        body.append(f'<line class="wall" x1="{X(p0[0]):.1f}" y1="{Y(p0[1]):.1f}" x2="{X(p1[0]):.1f}" y2="{Y(p1[1]):.1f}" '
                    f'stroke="{NAVY}" stroke-width="4"/>')
        mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)  # 面的名字写在墙外侧
        anchor = "end" if n[0] > 0 else "start" if n[0] < 0 else "middle"
        body.append(_text(X(mid[0]) - n[0] * 12, Y(mid[1]) - n[1] * 14 + 4, f"{d['label']} · {d['wall_w']}", 11, NAVY, anchor, "700"))
        if d["depth"]:
            q0 = (p0[0] + n[0] * d["depth"], p0[1] + n[1] * d["depth"])
            q1 = (p1[0] + n[0] * d["depth"], p1[1] + n[1] * d["depth"])
            body.append(f'<line class="depth" x1="{X(q0[0]):.1f}" y1="{Y(q0[1]):.1f}" x2="{X(q1[0]):.1f}" y2="{Y(q1[1]):.1f}" '
                        f'stroke="{MUTED}" stroke-dasharray="8 4"/>')
        over = d["depth"] is not None and d["distance"] > d["depth"]
        for i, (a, b, c) in enumerate(row):
            col = COLORS[i % len(COLORS)]
            body.append(f'<polygon class="cone" points="{X(c[0]):.1f},{Y(c[1]):.1f} {X(a[0]):.1f},{Y(a[1]):.1f} {X(b[0]):.1f},{Y(b[1]):.1f}" '
                        f'fill="{col}" fill-opacity="0.08" stroke="{col}" stroke-width="1"/>')
            body.append(f'<circle class="projector" cx="{X(c[0]):.1f}" cy="{Y(c[1]):.1f}" r="6" fill="{RED if over else col}"/>')
            body.append(_text(X(c[0]) + n[0] * 16, Y(c[1]) + n[1] * 16 + 4, f"{d['id']}{i + 1}", 10, col, "middle", "700"))
    index = {d["id"]: k for k, d in enumerate(faces)}
    for c in D["corners"]:  # P20：转角两侧第 1 台机位（a 面最后一台、b 面第一台）
        a, b = c["between"]
        p, q = pts[index[a]][-1][2], pts[index[b]][0][2]
        col = {"BLOCK": RED, "NOTE": ORANGE}.get(c["result"], GREEN)
        body.append(f'<line class="clash" x1="{X(p[0]):.1f}" y1="{Y(p[1]):.1f}" x2="{X(q[0]):.1f}" y2="{Y(q[1]):.1f}" stroke="{col}" '
                    f'stroke-width="2" stroke-dasharray="4 3"/>')
        cx, cy = (X(p[0]) + X(q[0])) / 2, (Y(p[1]) + Y(q[1])) / 2
        body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="14" fill="none" stroke="{col}" stroke-width="2"/>')
        body.append(_text(cx, cy + 40, f"P20 {c['distance_m']:.2f} m", 11, col, "middle", "700"))  # 写在机位编号下面
    bottom = Y(max(ys))
    foot = [_face_line(d) for d in faces]
    for c in D["corners"]:
        a, b = c["between"]
        state = {"BLOCK": tr("阻断：错开挂高 / 镜头位移 / 改吊架，记录后才能继续", "blocked: stagger heights / lens shift / change mounts, and record it"),
                 "NOTE": tr(f"已人工处理：{c['resolution']}", f"resolved by hand: {c['resolution']}")}.get(c["result"], tr("通过", "OK"))
        foot.append(tr(f"{a} / {b} 内转角：两侧第 1 台机位相距 {c['distance_m']:.2f} m（P20，要 ≥ {D['clash_m']:g} m）· {state}",
                       f"{a} / {b} inside corner: first projectors {c['distance_m']:.2f} m apart (P20, needs ≥ {D['clash_m']:g} m) · {state}"))
    return _frame(tr("平面机位图", "Plan · projector positions"), W, int(bottom + 60 + 16 * len(foot)), "".join(body), foot, stamp)


def section_faces_svg(D: dict, stamp: str = "") -> str:
    """多面投影的剖面：每面一张并排（墙高、进深、镜头高可以不同），同一比例。"""
    faces, H0 = D["faces"], 330
    s = min(H0 / max(_section_top(d) for d in faces), 300 / max(_section_far(d) for d in faces))
    floor = 70 + max(_section_top(d) for d in faces) * s  # 高度按内容
    body, x = [], 120.0
    for d in faces:
        body.append(_text(x - 100, 48, d["label"], 13, NAVY, "start", "700"))
        body += _section_body(d, x, floor, s)
        x += _section_far(d) * s + 260
    W = int(x - 120)
    foot = [f"{d['id']} · {_section_foot(d)[0]}" for d in faces if _section_foot(d)]
    foot += list(dict.fromkeys(line for d in faces for line in _section_foot(d)[1:]))  # 共同的提示只写一次
    return _frame(tr("剖面遮挡图", "Section · shadow check"), W, int(floor + 128 + 16 * len(foot)), "".join(body), foot, stamp)


def svg(kind: str, d: dict, stamp: str = "") -> str:
    if "faces" in d:  # 多面投影
        return {"elevation": elevation_faces_svg, "plan": plan_faces_svg, "section": section_faces_svg}[kind](d, stamp)
    return {"elevation": elevation_svg, "plan": plan_svg, "section": section_svg}[kind](d, stamp)


def titles() -> dict:
    return {"elevation": tr("立面融合区图", "Elevation · blend zones"), "plan": tr("平面机位图", "Plan · projector positions"),
            "section": tr("剖面遮挡图", "Section · shadow check")}
