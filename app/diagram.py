"""Level 1 概念图：信号从左到右，电源从下方的配电箱接入。生成 SVG，界面和 Proposal（第 6 步）共用同一张。"""
from html import escape

from .i18n import tr

BOX_W, BOX_H, GAP, V_GAP, PAD = 200, 84, 150, 80, 24
NAVY, MUTED, ORANGE = "#15203A", "#6B6558", "#C2410C"
FONT = "-apple-system, 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif"


def _box(x: float, y: float, node: dict) -> str:
    dashed = ' stroke-dasharray="6 4"' if node["supply"] != "boq" else ""
    qty = node["qty"] if isinstance(node["qty"], str) else f"× {node['qty']}"
    if node.get("manual"):  # 数量是手动值（CR-5）
        qty += " · " + tr("手动", "manual")
    return (f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="10" fill="#FFFFFF" stroke="{NAVY}"'
            f' stroke-width="1.5"{dashed}/>'
            f'<text x="{x + 12}" y="{y + 24}" font-size="13" font-weight="700" fill="{NAVY}">{escape(node["title"])}</text>'
            f'<text x="{x + 12}" y="{y + 46}" font-size="12" fill="#1F2430">{escape(str(node["model"]))} {escape(qty)}</text>'
            f'<text x="{x + 12}" y="{y + 66}" font-size="11" fill="{MUTED}">{escape(node["detail"])}</text>')


def _label(x: float, y: float, text: str, owner: bool) -> str:
    return f'<text x="{x}" y="{y}" font-size="11" text-anchor="middle" fill="{MUTED if owner else ORANGE}">{escape(text)}</text>'


def concept_svg(d: dict) -> str:
    chain, nodes = d["chain"], d["nodes"]
    width = PAD * 2 + len(chain) * BOX_W + (len(chain) - 1) * GAP
    height = PAD * 2 + BOX_H * (2 if d["power"] else 1) + (V_GAP if d["power"] else 0)
    x_of = {n: PAD + i * (BOX_W + GAP) for i, n in enumerate(chain)}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}"'
             f' font-family="{FONT}">',
             f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"'
             f' orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{NAVY}"/></marker></defs>']
    for n in chain:
        parts.append(_box(x_of[n], PAD, nodes[n]))
    for link in d["links"]:
        owner = link["supply"] != "boq"
        text = f"{link['cable']} × {link['qty']}" + (" · " + tr("手动", "manual") if link.get("manual") else "")
        note = {"owner": tr("业主提供", "By owner"), "included": tr("随设备附带", "Included")}.get(link["supply"], "")
        if link["from"] in x_of:  # 信号：横向箭头
            x1, x2, y = x_of[link["from"]] + BOX_W, x_of[link["to"]], PAD + BOX_H / 2
            parts.append(f'<line x1="{x1}" y1="{y}" x2="{x2 - 2}" y2="{y}" stroke="{NAVY}" stroke-width="1.5"'
                         f' marker-end="url(#arrow)"/>')
            parts.append(_label((x1 + x2) / 2, y - 10, text, owner))
            if note:
                parts.append(_label((x1 + x2) / 2, y + 20, note, owner))
        else:  # 电源：配电箱在屏幕正下方，竖向箭头
            x = x_of[link["to"]]
            y_box = PAD + BOX_H + V_GAP
            parts.append(_box(x, y_box, nodes[link["from"]]))
            xm = x + BOX_W / 2
            parts.append(f'<line x1="{xm}" y1="{y_box}" x2="{xm}" y2="{PAD + BOX_H + 2}" stroke="{NAVY}"'
                         f' stroke-width="1.5" marker-end="url(#arrow)"/>')
            parts.append(f'<text x="{xm - 8}" y="{PAD + BOX_H + V_GAP / 2 + 4}" font-size="11" text-anchor="end"'
                         f' fill="{ORANGE}">{escape(text)}</text>')
    parts.append("</svg>")
    return "".join(parts)


ROW_GAP = 48  # 多面屏：每面一行，行间距


def faces_svg(d: dict) -> str:
    """多面屏（S5）：信号源、整屏 1 台处理器在左边居中；每面一行：控制器 → 屏 ← 配电箱（电源从右边接入）。"""
    rows = d["faces"]
    cols = ["source", "processor"] + (["controller"] if any("controller" in r for r in rows) else []) + ["screen"] + (
        ["db_box"] if any("db_box" in r for r in rows) else [])
    x_col = {c: PAD + i * (BOX_W + GAP) for i, c in enumerate(cols)}
    tall = len(rows) * BOX_H + (len(rows) - 1) * ROW_GAP
    width, height = PAD * 2 + len(cols) * BOX_W + (len(cols) - 1) * GAP, PAD * 2 + tall
    pos = {"source": (x_col["source"], PAD + (tall - BOX_H) / 2), "processor": (x_col["processor"], PAD + (tall - BOX_H) / 2)}
    for i, r in enumerate(rows):
        for c in cols[2:]:
            if c in r:
                pos[r[c]] = (x_col[c], PAD + i * (BOX_H + ROW_GAP))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}"'
             f' font-family="{FONT}">',
             f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"'
             f' orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{NAVY}"/></marker></defs>']
    for nid, (x, y) in pos.items():
        parts.append(_box(x, y, d["nodes"][nid]))
    for link in d["links"]:
        (x1, y1), (x2, y2) = pos[link["from"]], pos[link["to"]]
        owner = link["supply"] != "boq"
        text = f"{link['cable']} × {link['qty']}"
        note = {"owner": tr("业主提供", "By owner"), "included": tr("随设备附带", "Included")}.get(link["supply"], "")
        ya, yb = y1 + BOX_H / 2, y2 + BOX_H / 2
        if x1 > x2:  # 电源：配电箱在屏右边，箭头向左
            parts.append(f'<line x1="{x1}" y1="{ya}" x2="{x2 + BOX_W + 2}" y2="{yb}" stroke="{NAVY}" stroke-width="1.5"'
                         f' marker-end="url(#arrow)"/>')
            parts.append(_label((x1 + x2 + BOX_W) / 2, yb - 10, text, owner))
            continue
        xs = x1 + BOX_W
        if link["from"] != "processor":  # 同一行：横向箭头
            parts.append(f'<line x1="{xs}" y1="{ya}" x2="{x2 - 2}" y2="{yb}" stroke="{NAVY}" stroke-width="1.5"'
                         f' marker-end="url(#arrow)"/>')
            xl = (xs + x2) / 2
        else:  # 处理器分到各面：先横、再竖、再横；字写在最后一段，避开竖线
            xm = xs + GAP / 3
            parts.append(f'<path d="M{xs},{ya} H{xm} V{yb} H{x2 - 2}" fill="none" stroke="{NAVY}" stroke-width="1.5"'
                         f' marker-end="url(#arrow)"/>')
            xl = (xm + x2) / 2
        parts.append(_label(xl, yb - 10, text, owner))
        if note:
            parts.append(_label(xl, yb + 20, note, owner))
    parts.append("</svg>")
    return "".join(parts)
