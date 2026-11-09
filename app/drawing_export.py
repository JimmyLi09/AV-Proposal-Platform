"""拼接与线路图的输出（CR-3）：SVG（页面上显示的就是这张）、DXF（分图层、1:1、mm、真正的 DIMENSION 标注）、
DWG（服务器装了 ODA 才有）、箱体清单 Excel、技术方案 PDF（图纸 + 说明栏 + 计算依据）。
所有文件都写入 Rev、规则版本、产品库版本；没批准的 Rev 带 DRAFT。图纸、说明栏和计算依据用同一份数据。"""
import io
import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path

LAYERS = ["id", "size", "power", "data", "dim", "note"]
CIRCUIT_COLORS = ["#2C5AA0", "#2F7A5B", "#C2410C", "#7A4FA0", "#A0782C", "#1F7A8C", "#8C5A1F", "#D1495B"]
CABLE_COLORS = ["#D1495B", "#2E86AB", "#3B8B5A", "#E59F2B", "#6D597A", "#1F7A8C", "#8C5A1F", "#2C5AA0"]
SIZE_FILL = ["#E3ECF7", "#F6E9D6", "#E6F2EC", "#F1E6F6"]
NAVY, MUTED, RED = "#15203A", "#6B6558", "#A23A2A"
FONT = "-apple-system, 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif"
DXF_LAYERS = {"AVP-CABINET": 8, "AVP-CABINET-ID": 7, "AVP-POWER": 5, "AVP-DATA": 1, "AVP-DIM": 3, "AVP-NOTE": 7}

TEXT = {
    "zh": {"title": "拼接与线路图", "project": "项目", "size": "尺寸 · 面积", "cabinets": "箱体", "modules": "模组",
           "resolution": "分辨率", "power": "功率 · 回路", "data": "网线", "reserved": "预留", "spare": "备用",
           "circuit": "回路", "cable": "网线", "box": "箱", "over": "超载", "legend": "图例",
           "numbering": "编号从左下角 R1C1 开始 · 网线起点在左侧",
           "disclaimer": "本图为方案示意，箱体规格以厂家深化为准", "basis": "计算依据", "item": "项目",
           "formula": "公式（代入数值）", "result": "结果", "rule": "规则", "manual": "手动调整",
           "faces_numbering": "每面编号从左下角 R1C1 开始 · 回路、网线编号整屏连续\n面与面之间的空白只为看得清，不是实际尺寸"},
    "en": {"title": "Cabinet & cabling drawing", "project": "Project", "size": "Size · Area", "cabinets": "Cabinets",
           "modules": "Modules", "resolution": "Resolution", "power": "Power · Circuits", "data": "Data cables",
           "reserved": "reserved", "spare": "spare", "circuit": "Circuit", "cable": "Cable", "box": "cab.",
           "over": "overload", "legend": "Legend", "numbering": "Numbering from bottom-left R1C1 · data cables start on the left",
           "disclaimer": "Concept drawing; cabinet specs subject to manufacturer detailing", "basis": "Calculation basis",
           "item": "Item", "formula": "Formula (with values)", "result": "Result", "rule": "Rule",
           "manual": "Manually adjusted",
           "faces_numbering": "Each face numbered from its bottom-left R1C1 · circuit and cable numbers run\n"
                              "across the whole screen · gaps between faces are for legibility only"},
}


def notes(d: dict, meta: dict, lang: str) -> list[tuple[str, str]]:
    """说明栏（SVG、DXF、PDF 共用）。"""
    t, v = TEXT[lang], meta["values"]
    cabs = " + ".join(f"{k} {s['count']}" for k, s in d["sizes"].items()) + f" = {len(d['cabinets'])}"
    return [
        (t["project"], meta["project"]),
        (t["size"], (" + ".join(f"{p['width']} × {p['height']}" for p in d["panels"]) if d.get("panels")  # 多面屏：每面的尺寸
                     else f"{d['width']} × {d['height']}") + f" mm · {v['area_m2']:.2f} ㎡"),
        (t["modules"] + " · " + t["cabinets"], f"{v.get('modules', '—')} · {cabs}"),
        (t["resolution"], " × ".join(map(str, d["canvas_px"])) if d.get("canvas_px")  # 多面屏：展开画布
         else f"{v.get('res_x', '—')} × {v.get('res_y', '—')}"),
        (t["power"], f"{v['power_kw']:.2f} kW · {len(d['circuits'])} + {d['spare_circuits']} {t['reserved']}"),
        (t["data"], f"{len(d['cables'])} + {d['spare_cables']} {t['spare']}"),
    ]


def _circled(n: int) -> str:
    return chr(0x2460 + n - 1) if 1 <= n <= 20 else str(n)


def panels(d: dict) -> list[dict]:
    """图上的每一面（多面屏是展开总图里的每一面，单屏就是整张屏）：原点、尺寸、列宽、行高。"""
    return d.get("panels") or [{"id": "", "label": None, "x": 0, "y": 0, "width": d["width"], "height": d["height"],
                                "cols": d["cols"], "col_w": d["col_w"], "rows": d["rows"]}]


def svg(d: dict, meta: dict, lang: str = "zh", layers: list[str] | None = None) -> str:
    """layers：要显示的图层（默认全部）。每个箱体是 <g data-cab="R1C1">，页面上点它可以换回路 / 网线。
    多面屏（d 里有 panels）：一张展开总图，每面上方写面的名字和尺寸，尺寸线按面画；说明栏每面一行汇总，超载的单独列出。"""
    t, shown = TEXT[lang], set(LAYERS if layers is None else layers)
    W, H = d["width"], d["height"]
    multi = bool(d.get("panels"))
    s = min(820 / max(p["width"] for p in panels(d)), 2600 / W, 1400 / H) if multi else 820 / W
    left, top, gap = 40, 140 if multi else 116, 110
    note_x = left + W * s + gap
    width, height = note_x + 330, max(top + H * s + 70, 560)
    if multi:  # 说明栏放得下：每面三行汇总，加上超载的
        lines = 3 * len(d["panels"]) + sum(1 for c in d["circuits"] + d["cables"] if c["over"])
        height = max(height, top + 16 * len(d["sizes"]) + 15 * lines + 300)
    X = lambda x: left + x * s  # noqa: E731
    Y = lambda y: top + (H - y) * s  # noqa: E731  CAD 坐标 y 向上
    over_c = {c["no"] for c in d["circuits"] if c["over"]}
    over_d = {c["no"] for c in d["cables"] if c["over"]}
    size_idx = {k: i for i, k in enumerate(d["sizes"])}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}"'
           f' height="{height:.0f}" font-family="{FONT}" class="drawing{" wide" if multi else ""}">',
           f'<rect width="100%" height="100%" fill="#FFFFFF"/>',
           f'<text x="{left}" y="26" font-size="16" font-weight="700" fill="{NAVY}">{escape(t["title"])} · {escape(meta["project"])}</text>']
    # 箱体（AVP-CABINET）和图层
    for c in d["cabinets"]:
        x, y, w, h = X(c["x"]), Y(c["y"] + c["h"]), c["w"] * s, c["h"] * s
        stroke = RED if c["circuit"] in over_c or c["cable"] in over_d else (NAVY if c["manual"] else "#8F8676")
        g = [f'<g data-cab="{c["id"]}" class="cab">',
             f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{SIZE_FILL[size_idx[c["size"]] % 4]}"'
             f' stroke="{stroke}" stroke-width="{2 if stroke != "#8F8676" else 0.8}"/>']
        if "power" in shown:
            col = CIRCUIT_COLORS[(c["circuit"] - 1) % len(CIRCUIT_COLORS)]
            g.append(f'<rect class="layer-power" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{col}"'
                     f' fill-opacity="0.14" pointer-events="none"/>'
                     f'<text class="layer-power" x="{x + 3:.1f}" y="{y + h - 4:.1f}" font-size="9.5" font-weight="700"'
                     f' fill="{col}">P{c["circuit"]}</text>')
        if "id" in shown:  # 多面屏格子里写面内编号（R1C1），面的名字写在上方
            g.append(f'<text class="layer-id" x="{x + w / 2:.1f}" y="{y + h * 0.42:.1f}" font-size="10" text-anchor="middle"'
                     f' fill="{NAVY}">{c.get("local", c["id"])}</text>')
        if "size" in shown:
            g.append(f'<text class="layer-size" x="{x + w / 2:.1f}" y="{y + h * 0.42 + 12:.1f}" font-size="9" text-anchor="middle"'
                     f' fill="{MUTED}">{c["size"]}</text>')
        if "data" in shown:
            col = CABLE_COLORS[(c["cable"] - 1) % len(CABLE_COLORS)]
            g.append(f'<text class="layer-data" x="{x + w - 3:.1f}" y="{y + h - 4:.1f}" font-size="10.5" font-weight="700"'
                     f' text-anchor="end" fill="{col}">{_circled(c["cable"])}</text>')
        g.append("</g>")
        out.append("".join(g))
    if "data" in shown:  # 网线：按蛇形顺序连起来
        by_id = {c["id"]: c for c in d["cabinets"]}
        for cable in d["cables"]:
            col = CABLE_COLORS[(cable["no"] - 1) % len(CABLE_COLORS)]
            pts = " ".join(f"{X(by_id[i]['x'] + by_id[i]['w'] / 2):.1f},{Y(by_id[i]['y'] + by_id[i]['h'] / 2):.1f}"
                           for i in cable["path"])
            out.append(f'<polyline class="layer-data" points="{pts}" fill="none" stroke="{col}" stroke-width="1.6"'
                       f' stroke-opacity="0.8" pointer-events="none"/>')
            if cable["path"]:
                first = by_id[cable["path"][0]]
                out.append(f'<circle class="layer-data" cx="{X(first["x"] + first["w"] / 2):.1f}"'
                           f' cy="{Y(first["y"] + first["h"] / 2):.1f}" r="3.5" fill="{col}" pointer-events="none"/>')
    for p in panels(d):
        px, py, pw, ph = p["x"], p["y"], p["width"], p["height"]
        if p["label"]:  # 面的名字和尺寸
            out.append(f'<text x="{X(px)}" y="{Y(py + ph) - 64:.1f}" font-size="13" font-weight="700" fill="{NAVY}">'
                       f'{escape(p["label"])} · {pw} × {ph}</text>')
        if "dim" not in shown:  # 尺寸线：上方逐列 + 总宽，右侧逐行 + 总高
            continue
        y1, y2 = Y(py + ph) - 18, Y(py + ph) - 46
        for c in range(p["cols"]):
            xa, xb = X(px + c * p["col_w"]), X(px + (c + 1) * p["col_w"])
            out.append(f'<g class="layer-dim"><line x1="{xa:.1f}" y1="{y1:g}" x2="{xb:.1f}" y2="{y1:g}" stroke="{MUTED}"/>'
                       f'<line x1="{xa:.1f}" y1="{y1 - 4:g}" x2="{xa:.1f}" y2="{y1 + 4:g}" stroke="{MUTED}"/>'
                       f'<text x="{(xa + xb) / 2:.1f}" y="{y1 - 4:g}" font-size="9.5" text-anchor="middle" fill="{MUTED}">{p["col_w"]}</text></g>')
        out.append(f'<g class="layer-dim"><line x1="{X(px)}" y1="{y2:g}" x2="{X(px + pw):.1f}" y2="{y2:g}" stroke="{NAVY}"/>'
                   f'<text x="{X(px + pw / 2):.1f}" y="{y2 - 5:g}" font-size="11.5" font-weight="700" text-anchor="middle" fill="{NAVY}">'
                   f'{pw} = {p["col_w"]} × {p["cols"]}</text></g>')
        x1, x2, y = X(px + pw) + 16, X(px + pw) + 70, py
        for h in p["rows"]:
            ya, yb = Y(y), Y(y + h)
            out.append(f'<g class="layer-dim"><line x1="{x1}" y1="{ya:.1f}" x2="{x1}" y2="{yb:.1f}" stroke="{MUTED}"/>'
                       f'<line x1="{x1 - 4}" y1="{yb:.1f}" x2="{x1 + 4}" y2="{yb:.1f}" stroke="{MUTED}"/>'
                       f'<text x="{x1 + 5}" y="{(ya + yb) / 2 + 3:.1f}" font-size="9.5" fill="{MUTED}">{h}</text></g>')
            y += h
        out.append(f'<g class="layer-dim"><line x1="{x2}" y1="{Y(py):.1f}" x2="{x2}" y2="{Y(py + ph):.1f}" stroke="{NAVY}"/>'
                   f'<text x="{x2 + 6}" y="{Y(py + ph / 2):.1f}" font-size="11.5" font-weight="700" fill="{NAVY}"'
                   f' transform="rotate(90 {x2 + 6} {Y(py + ph / 2):.1f})" text-anchor="middle">{ph} = {" + ".join(str(h) for h in p["rows"][::-1])}</text></g>')
    if "note" in shown:  # 说明栏
        y = top - 40
        out.append(f'<g class="layer-note"><rect x="{note_x - 12}" y="{y - 22}" width="330" height="{height - y + 10:.0f}"'
                   f' fill="#FAF8F4" stroke="#E6E0D6"/>')
        for label, value in notes(d, meta, lang):
            out.append(f'<text x="{note_x}" y="{y}" font-size="10" fill="{MUTED}">{escape(label)}</text>'
                       f'<text x="{note_x}" y="{y + 14}" font-size="11.5" font-weight="600" fill="{NAVY}">{escape(value)}</text>')
            y += 34
        out.append(f'<text x="{note_x}" y="{y}" font-size="10" fill="{MUTED}">{escape(t["legend"])}</text>')
        y += 16
        for i, (k, sz) in enumerate(d["sizes"].items()):
            out.append(f'<rect x="{note_x}" y="{y - 9}" width="14" height="10" fill="{SIZE_FILL[i % 4]}" stroke="#8F8676"/>'
                       f'<text x="{note_x + 20}" y="{y}" font-size="10.5" fill="{NAVY}">{k} {sz["w"]} × {sz["h"]} × {sz["count"]}</text>')
            y += 16
        if multi:  # 每面一行汇总：回路、网线编号段和预留 / 备用；超载的单独列出
            for p in d["panels"]:
                (c1, c2), (d1, d2) = p["circuits"], p["cables"]
                out.append(f'<text x="{note_x}" y="{y}" font-size="10.5" font-weight="600" fill="{NAVY}">{escape(p["label"])}</text>'
                           f'<text x="{note_x}" y="{y + 15}" font-size="10.5" fill="{NAVY}">P{c1}–P{c2} {t["circuit"]} · '
                           f'{c2 - c1 + 1} + {p["spare_circuits"]} {t["reserved"]}</text>'
                           f'<text x="{note_x}" y="{y + 30}" font-size="10.5" fill="{NAVY}">{_circled(d1)}–{_circled(d2)} {t["cable"]} · '
                           f'{d2 - d1 + 1} + {p["spare_cables"]} {t["spare"]}</text>')
                y += 45
        for c in d["circuits"]:
            if multi and not c["over"]:
                continue
            col = RED if c["over"] else CIRCUIT_COLORS[(c["no"] - 1) % len(CIRCUIT_COLORS)]
            tail = f" · {t['over']}" if c["over"] else ""
            out.append(f'<text x="{note_x}" y="{y}" font-size="10.5" fill="{col}">P{c["no"]} {t["circuit"]} {c["no"]} · '
                       f'{c["cabinets"]} {t["box"]} · {c["watts"]} W · {c["amps"]} A{tail}</text>')
            y += 15
        if not multi:
            out.append(f'<text x="{note_x}" y="{y}" font-size="10.5" fill="{MUTED}">P{len(d["circuits"]) + 1} {t["circuit"]} '
                       f'{len(d["circuits"]) + 1} · {t["reserved"]}</text>')
            y += 18
        for c in d["cables"]:
            if multi and not c["over"]:
                continue
            col = RED if c["over"] else CABLE_COLORS[(c["no"] - 1) % len(CABLE_COLORS)]
            tail = f" · {t['over']}" if c["over"] else ""
            out.append(f'<text x="{note_x}" y="{y}" font-size="10.5" fill="{col}">{_circled(c["no"])} {t["cable"]} · '
                       f'{c["cabinets"]} {t["box"]} · {c["px"]:,} px{tail}</text>')
            y += 15
        if not multi:
            out.append(f'<text x="{note_x}" y="{y}" font-size="10.5" fill="{MUTED}">{_circled(len(d["cables"]) + 1)} FOR SPARE · {t["spare"]}</text>')
        y += 24
        for line in (*t["faces_numbering" if multi else "numbering"].split("\n"), t["disclaimer"], meta["stamp"]):
            out.append(f'<text x="{note_x}" y="{y}" font-size="9.5" fill="{MUTED}">{escape(line)}</text>')
            y += 14
        out.append("</g>")
    if meta["draft"]:
        out.append(f'<text x="{X(W / 2):.1f}" y="{Y(H / 2):.1f}" font-size="{min(W * s / 5, 120):.0f}" font-weight="700"'
                   f' fill="{RED}" fill-opacity="0.10" text-anchor="middle" dominant-baseline="middle"'
                   f' transform="rotate(-20 {X(W / 2):.1f} {Y(H / 2):.1f})" pointer-events="none">DRAFT</text>')
    out.append("</svg>")
    return "".join(out)


WIRING_TEXT = {
    "zh": {"sender": "发送卡", "db": "配电箱", "circuit": "回路", "port": "网口", "box": "箱"},
    "en": {"sender": "Sending card", "db": "DB box", "circuit": "Circuit", "port": "Port", "box": "cab."},
}
DATA_BLUE = "#2E6FD8"


def wiring_svg(d: dict, lang: str = "zh") -> str:
    """方案配置页（05）的接线示意图（CR-11），和图纸用同一份 W1 结果：箱体格子；电源每路一种颜色、虚线，从左下的配电箱
    接到这一路的第一箱再按走线顺序串下去；网线蓝色实线，从左上的发送卡开始。回路标签在屏幕下方、网口标签在屏幕上方，
    平均分布不重叠。电源、网线分别在 layer-power / layer-data 里，页面上可以只看其中一种。超载的组标红。"""
    t = WIRING_TEXT[lang]
    W, H = d["width"], d["height"]
    s = min(760 / W, 340 / H)
    left, top = 150, 70
    sw, sh = W * s, H * s
    X = lambda x: left + x * s  # noqa: E731
    Y = lambda y: top + (H - y) * s  # noqa: E731
    cab = {c["id"]: c for c in d["cabinets"]}
    center = lambda cid: (X(cab[cid]["x"] + cab[cid]["w"] / 2), Y(cab[cid]["y"] + cab[cid]["h"] / 2))  # noqa: E731
    width, height = left + sw + 30, top + sh + 66
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" '
           f'height="{height:.0f}" font-family="{FONT}">',
           f'<rect width="{width:.0f}" height="{height:.0f}" fill="#fff"/>']
    for c in d["cabinets"]:
        out.append(f'<rect x="{X(c["x"]):.1f}" y="{Y(c["y"] + c["h"]):.1f}" width="{c["w"] * s:.1f}" '
                   f'height="{c["h"] * s:.1f}" fill="#F7F4EE" stroke="#CFC6B8"/>')
    sender, db = (12, top - 4), (12, top + sh - 32)
    out.append(f'<g class="layer-data"><rect x="{sender[0]}" y="{sender[1]}" width="112" height="36" rx="6" fill="#EAF1FC" '
               f'stroke="{DATA_BLUE}"/><text x="{sender[0] + 56}" y="{sender[1] + 22}" font-size="12" text-anchor="middle" '
               f'fill="{NAVY}">{escape(t["sender"])}</text></g>')
    out.append(f'<g class="layer-power"><rect x="{db[0]}" y="{db[1]}" width="112" height="36" rx="6" fill="#FDF1E6" '
               f'stroke="#C2410C"/><text x="{db[0] + 56}" y="{db[1] + 22}" font-size="12" text-anchor="middle" '
               f'fill="{NAVY}">{escape(t["db"])}</text></g>')

    def run(cls, path, color, start, dashed, no, label, sub, slot, n, above, shift):
        """shift：电源线往下、网线往上各偏几像素，两种线并排走，不互相遮住。"""
        pts = [start] + [(x, y + shift) for x, y in map(center, path)]
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        g = [f'<g class="{cls}">',
             f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{color}" '
             f'stroke-width="1.8"{dash}/>']
        fx, fy = center(path[0])
        bx, by = fx + (10 if shift > 0 else -10), fy + shift * 2
        g.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="8" fill="{color}"/>'
                 f'<text x="{bx:.1f}" y="{by + 4:.1f}" font-size="10" font-weight="700" text-anchor="middle" fill="#fff">{no}</text>')
        lx = left + sw * (slot + 0.5) / n  # 平均分布在屏幕上方 / 下方，每个标签两行，不超过自己那一格
        ly = top - 30 if above else top + sh + 22
        g.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" text-anchor="middle" fill="{color}" font-weight="600">'
                 f'{escape(label)}</text>'
                 f'<text x="{lx:.1f}" y="{ly + 14:.1f}" font-size="10" text-anchor="middle" fill="{MUTED}">{escape(sub)}</text>')
        g.append("</g>")
        return g

    n = len(d["circuits"])
    for i, c in enumerate(d["circuits"]):
        if not c["path"]:
            continue
        color = RED if c["over"] else CIRCUIT_COLORS[(c["no"] - 1) % len(CIRCUIT_COLORS)]
        out += run("layer-power", c["path"], color, (db[0] + 112, db[1] + 18), True, c["no"],
                   f'{t["circuit"]} {c["no"]} · {c["cabinets"]} {t["box"]}', f'{c["amps"]} A', i, n, False, 5)
    n = len(d["cables"])
    for i, c in enumerate(d["cables"]):
        if not c["path"]:
            continue
        color = RED if c["over"] else DATA_BLUE
        out += run("layer-data", c["path"], color, (sender[0] + 112, sender[1] + 18), False, _circled(c["no"]),
                   f'{t["port"]} {_circled(c["no"])} · {c["cabinets"]} {t["box"]}', f'{c["px"]:,} px', i, n, True, -5)
    out.append("</svg>")
    return "".join(out)


def dxf(d: dict, meta: dict, lang: str = "zh") -> bytes:
    """单位 mm，1:1；每样东西一个图层；尺寸用 DIMENSION 实体，在 AutoCAD 里可以直接量、直接改。"""
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for name, color in DXF_LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    W, H = d["width"], d["height"]
    th = max(W, H) / 120  # 文字高度随屏幕大小
    for c in d["cabinets"]:
        x, y, w, h = c["x"], c["y"], c["w"], c["h"]
        msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs={"layer": "AVP-CABINET"})
        msp.add_text(c["id"], height=th, dxfattribs={"layer": "AVP-CABINET-ID"}).set_placement(
            (x + w / 2, y + h * 0.55), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        msp.add_text(f"{c['size']} {w}x{h}", height=th * 0.7, dxfattribs={"layer": "AVP-CABINET-ID"}).set_placement(
            (x + w / 2, y + h * 0.35), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        msp.add_text(f"P{c['circuit']}", height=th * 0.8, dxfattribs={"layer": "AVP-POWER", "color": (c["circuit"] - 1) % 6 + 1}
                     ).set_placement((x + w * 0.08, y + h * 0.08))
        msp.add_text(f"D{c['cable']}", height=th * 0.8, dxfattribs={"layer": "AVP-DATA", "color": (c["cable"] - 1) % 6 + 1}
                     ).set_placement((x + w * 0.92, y + h * 0.08), align=ezdxf.enums.TextEntityAlignment.BOTTOM_RIGHT)
    by_id = {c["id"]: c for c in d["cabinets"]}
    for cable in d["cables"]:
        pts = [(by_id[i]["x"] + by_id[i]["w"] / 2, by_id[i]["y"] + by_id[i]["h"] / 2) for i in cable["path"]]
        if len(pts) > 1:
            msp.add_lwpolyline(pts, dxfattribs={"layer": "AVP-DATA", "color": (cable["no"] - 1) % 6 + 1})
    dim = {"dimtxt": th, "dimasz": th * 0.8, "dimexe": th * 0.5, "dimexo": th * 0.3, "dimgap": th * 0.3}
    for p in panels(d):  # 尺寸线按面画；多面屏每面上方写面的名字和尺寸
        px, py, pw, ph = p["x"], p["y"], p["width"], p["height"]
        for c in range(p["cols"]):
            msp.add_linear_dim(base=(px, py + ph + th * 4), p1=(px + c * p["col_w"], py + ph),
                               p2=(px + (c + 1) * p["col_w"], py + ph), override=dim, dxfattribs={"layer": "AVP-DIM"}).render()
        msp.add_linear_dim(base=(px, py + ph + th * 9), p1=(px, py + ph), p2=(px + pw, py + ph), override=dim,
                           dxfattribs={"layer": "AVP-DIM"}).render()
        y = py
        for h in p["rows"]:
            msp.add_linear_dim(base=(px + pw + th * 4, py), p1=(px + pw, y), p2=(px + pw, y + h), angle=90, override=dim,
                               dxfattribs={"layer": "AVP-DIM"}).render()
            y += h
        msp.add_linear_dim(base=(px + pw + th * 9, py), p1=(px + pw, py), p2=(px + pw, py + ph), angle=90, override=dim,
                           dxfattribs={"layer": "AVP-DIM"}).render()
        if p["label"]:
            msp.add_text(f"{p['label']} {pw}x{ph}", height=th * 1.6, dxfattribs={"layer": "AVP-NOTE"}).set_placement(
                (px, py + ph + th * 12))
    t = TEXT[lang]
    lines = [t["title"]] + [f"{a}: {b}" for a, b in notes(d, meta, lang)]
    lines += [f"P{c['no']} {t['circuit']} {c['no']}: {c['cabinets']} {t['box']} · {c['watts']} W · {c['amps']} A"
              + (f" · {t['over']}" if c["over"] else "") for c in d["circuits"]]
    lines += [f"D{c['no']} {t['cable']}: {c['cabinets']} {t['box']} · {c['px']:,} px" + (f" · {t['over']}" if c["over"] else "")
              for c in d["cables"]]
    lines += [f"D{len(d['cables']) + 1} FOR SPARE"] if not d.get("panels") else [
        f"{p['label']}: P{p['circuits'][0]}–P{p['circuits'][1]} + {p['spare_circuits']} {t['reserved']} · "
        f"D{p['cables'][0]}–D{p['cables'][1]} + {p['spare_cables']} {t['spare']}" for p in d["panels"]]
    lines += [t["faces_numbering"].replace("\n", " ") if d.get("panels") else t["numbering"], t["disclaimer"], meta["stamp"]]
    msp.add_mtext("\\P".join(lines), dxfattribs={"layer": "AVP-NOTE", "char_height": th, "insert": (W + th * 16, H),
                                                 "width": th * 45})
    if meta["draft"]:
        msp.add_text("DRAFT", height=H / 6, dxfattribs={"layer": "AVP-NOTE", "color": 1}).set_placement(
            (W / 2, H / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    doc.header["$PROJECTNAME"] = meta["project"][:250]
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def dwg(dxf_bytes: bytes, oda: str) -> bytes:
    """用免费的 ODA File Converter 把 DXF 转成 DWG（ODA 只处理整个文件夹）。"""
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
        (Path(src) / "drawing.dxf").write_bytes(dxf_bytes)
        subprocess.run([oda, src, dst, "ACAD2018", "DWG", "0", "1", "*.DXF"], check=True, timeout=180, capture_output=True)
        return next(Path(dst).glob("*.dwg")).read_bytes()


def cabinets_xlsx(d: dict, meta: dict, lang: str = "zh") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    t = TEXT[lang]
    wb = Workbook()
    ws = wb.active
    ws.title = "Cabinets"
    ws.append([f"{t['cabinets']} · {meta['project']}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([meta["stamp"]])
    ws.append([])
    ws.append(["ID", "Size 尺寸", "Circuit 回路", "Data cable 网线", "Row 行", "Column 列", "px", "W", "Manual 手动"])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    face = {p["id"]: i for i, p in enumerate(panels(d))}
    for c in sorted(d["cabinets"], key=lambda c: (face.get(c.get("face", ""), 0), c["row"], c["col"])):
        ws.append([c["id"], f"{c['size']} {c['w']} × {c['h']}", c["circuit"], c["cable"], c["row"], c["col"], c["px"],
                   c["watts"], "✓" if c["manual"] else ""])
    for col, width in zip("ABCDEFGHI", (10, 16, 10, 14, 8, 10, 10, 10, 10)):
        ws.column_dimensions[col].width = width
    p = wb.properties
    p.title, p.keywords, p.description, p.creator = f"Cabinets · {meta['project']}", meta["stamp"], meta["stamp"], "AV Proposal Platform"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pdf(d: dict, meta: dict, basis: list[dict], lang: str = "zh") -> bytes:
    """技术方案 PDF：图纸 + 说明栏 + 计算依据，用无头 Chromium 打印，再用 pypdf 写文件属性。"""
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader, PdfWriter

    t = TEXT[lang]
    rows = "".join(f"<tr><td>{escape(b['item'])}</td><td class='mono'>{escape(b['formula'])}</td>"
                   f"<td>{escape(b['result'])}</td><td>{escape(b['rule'])}</td></tr>" for b in basis)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      body {{ font-family: {FONT}; color: {NAVY}; margin: 0; }}
      h1 {{ font-size: 18px; margin: 0 0 4px; }} .muted {{ color: {MUTED}; font-size: 11px; }}
      svg {{ width: 100%; height: auto; }} table {{ border-collapse: collapse; width: 100%; font-size: 11px; margin-top: 10px; }}
      th, td {{ border-bottom: 1px solid #E6E0D6; padding: 5px 6px; text-align: left; vertical-align: top; }}
      .mono {{ font-family: Consolas, monospace; }} h2 {{ font-size: 14px; margin: 14px 0 0; }}
    </style></head><body>
      <h1>{escape(t['title'])} · {escape(meta['project'])}</h1><div class="muted">{escape(meta['stamp'])}</div>
      {svg(d, meta, lang)}
      <h2>{escape(t['basis'])}</h2>
      <table><thead><tr><th>{t['item']}</th><th>{t['formula']}</th><th>{t['result']}</th><th>{t['rule']}</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html)
            raw = page.pdf(format="A3", landscape=True, print_background=True,
                           margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"})
        finally:
            browser.close()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(raw)))
    writer.add_metadata({"/Title": f"{t['title']} · {meta['project']}", "/Subject": meta["stamp"],
                         "/Keywords": meta["stamp"], "/Creator": "AV Proposal Platform"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def oda_available(oda: str | None) -> bool:
    return bool(oda) and (Path(oda).exists() or shutil.which(oda) is not None)
