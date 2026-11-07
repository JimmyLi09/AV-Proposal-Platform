"""第 6 步：方案演示稿 Deck（PPT，方案「方案演示稿 Deck」）。

和 PDF / Word 用同一份 Rev 数据（proposal_doc.content），16:9。文字和表格都是原生可编辑对象，示意图和标注图是图片，
可以整张换。封面字段（标题、项目名、项目编号、客户、地点、日期）可以在平台里改，随 Rev 保存；封面和最后一页固定，
其余页可以勾掉。每页 AUDAX 页眉、Confidential 页脚和页码；不显示价格。未批准只出带 DRAFT 水印的草稿。
公司 .potx 母版放在服务器上并在 deploy.local.yaml 的 deck_template 写路径后，按母版出；没有就用内置的 Audax 配色版式。
"""
import io
import zipfile
from datetime import date
from pathlib import Path

from .i18n import tr, use

NAVY, MUTED, ORANGE = (0x15, 0x20, 0x3A), (0x6B, 0x65, 0x58), (0xC2, 0x41, 0x0C)

# 默认页序（封面、最后一页固定）
SLIDES = {
    "LED": ["cover", "overview", "config", "diagram", "schematic", "drawing", "annotated", "boq", "risks", "next"],
    "PJ": ["cover", "overview", "config", "diagram", "schematic", "annotated", "boq", "risks", "next"],
}
FIXED = {"cover", "next"}
COVER_FIELDS = ["title", "project", "project_no", "client", "location", "date"]


def slide_title(key: str) -> str:
    return {
        "cover": tr("封面", "Cover"), "overview": tr("项目概况", "Project overview"),
        "config": tr("推荐配置", "Recommended configuration"), "diagram": tr("系统图 L1", "System diagram"),
        "schematic": tr("示意图 L2", "Schematic"), "drawing": tr("拼接与线路图", "Cabinet and cabling drawing"),
        "annotated": tr("标注图", "Annotated drawing"), "boq": tr("数量与 BOQ", "Quantities and BOQ"),
        "risks": tr("风险与假设", "Risks and assumptions"), "next": tr("下一步与联系", "Next steps and contact"),
    }[key]


def available(line: str, have: set) -> list[str]:
    """这个方案实际有内容的页（没有图纸或标注副本的页不出）。have：方案文档里有的章节。"""
    need = {"diagram": "diagram", "schematic": "links", "drawing": "drawing", "annotated": "annotated", "boq": "boq"}
    return [k for k in SLIDES[line] if k not in need or need[k] in have]


def sections_of(view: dict) -> set:
    """不生成整份文档，直接从工作页数据判断有哪些章节（和 proposal_doc.content 的规则一致）。"""
    result = view["result"] or {}
    have = set()
    if result.get("diagram"):
        have |= {"diagram", "links"}
    if view.get("drawing"):
        have.add("drawing")
    if view.get("boq"):
        have.add("boq")
    if any(d.get("copy_path") for d in (view["rev"].get("annotations") or {}).values()):
        have.add("annotated")
    return have


def cover_defaults(project, prop, rev) -> dict:
    when = (rev.reviewed_at.date() if rev.reviewed_at and rev.status == "approved" else date.today()).isoformat()
    return {"title": tr("方案建议书", "Proposal") + f" · {prop.name}", "project": project.name,
            "project_no": project.project_no or "", "client": project.client, "location": project.location or "", "date": when}


def settings_view(line: str, have: set, saved: dict | None, defaults: dict) -> dict:
    saved = saved or {}
    off = set(saved.get("off") or [])
    return {"slides": [{"key": k, "title": slide_title(k), "fixed": k in FIXED, "included": k in FIXED or k not in off}
                       for k in available(line, have)],
            "cover": defaults | {k: v for k, v in (saved.get("cover") or {}).items() if v},
            "cover_defaults": defaults}


# ---------- PPT ----------

def _open(template: Path | None):
    """.potx 母版：python-pptx 只认 .pptx，把内容类型改成演示文稿再打开（原文件不动）。"""
    from pptx import Presentation
    from pptx.util import Emu
    if template and template.exists():
        buf = io.BytesIO()
        with zipfile.ZipFile(template) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = data.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
                dst.writestr(item, data)
        buf.seek(0)
        return Presentation(buf), True
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)  # 16:9
    return prs, False


def _layout(prs, *names):
    for n in names:
        for lay in prs.slide_layouts:
            if lay.name.lower() == n.lower():
                return lay
    return prs.slide_layouts[len(prs.slide_layouts) - 1]


def _rgb(c):
    from pptx.dml.color import RGBColor
    return RGBColor(*c)


def _text(slide, x, y, w, h, text, size=14, bold=False, color=NAVY, align=None):
    from pptx.util import Pt
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(text if isinstance(text, list) else [text]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        if align:
            p.alignment = align
        for r in p.runs:
            r.font.size, r.font.bold, r.font.color.rgb = Pt(size), bold, _rgb(color)
    return box


def _table(slide, x, y, w, rows, head=None, size=11, widths=None):
    from pptx.util import Emu, Pt
    data = ([head] if head else []) + rows
    n_rows, n_cols = len(data), max(len(r) for r in data)
    shape = slide.shapes.add_table(n_rows, n_cols, x, y, w, Emu(int(320000 * n_rows)))
    table = shape.table
    table.first_row = bool(head)  # 没有表头时第一行不用表头样式
    if widths:
        for i, f in enumerate(widths):
            table.columns[i].width = Emu(int(w * f))
    for r, row in enumerate(data):
        for c in range(n_cols):
            cell = table.cell(r, c)
            cell.text = str(row[c]) if c < len(row) else ""
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(size)
                    run.font.bold = bool(head) and r == 0
    return shape


def build(doc: dict, docs_other: dict | None, line: str, settings: dict, lang: str, author: str,
          template: Path | None, png) -> bytes:
    """doc：导出语言的内容；lang = bi 时 doc 是英文、docs_other 是中文，标题写两种语言。png：SVG → PNG。"""
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Pt

    prs, branded = _open(template)
    W, H = prs.slide_width, prs.slide_height
    M = Emu(int(W * 0.05))
    by_key = {s["key"]: s for s in doc["sections"]}
    other = {s["key"]: s for s in (docs_other or {}).get("sections", [])}
    # 内置版式用空白页、自己画标题（默认母版是 4:3 的占位符）；公司母版用它的版式
    content_layout = _layout(prs, "Title Only", "Blank") if branded else _layout(prs, "Blank")
    title_layout = _layout(prs, "Title Slide", "Title Only") if branded else _layout(prs, "Blank")
    need = {"diagram": "diagram", "schematic": "links", "drawing": "drawing", "annotated": "annotated", "boq": "boq"}
    keys = [s["key"] for s in settings["slides"] if s["included"] and (s["key"] not in need or need[s["key"]] in by_key)]
    titles = {s["key"]: s["title"] for s in settings["slides"]}
    if lang == "bi":
        with use("zh"):
            zh_titles = {k: slide_title(k) for k in titles}
        titles = {k: f"{v} · {zh_titles[k]}" for k, v in titles.items()}

    def chrome(slide, no):
        """页眉、页脚、页码、DRAFT 水印。公司母版自带页眉页脚时不重复加。"""
        if doc["draft"]:
            mark = _text(slide, Emu(int(W * 0.15)), Emu(int(H * 0.35)), Emu(int(W * 0.7)), Emu(int(H * 0.3)), "DRAFT",
                         size=120, bold=True, color=(0xF4, 0xD9, 0xCC), align=PP_ALIGN.CENTER)
            mark.rotation = -25
            slide.shapes._spTree.remove(mark._element)  # 放到最底层，不挡内容
            slide.shapes._spTree.insert(2, mark._element)
        if not branded:
            _text(slide, M, Emu(int(H * 0.025)), Emu(int(W * 0.4)), Emu(int(H * 0.06)), "AUDAX", size=14, bold=True)
            _text(slide, M, Emu(int(H * 0.93)), Emu(int(W * 0.75)), Emu(int(H * 0.05)),
                  f"Confidential · {doc['stamp']}", size=9, color=MUTED)
            _text(slide, Emu(int(W * 0.88)), Emu(int(H * 0.93)), Emu(int(W * 0.07)), Emu(int(H * 0.05)), str(no),
                  size=9, color=MUTED, align=PP_ALIGN.RIGHT)

    def heading(slide, text):
        if slide.shapes.title is not None:
            slide.shapes.title.text = text
            return
        _text(slide, M, Emu(int(H * 0.09)), W - 2 * M, Emu(int(H * 0.1)), text, size=26, bold=True)

    def body_top():
        return Emu(int(H * 0.22))

    for no, key in enumerate(keys, 1):
        if key == "cover":
            s = prs.slides.add_slide(title_layout)
            c = settings["cover"]
            lines = [f"{c['project']}" + (f" · {c['project_no']}" if c.get("project_no") else ""),
                     f"{c['client']}" + (f" · {c['location']}" if c.get("location") else ""),
                     f"{c['date']} · Rev {doc['rev_no']}"]
            if s.shapes.title is not None:
                s.shapes.title.text = c["title"]
                placeholders = [p for p in s.placeholders if p.placeholder_format.idx != 0]
                if placeholders:
                    placeholders[0].text = "\n".join(lines)
                else:
                    _text(s, M, Emu(int(H * 0.6)), W - 2 * M, Emu(int(H * 0.25)), lines, size=16, color=MUTED)
            else:
                _text(s, M, Emu(int(H * 0.3)), W - 2 * M, Emu(int(H * 0.2)), c["title"], size=36, bold=True)
                _text(s, M, Emu(int(H * 0.55)), W - 2 * M, Emu(int(H * 0.25)), lines, size=16, color=MUTED)
            chrome(s, no)
            continue
        s = prs.slides.add_slide(content_layout)
        heading(s, titles[key])
        top, width = body_top(), W - 2 * M
        if key == "overview":
            paras = by_key["concept"]["paragraphs"] + (other["concept"]["paragraphs"] if other else [])
            _text(s, M, top, width, Emu(int(H * 0.6)), paras, size=16)
        elif key == "config":
            rows = [list(r) for r in by_key["config"]["rows"]]
            if other:
                rows = [[f"{a} · {b[0].split(' · ', 1)[-1]}", v] for (a, v), b in zip(rows, other["config"]["rows"])]
            _table(s, M, top, width, rows[:14], size=11, widths=[0.55, 0.45])
        elif key in ("diagram", "drawing"):
            img = png(by_key[key]["svg"])
            pic = s.shapes.add_picture(io.BytesIO(img), M, top, width=width)
            if pic.height > H * 0.68:  # 太高就按高度缩
                ratio = (H * 0.68) / pic.height
                pic.height, pic.width = int(pic.height * ratio), int(pic.width * ratio)
        elif key == "schematic":
            sec = by_key["links"]
            head, *nodes = sec["nodes"]
            _table(s, M, top, width, nodes, head=head, size=10, widths=[0.25, 0.25, 0.15, 0.35])
            _table(s, M, Emu(int(top + 320000 * (len(nodes) + 1.6))), width, sec["table"]["rows"],
                   head=sec["table"]["head"], size=10)
        elif key == "annotated":
            img = by_key["annotated"]["images"][0]
            pic = s.shapes.add_picture(img["path"], M, top, height=Emu(int(H * 0.62)))
            if pic.width > width:
                ratio = width / pic.width
                pic.height, pic.width = int(pic.height * ratio), int(pic.width * ratio)
        elif key == "boq":
            b = by_key["boq"]["boq"]
            rows = [[str(r["no"]), r["title"] + "".join(f"\n- {x}" for x in r.get("specs") or []), _qty(r["qty"]), r["unit"]]
                    for r in b["rows"]]
            _table(s, M, top, width, rows, head=["No.", "Description", "Qty", "Unit"], size=9,
                   widths=[0.06, 0.74, 0.1, 0.1])
        elif key == "risks":
            bullets = by_key["risks"]["bullets"]
            _text(s, M, top, width, Emu(int(H * 0.65)), [f"• {x}" for x in bullets[:10]], size=14)
        elif key == "next":
            with use("en" if lang == "bi" else lang):
                steps = [tr("现场勘测：确认墙体、电源点和走线", "Site survey: confirm wall, power point and cable routes"),
                         tr("确认内容来源和播放方式", "Confirm content sources and playback"),
                         tr("勘测后出正式方案", "Final proposal after the survey")]
                contact = tr("联系人", "Contact") + f"：{author}" if lang == "zh" else f"Contact: {author}"
            _text(s, M, top, width, Emu(int(H * 0.5)), [f"• {x}" for x in steps] + ["", contact + " · Audax"], size=16)
        chrome(s, no)

    core = prs.core_properties
    core.title, core.subject, core.keywords = settings["cover"]["title"], doc["stamp"], doc["stamp"]
    core.comments, core.author = doc["stamp"], "AV Proposal Platform"
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _qty(v) -> str:
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return "—" if v is None else str(v)
