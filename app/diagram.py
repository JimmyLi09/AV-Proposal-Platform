"""Level 1 概念图：信号从左到右，电源从下方的配电箱接入。生成 SVG，界面和 Proposal（第 6 步）共用同一张。"""
from html import escape

from .i18n import tr

BOX_W, BOX_H, GAP, V_GAP, PAD = 200, 84, 150, 80, 24
NAVY, MUTED, ORANGE = "#15203A", "#6B6558", "#C2410C"
FONT = "-apple-system, 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif"


def _box(x: float, y: float, node: dict) -> str:
    dashed = ' stroke-dasharray="6 4"' if node["supply"] != "boq" else ""
    qty = node["qty"] if isinstance(node["qty"], str) else f"× {node['qty']}"
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
        text = f"{link['cable']} × {link['qty']}"
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
