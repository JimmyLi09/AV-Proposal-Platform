"""投影业务线（第 7 步 / CR-7）：步骤类规则（步骤写在代码里，只改参数），以及产品库选型、内部明细和示意图。

顺序：先定单台画面（P1），选镜头、反推机位（P3），算实际画面（P4）和台数（P2），再核融合带、清晰度、亮度。
口径：投射距离一律从镜头前端量到投影面；V1 只算一排横装。
"""
import math
from decimal import Decimal

from ..i18n import tr
from ..products.library import active, name
from .expr import fmt

UPS_KVA = [Decimal(x) for x in ("1", "1.5", "2", "3", "5", "6", "10", "15", "20")]  # 常见 UPS 规格


def _n(x) -> str:
    return fmt(x)


def lens_pick(ctx: dict, catalog: dict) -> dict:
    """P3：可配镜头里取最短距离（投射比 × 画面宽）放得进可用进深、投射比最小的；填了投射比就用那款。
    安装距离：填了用实际值（被梁、空调卡住时），没填按最短距离。"""
    w, depth = ctx["single_w_m"], ctx["available_depth_mm"] / 1000
    lenses = catalog.get("lenses", [])
    wanted = ctx.get("lens_throw_ratio")
    if wanted is not None:
        lenses = [x for x in lenses if Decimal(str(x["throw_ratio"])) == wanted]
    fits = [x for x in lenses if Decimal(str(x["throw_ratio"])) * w <= depth]
    if not fits:
        return {"check": "BLOCK", "sample": True, "note": tr(
            f"没有放得进 {_n(depth)} m 进深的可配镜头（画面宽 {_n(w)} m）",
            f"No compatible lens fits the {_n(depth)} m depth (image width {_n(w)} m)")}
    lens = min(fits, key=lambda x: x["throw_ratio"])
    throw = Decimal(str(lens["throw_ratio"]))
    shortest = throw * w
    distance = ctx.get("mount_distance_m") or shortest
    out = {"lens": lens["model"], "lens_id": lens["id"], "throw_ratio": throw, "min_distance_m": shortest,
           "distance_m": distance}
    note = "" if distance <= depth else tr(f"安装距离 {_n(distance)} m 超过可用进深 {_n(depth)} m",
                                           f"Mount distance {_n(distance)} m is beyond the {_n(depth)} m depth")
    return {"outputs": out, "check": "NOTE" if note else "PASS", "note": note, "sample": lens.get("sample", False),
            "trace": tr(f"{_n(throw)} × {_n(w)} = {_n(shortest)} m ≤ 进深 {_n(depth)} m；按 {_n(distance)} m 安装",
                        f"{_n(throw)} × {_n(w)} = {_n(shortest)} m ≤ depth {_n(depth)} m; mounted at {_n(distance)} m")}


def occlusion(ctx: dict, catalog: dict) -> dict:
    """P10：从镜头（离墙 d、高 H）到画面底边（地面）画光线，人高 h 时离墙 d × h ÷ H 以内会挡光。"""
    d, height, person = ctx["distance_m"], ctx["mount_height_m"], ctx["person_height_m"]
    within = d * person / height if height > person else d
    return {"outputs": {"occlusion_within_m": within}, "check": "NOTE",
            "note": tr(f"人高 {_n(person)} m 时，离墙 {_n(within.quantize(Decimal('0.01')))} m 以内会挡光",
                       f"A {_n(person)} m tall person within {_n(within.quantize(Decimal('0.01')))} m of the wall casts a shadow"),
            "trace": f"{_n(d)} × {_n(person)} ÷ {_n(height)} = {_n(within.quantize(Decimal('0.01')))} m"}


def blender_pick(ctx: dict, catalog: dict) -> dict:
    """P11：2 台及以上必须用融合器，输出路数 ≥ 台数，按产品库顺序（首选在前）取第一款够用的。"""
    n = ctx["projectors"]
    if n < 2:
        return {"outputs": {"blender": "—", "blender_id": "", "blender_qty": Decimal(0), "blender_outputs": Decimal(0)},
                "check": "PASS", "note": tr("单台不用融合器", "A single projector needs no blender"), "trace": "n = 1"}
    for b in catalog.get("blenders", []):
        if n <= b["outputs"]:
            return {"outputs": {"blender": b["model"], "blender_id": b["id"], "blender_qty": Decimal(1),
                                "blender_outputs": Decimal(b["outputs"])},
                    "check": "PASS", "sample": b.get("sample", False),
                    "trace": tr(f"{_n(n)} 台 ≤ {b['outputs']} 路输出", f"{_n(n)} projectors ≤ {b['outputs']} outputs")}
    return {"check": "BLOCK", "sample": True, "note": tr(f"产品库里没有输出路数 ≥ {_n(n)} 的融合器",
                                                         f"No blender in the library with ≥ {_n(n)} outputs")}


def transport_pick(ctx: dict, catalog: dict) -> dict:
    """P14：距离 ≤ HDMI 上限用 HDMI；不超过光纤门槛用 HDBaseT；更远用光纤 HDMI；项目有 AV 网络时用 AVoIP。
    距离没填时：播放源在机房按超过 HDMI 上限算（HDBaseT，现场再核是否要光纤），在现场按 HDMI。"""
    hdmi_max, fiber = ctx["hdmi_max_m"], ctx["fiber_over_m"]
    if ctx.get("transport_mode") == "avoip":
        return {"outputs": {"transport": "AVoIP"}, "check": "PASS", "trace": tr("项目有 AV 网络", "AV network on site")}
    run = ctx.get("signal_run_m")
    if run is None:
        far = ctx.get("source_location") == "server_room"
        return {"outputs": {"transport": "HDBaseT" if far else "HDMI"}, "check": "NOTE", "note": tr(
            f"信号距离没填；播放源在机房，按超过 {_n(hdmi_max)} m 算：HDBaseT，超过 {_n(fiber)} m 要改光纤，请现场核实" if far
            else "信号距离没填；播放源在现场，按 HDMI 算，请现场核实",
            f"Signal run not filled in; source in the server room, so over {_n(hdmi_max)} m assumed: HDBaseT, "
            f"fiber above {_n(fiber)} m — check on site" if far
            else "Signal run not filled in; source on site, so HDMI assumed — check on site")}
    kind = "HDMI" if run <= hdmi_max else "HDBaseT" if run <= fiber else "Fiber HDMI"
    return {"outputs": {"transport": kind}, "check": "PASS",
            "trace": f"{_n(run)} m" + (f" ≤ {_n(hdmi_max)} m" if kind == "HDMI" else
                                       f" > {_n(hdmi_max)} m, ≤ {_n(fiber)} m" if kind == "HDBaseT" else f" > {_n(fiber)} m")}


def _spare(ctx: dict, n) -> Decimal:
    return max(ctx["spare_min"], Decimal(math.ceil(n * ctx["spare_ratio"])))


def power_points(ctx: dict, catalog: dict) -> dict:
    """P16：每台投影 1 个 13A 电源点；机房设备功率 × (1 + 余量)；方案 A 按设备数预留插座（含备用），方案 B 配 UPS。"""
    n, transport = ctx["projectors"], ctx["transport"]
    room_w = ctx["server_room_w"] * (1 + ctx["power_margin"])
    room_w = room_w.quantize(Decimal(1), rounding="ROUND_HALF_UP")
    if ctx.get("server_room_scope") == "media_pc_only":
        plugs = Decimal(1)
    else:
        plugs = (1 + (1 if n >= 2 else 0) + (n if transport == "HDBaseT" else 0)
                 + (1 if ctx.get("central_control") == "pjlink" else 0))
        plugs = Decimal(plugs)
    outlets = plugs + _spare(ctx, plugs)
    need = room_w / 1000 / ctx["ups_pf"]
    ups = next((k for k in UPS_KVA if k >= need), UPS_KVA[-1])
    return {"outputs": {"ceiling_outlets": n, "server_room_w_margin": room_w, "server_room_plugs": plugs,
                        "option_a_outlets": outlets, "option_b_ups_kva": ups},
            "check": "PASS", "sample": True,
            "trace": tr(f"吊顶 13A × {_n(n)}；机房 {_n(ctx['server_room_w'])} × {_n(1 + ctx['power_margin'])} = {_n(room_w)} W；"
                        f"插座 {_n(plugs)} + 备用 = {_n(outlets)}，或 UPS {_n(ups)} kVA",
                        f"Ceiling 13A × {_n(n)}; server room {_n(ctx['server_room_w'])} × {_n(1 + ctx['power_margin'])} = "
                        f"{_n(room_w)} W; outlets {_n(plugs)} + spare = {_n(outlets)}, or UPS {_n(ups)} kVA")}


def consistency(ctx: dict, catalog: dict) -> dict:
    """P17：视频线 = 控制线 = 台数；融合器输出 ≥ 台数；和原方案的数量核对；投影只用网络指令待机，不直接断电。"""
    n = ctx["projectors"]
    blocks, notes = [], []
    if ctx["video_lines"] != n:
        blocks.append(tr(f"视频线 {_n(ctx['video_lines'])} 根，和台数 {_n(n)} 不一致",
                         f"{_n(ctx['video_lines'])} video lines do not match {_n(n)} projectors"))
    pjlink = ctx.get("control_lines", 0) > 0
    if pjlink and ctx["control_lines"] != n:
        blocks.append(tr(f"控制线 {_n(ctx['control_lines'])} 根，和台数 {_n(n)} 不一致",
                         f"{_n(ctx['control_lines'])} control lines do not match {_n(n)} projectors"))
    if n >= 2 and ctx.get("blender_outputs") is not None and ctx["blender_outputs"] < n:
        blocks.append(tr(f"融合器输出 {_n(ctx['blender_outputs'])} 路，少于台数 {_n(n)}",
                         f"Blender has {_n(ctx['blender_outputs'])} outputs, fewer than {_n(n)} projectors"))
    if (design := ctx.get("existing_video_lines")) is not None and design != n:
        blocks.append(tr(f"原方案视频线 {_n(design)} 根，和台数 {_n(n)} 不一致",
                         f"The design has {_n(design)} video lines for {_n(n)} projectors"))
    match = None
    totals = (("existing_video_total", "video_lines", "video_spare", tr("视频线", "video cables")),
              ("existing_control_total", "control_lines", "control_spare", tr("控制线", "control cables")))
    for key, lines, spare, label in totals:
        if (design := ctx.get(key)) is not None and lines in ctx:
            ours = ctx[lines] + ctx.get(spare, 0)
            if design == ours:
                match = match or "PASS"
            else:
                match = "NOTE"
                notes.append(tr(f"原方案{label} {_n(design)} 根，规则算出 {_n(ours)} 根（含备用）",
                                f"The design has {_n(design)} {label}; the rules give {_n(ours)} including spares"))
    if not pjlink:
        notes.append(tr("没有中控：投影要单独设定待机", "No central control: projectors need their own standby setup"))
    points = n + (1 if n >= 2 else 0) + 1 if pjlink else Decimal(0)
    out = {"control_points": Decimal(points)}
    if match:
        out["cables_match"] = match
    return {"outputs": out, "check": "BLOCK" if blocks else "NOTE" if notes else "PASS",
            "note": tr("；", "; ").join(blocks + notes) or tr("投影只用网络指令（PJLink）待机，不直接断电",
                                                            "Projectors go to standby by network command (PJLink), never by cutting power"),
            "trace": tr(f"视频 {_n(ctx['video_lines'])} = 控制 {_n(ctx.get('control_lines', 0))} = 台数 {_n(n)}；中控点 {_n(points)}",
                        f"video {_n(ctx['video_lines'])} = control {_n(ctx.get('control_lines', 0))} = projectors {_n(n)}; "
                        f"control points {_n(points)}")}


# 步骤名 → (函数, 需要的名称, 产出的名称)
STEPS = {
    "lens_pick": (lens_pick, ["single_w_m", "available_depth_mm"],
                  ["lens", "lens_id", "throw_ratio", "min_distance_m", "distance_m"]),
    "occlusion": (occlusion, ["distance_m", "mount_height_m", "person_height_m"], ["occlusion_within_m"]),
    "blender_pick": (blender_pick, ["projectors"], ["blender", "blender_id", "blender_qty", "blender_outputs"]),
    "transport_pick": (transport_pick, ["hdmi_max_m", "fiber_over_m"], ["transport"]),
    "power_points": (power_points, ["projectors", "transport", "server_room_w", "power_margin", "ups_pf"],
                     ["ceiling_outlets", "server_room_w_margin", "server_room_plugs", "option_a_outlets", "option_b_ups_kva"]),
    "consistency": (consistency, ["projectors", "video_lines"], ["control_points", "cables_match"]),
}


# ---- 产品库选型、内部明细、示意图 ----

PRODUCT_INPUTS = ["native_px_w", "native_px_h", "projector_lumens", "projector_power_w"]  # 由选定的投影机带出
OVERRIDABLE: dict[str, list[str]] = {}  # 推荐页手动覆盖（CR-5）目前只做 LED


def size_choices(ctx: dict) -> dict:
    return {}


def recommend(inputs: dict, library: dict, chosen_id: str | None = None) -> dict:
    """投影机只从产品库里选，首选在前；可以换成其它型号。"""
    candidates = active(library, "projector")
    chosen = next((p for p in candidates if p["id"] == chosen_id), candidates[0] if candidates else None)
    block = None if chosen else tr("产品库里没有投影机，请先在产品库添加", "No projector in the library; add one first")
    return {"cabinet": chosen, "candidates": candidates, "block": block, "missing": []}


def product_inputs(projector: dict | None) -> dict:
    if not projector:
        return {}
    keys = {"native_px_w": "native_px_w", "native_px_h": "native_px_h", "projector_lumens": "lumens",
            "projector_power_w": "power_w"}
    return {k: projector[src] for k, src in keys.items() if projector.get(src) is not None}


def catalog(library: dict, projector: dict | None) -> dict:
    """规则引擎用到的产品：适配选定投影机的镜头（按投射比），以及融合器（首选在前）。"""
    fits = {projector["id"], projector["model"]} if projector else set()
    lenses = [x for x in active(library, "lens") if fits & set(x.get("fits") or []) and x.get("throw_ratio")]
    return {"cabinet": {"model": name(projector), "sample": projector.get("sample", False)} if projector else {},
            "lenses": [{"id": x["id"], "model": name(x), "throw_ratio": x["throw_ratio"], "sample": x.get("sample", False)}
                       for x in sorted(lenses, key=lambda x: x["throw_ratio"])],
            "blenders": [{"id": b["id"], "model": name(b), "outputs": b["outputs"], "curved": bool(b.get("curved")),
                          "sample": b.get("sample", False)} for b in active(library, "blender") if b.get("outputs")]}


def boq(values: dict, projector: dict | None, inputs: dict, library: dict, manual: set = frozenset()) -> list[dict]:
    """内部明细：数量全部来自规则结果，「数量依据」写规则编号。吊架、幕面这类「视现场」的只列项目，不推数量。"""
    lines, n = [], values.get("projectors")

    def add(key, item, model, qty, unit, why, rule):
        if qty is not None:
            lines.append({"key": key, "item": item, "model": model, "qty": qty, "unit": unit, "why": why,
                          "rule": rule, "included": False, "manual": False})

    if projector and n is not None:
        add(projector["id"], tr("投影机", "Projector"), name(projector), n, tr("台", "units"), "P2", "P2")
        if values.get("lens_id"):
            add(values["lens_id"], tr("镜头", "Lens"), values["lens"], n, tr("个", "pcs"), "P3", "P3")
        add("mount", tr("投影机吊架", "Projector mount"), tr("视现场", "Subject to site"), n, tr("套", "set"),
            tr("视现场", "Subject to site"), "P2")
    if values.get("blender_qty"):
        add(values["blender_id"], tr("融合器", "Blender"), values["blender"], values["blender_qty"], tr("台", "units"),
            "P11", "P11")
    if n is not None:
        add("media_pc", tr("播控电脑", "Media PC"), "—", 1, tr("台", "units"), "P12", "P12")
    if values.get("transport") in ("HDBaseT", "Fiber HDMI") and n is not None:
        add("transport_kit", tr(f"{values['transport']} 发送 / 接收", f"{values['transport']} TX / RX"), "—", n,
            tr("套", "set"), "P14", "P14")
    if values.get("video_lines") is not None:
        cable = "CAT6" if values.get("transport") in ("HDBaseT", "AVoIP") else values.get("transport", "")
        add("video_cable", tr("视频线", "Video cable"), cable, values["video_lines"] + values["video_spare"], tr("根", "pcs"),
            tr(f"{_n(values['video_lines'])} + {_n(values['video_spare'])} 备用，P15",
               f"{_n(values['video_lines'])} + {_n(values['video_spare'])} spare, P15"), "P15")
        if values.get("control_lines"):
            add("control_cable", tr("控制线", "Control cable"), "CAT6", values["control_lines"] + values["control_spare"],
                tr("根", "pcs"), tr(f"{_n(values['control_lines'])} + {_n(values['control_spare'])} 备用，P15",
                                    f"{_n(values['control_lines'])} + {_n(values['control_spare'])} spare, P15"), "P15")
    return lines


BOQ_EXTRA = ["projector_model", "transport_kits"]


def boq_context(values: dict, projector: dict | None, inputs: dict) -> dict:
    ctx = {**inputs, **product_inputs(projector), **values}
    if projector:
        ctx["projector_model"] = name(projector)
    if values.get("projectors") is not None:
        ctx["transport_kits"] = values["projectors"] if values.get("transport") in ("HDBaseT", "Fiber HDMI") else 0
    return ctx


def suggest(values: dict, inputs: dict, library: dict) -> list[dict]:
    return []


def diagram(values: dict, boq_lines: list[dict], inputs: dict, projector: dict | None, library: dict,
            suggestions: list[dict] | None = None, manual: set = frozenset()) -> dict | None:
    """信号链 L1：播控电脑 → 融合器 → 投影机 → 投影墙；每台设备、每条线缆都对应内部明细的行。"""
    n = values.get("projectors")
    if not projector or n is None:
        return None
    nodes = {"source": {"title": tr("播控电脑", "Media PC"), "model": "—", "qty": 1, "detail": "", "boq": ["media_pc"],
                        "supply": "boq"}}
    if values.get("blender_qty"):
        nodes["blender"] = {"title": tr("融合器", "Blender"), "model": values["blender"], "qty": values["blender_qty"],
                            "detail": tr(f"{_n(values['blender_outputs'])} 路输出", f"{_n(values['blender_outputs'])} outputs"),
                            "boq": [values["blender_id"]], "supply": "boq"}
    nodes["projector"] = {"title": tr("投影机", "Projector"), "model": name(projector), "qty": n,
                          "detail": f"{values.get('lens', '—')}", "boq": [projector["id"]], "supply": "boq"}
    nodes["screen"] = {"title": tr("投影墙", "Projection wall"), "model": "—",
                       "qty": f"{inputs.get('wall_width_mm')} × {inputs.get('wall_height_mm')}",
                       "detail": tr("幕面 / 涂料视现场", "Surface / paint subject to site"), "boq": [], "supply": "owner"}
    chain = [k for k in ("source", "blender", "projector", "screen") if k in nodes]
    links = []
    for a, b in zip(chain, chain[1:]):
        if b == "projector" and values.get("video_lines") is not None:
            links.append({"from": a, "to": b, "cable": values.get("transport", ""),
                          "qty": f"{_n(values['video_lines'])} + {_n(values['video_spare'])} " + tr("备用", "spare"),
                          "boq": "video_cable", "supply": "boq"})
        elif b == "screen":
            links.append({"from": a, "to": b, "cable": tr("投射", "Projection"), "qty": "", "boq": None, "supply": "included"})
        else:
            links.append({"from": a, "to": b, "cable": "HDMI", "qty": "1", "boq": None, "supply": "included"})
    keys = {line["key"] for line in boq_lines if line["key"]}
    unmatched = [f"{nd['title']} ({k})" for nd in nodes.values() if nd["supply"] == "boq" for k in nd["boq"] if k not in keys]
    unmatched += [f"{x['cable']} ({x['boq']})" for x in links if x["supply"] == "boq" and x["boq"] not in keys]
    return {"chain": chain, "power": None, "nodes": nodes, "links": links, "unmatched": unmatched}


STEP_DISPLAY = {
    "lens_pick": lambda o: f"{o['lens']} · {_n(o['distance_m'])} m",
    "occlusion": lambda o: tr(f"离墙 {_n(o['occlusion_within_m'].quantize(Decimal('0.01')))} m 以内",
                              f"Within {_n(o['occlusion_within_m'].quantize(Decimal('0.01')))} m"),
    "blender_pick": lambda o: f"{_n(o['blender_qty'])} × {o['blender']}" if o["blender_qty"] else "—",
    "transport_pick": lambda o: o["transport"],
    "power_points": lambda o: tr(f"吊顶 13A × {_n(o['ceiling_outlets'])} · 机房 {_n(o['server_room_w_margin'])} W",
                                 f"Ceiling 13A × {_n(o['ceiling_outlets'])} · server room {_n(o['server_room_w_margin'])} W"),
    "consistency": lambda o: tr(f"中控点 {_n(o['control_points'])}", f"{_n(o['control_points'])} control points"),
}
