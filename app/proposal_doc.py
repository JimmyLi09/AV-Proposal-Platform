"""第 6 步：方案文档输出——PDF、可编辑 Word、JPG Boards。

三种格式用同一份内容（content()），章节按方案「Proposal 输出」：概述、推荐配置、BOQ、系统图（Level 1）、
连接与线缆（Level 2）、拼接与线路图、标注图、风险与假设、计算依据。叙述段落由固定句式按条件拼装，不经任何模型。
文件属性写入 Rev、规则版本、产品库版本、模板版本；没批准的 Rev 每页带 DRAFT 水印。
"""
import io
import zipfile
from contextlib import contextmanager
from datetime import date
from html import escape
from pathlib import Path

from . import drawing_export, pj_drawings
from . import workspace as ws
from .i18n import tr, use
from .models import Project, Proposal, Revision

NAVY, MUTED, ORANGE, LINE = "#15203A", "#6B6558", "#C2410C", "#E6E0D6"
FONT = drawing_export.FONT
TILES = {
    "LED": ["F4", "F2", "F3", "F10", "F5", "F6", "F7", "F9", "F11", "F13", "F12"],
    "PJ": ["P2", "P3", "P4", "P5", "P7", "P8", "P9", "P11", "P14", "P12", "P15", "P16"],
}


def _n(v) -> str:
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return "—" if v is None else str(v)


OPTIONS = {"indoor": ("室内", "indoor"), "outdoor": ("户外", "outdoor"), "rental": ("租赁", "rental"),
           "wall": ("壁挂", "wall-mounted"), "floor": ("落地", "floor-standing"), "hanging": ("吊装", "hung"),
           "embedded": ("嵌入式", "embedded")}


def _concept(prop: Proposal, project: Project, v: dict) -> list[str]:
    """概述：按业务线和输入拼句子。"""
    result, inputs = v["result"], v["rev"]["inputs"]
    where = project.location or project.name
    if result.get("faces"):
        faces = "；".join(f"{f['id']} {_n(f.get('width_mm'))} × {_n(f.get('height_mm'))} mm" for f in result["faces"])
        faces_en = "; ".join(f"{f['id']} {_n(f.get('width_mm'))} × {_n(f.get('height_mm'))} mm" for f in result["faces"])
        n = len(result["faces"])
        return [tr(f"{where}：多面{'LED 屏' if prop.business_line == 'LED' else '投影'}，共 {n} 面（{faces}）。每面单独计算，再合成一张展开画布。",
                   f"{where}: a {n}-face {'LED screen' if prop.business_line == 'LED' else 'projection'} ({faces_en}). "
                   "Each face is calculated on its own and combined into one unfolded canvas.")]
    x = result["values"]
    if prop.business_line == "LED":
        env = OPTIONS.get(inputs.get("environment"), ("", ""))
        inst = OPTIONS.get(inputs.get("installation"), ("", ""))
        return [tr(
            f"{where}：一块 P{_n(x.get('pixel_pitch_mm'))} {env[0]} LED 屏，"
            f"{_n(x.get('width_mm'))} × {_n(x.get('height_mm'))} mm（{_n(x.get('area_m2'))} ㎡），{inst[0]}，"
            f"分辨率 {_n(x.get('res_x'))} × {_n(x.get('res_y'))}，箱体 {x.get('cabinet_model', '—')}。",
            f"{where}: one P{_n(x.get('pixel_pitch_mm'))} {env[1]} LED screen, "
            f"{_n(x.get('width_mm'))} × {_n(x.get('height_mm'))} mm ({_n(x.get('area_m2'))} ㎡), {inst[1]}, "
            f"resolution {_n(x.get('res_x'))} × {_n(x.get('res_y'))}, cabinet {x.get('cabinet_model', '—')}.")]
    return [tr(
        f"{where}：投影融合墙 {_n(inputs.get('wall_width_mm'))} × {_n(inputs.get('wall_height_mm'))} mm，"
        f"{_n(x.get('projectors'))} 台 {x.get('projector_model', '—')} 横向融合。",
        f"{where}: a blended projection wall {_n(inputs.get('wall_width_mm'))} × {_n(inputs.get('wall_height_mm'))} mm, "
        f"{_n(x.get('projectors'))} × {x.get('projector_model', '—')} blended horizontally.")]


STANDARD_RISKS = {
    "LED": [
        ("电源接驳点距屏幕的距离按假设计算（文件中未提供时）。", "The distance from the power point to the screen is assumed where the files do not state it."),
        ("墙体须能承受屏体荷载，结构核算由他方负责。", "The wall must carry the screen load; structural checks are by others."),
        ("数量以现场勘测和厂家深化为准。", "Quantities are subject to site survey and manufacturer detailing."),
        ("不含土建、市电引入和网络布线。", "Civil works, mains supply and network cabling are excluded."),
    ],
    "PJ": [
        ("融合带可能偏亮，需要现场调校。", "Blend zones may look brighter and need on-site tuning."),
        ("画面清晰度受像素尺寸限制。", "Image sharpness is limited by the pixel size on the wall."),
        ("天花过矮会影响投影机安装。", "A low ceiling can limit projector mounting."),
        ("天花或建筑抖动可能导致融合错位。", "Ceiling or building vibration can misalign the blend."),
    ],
}


def _risks(prop: Proposal, v: dict) -> list[str]:
    result = v["result"]
    out = [tr(*x) for x in STANDARD_RISKS[prop.business_line]]
    if any(r.get("status") == "sample" for r in result.get("rules") or []):
        out.append(tr("部分系数是示例值，以最终确认的数值为准。", "Some coefficients are sample values, pending final confirmation."))
    for m in v["overrides"]:
        out.append(tr(f"{m['rule']} {m['title']}：规则值 {m['rule_display']}，手动改为 {m['display']}（{m['reason']}）。",
                      f"{m['rule']} {m['title']}: rule value {m['rule_display']}, set manually to {m['display']} ({m['reason']})."))
    for r in result.get("rules") or []:
        if r.get("check") == "NOTE":
            out.append(tr(f"{r['id']} {r['title']}：{r['display']}", f"{r['id']} {r['title']}: {r['display']}"))
    for c in (result.get("multi") or {}).get("checks") or []:
        if c.get("check") == "NOTE":
            out.append(c["text"])
    return out


def content(db, prop: Proposal, rev: Revision, lang: str, data_dir: Path) -> dict:
    """一个 Rev 的方案文档内容（按 lang）。没算完的 Rev 不能出文档。"""
    from fastapi import HTTPException
    with use(lang):
        v = ws.view(db, prop, rev)
        result = v["result"]
        if not result or not result.get("rules"):
            raise HTTPException(409, tr("还没有计算结果，算完才能导出方案", "No results yet; calculate before exporting the proposal"))
        project = db.get(Project, prop.project_id)
        draft = rev.status != "approved"
        stamp = " · ".join([f"Rev {rev.rev_no}", tr("规则 ", "Rules ") + v["rules_version"],
                            tr("产品库 ", "Product library ") + v["library_version"],
                            tr("模板 ", "Template ") + v["template_version"]] + (["DRAFT"] if draft else []))
        when = (rev.reviewed_at.date() if rev.reviewed_at and not draft else date.today()).isoformat()
        cover = [(tr("项目", "Project"), project.name), (tr("项目编号", "Project no."), project.project_no or "—"),
                 (tr("客户", "Client"), project.client), (tr("地点", "Location"), project.location or "—"),
                 (tr("方案", "Proposal"), prop.name), (tr("日期", "Date"), when),
                 (tr("版本", "Revision"), f"Rev {rev.rev_no} · " + (tr("草稿（未批准）", "Draft (not approved)") if draft
                                                                    else tr("已批准", "Approved") + f" · {v['reviewer']}"))]
        rules = {r["id"]: r for r in result["rules"]}
        ids = [i for i in TILES[prop.business_line] if i in rules] if not result.get("faces") else list(rules)
        config = [(f"{i} · {rules[i]['title']}", rules[i]["display"] + (tr("（手动）", " (manual)") if rules[i].get("manual") else ""))
                  for i in ids if rules[i].get("display")]
        sections = [
            {"key": "concept", "title": tr("概述", "Concept"), "paragraphs": _concept(prop, project, v)},
            {"key": "config", "title": tr("推荐配置", "Recommended configuration"), "rows": config},
        ]
        if v["boq"]:
            sections.append({"key": "boq", "title": tr("工程量清单（BOQ）", "Bill of quantities (BOQ)"), "boq": v["boq"]})
        diagram = result.get("diagram")
        if diagram:
            sections.append({"key": "diagram", "title": tr("系统图（Level 1）", "System diagram (Level 1)"), "svg": diagram["svg"]})
            names = {k: n["title"] for k, n in diagram["nodes"].items()} | {"db_box": tr("配电箱", "DB box")}
            sections.append({"key": "links", "title": tr("连接与线缆（Level 2）", "Connections and cables (Level 2)"),
                             "table": {"head": [tr("起点", "From"), tr("终点", "To"), tr("线缆", "Cable"), tr("数量", "Qty")],
                                       "rows": [[names.get(x["from"], x["from"]), names.get(x["to"], x["to"]), x["cable"], x["qty"]]
                                                for x in diagram["links"]]},
                             "nodes": [[tr("设备", "Equipment"), tr("型号", "Model"), tr("数量", "Qty"), tr("说明", "Notes")]]
                             + [[n["title"], str(n["model"]), _n(n["qty"]), n["detail"]] for n in diagram["nodes"].values()]})
        if v["drawing"]:
            meta = {"project": f"{project.name} · {prop.name}", "stamp": stamp, "draft": draft, "values": result["values"]}
            sections.append({"key": "drawing", "title": tr("拼接与线路图", "Cabinet and cabling drawing"),
                             "svg": drawing_export.svg(v["drawing"], meta, lang)})
        if v["projection"]:  # 投影专属图（第 8 步）：立面融合区、平面机位、剖面遮挡
            for kind, title in pj_drawings.titles().items():
                sections.append({"key": f"pj_{kind}", "title": title, "svg": pj_drawings.svg(kind, v["projection"], stamp)})
        images = [{"path": str(data_dir / doc["copy_path"]), "caption": doc.get("copy_name", "")}
                  for doc in (rev.annotations or {}).values() if doc.get("copy_path") and (data_dir / doc["copy_path"]).exists()]
        if images:
            sections.append({"key": "annotated", "title": tr("标注图", "Annotated drawings"), "images": images})
        sections.append({"key": "risks", "title": tr("风险与假设", "Risks and assumptions"), "bullets": _risks(prop, v)})
        sections.append({"key": "basis", "title": tr("附录：计算依据", "Appendix: calculation basis"),
                         "table": {"head": [tr("规则", "Rule"), tr("项目", "Item"), tr("公式（代入数值）", "Formula (with values)"),
                                            tr("结果", "Result")],
                                   "rows": [[r["id"], r["title"], r.get("trace") or "", r.get("display") or ""]
                                            for r in result["rules"]]}})
        title = tr("方案建议书", "Proposal") + f" · {prop.name}"
    return {"title": title, "project": project.name, "client": project.client, "stamp": stamp, "draft": draft,
            "lang": lang, "cover": cover, "sections": sections, "rev_no": rev.rev_no,
            "versions": {k: v[k] for k in ("rules_version", "library_version", "template_version")}}


# ---------- HTML（PDF 和 JPG Boards 共用） ----------

CSS = f"""
body {{ font-family: {FONT}; color: {NAVY}; margin: 0; font-size: 12px; }}
h1 {{ font-size: 24px; margin: 0 0 6px; }} h2 {{ font-size: 16px; margin: 18px 0 8px; border-bottom: 2px solid {ORANGE}; padding-bottom: 4px; }}
.brand {{ font-weight: 800; letter-spacing: 3px; font-size: 14px; }} .muted {{ color: {MUTED}; font-size: 10.5px; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid {LINE}; padding: 5px 7px; text-align: left; vertical-align: top; }}
th {{ background: #FAF8F4; }} .group td {{ background: #E8EEF8; font-weight: 700; }} .num {{ text-align: right; white-space: nowrap; }}
.spec {{ color: #3B3A36; padding-left: 8px; }} .note {{ font-style: italic; color: {MUTED}; }}
svg {{ max-width: 100%; height: auto; }} img {{ max-width: 100%; }} .mono {{ font-family: Consolas, monospace; font-size: 10.5px; }}
.cover td:first-child {{ width: 28%; color: {MUTED}; }}
.watermark {{ position: fixed; top: 40%; left: 0; right: 0; text-align: center; transform: rotate(-30deg); font-size: 120px;
  font-weight: 800; color: rgba(194, 65, 12, 0.13); z-index: 10; pointer-events: none; }}
section {{ break-inside: avoid-page; }}
"""


def _section_html(s: dict) -> str:
    out = [f"<section><h2>{escape(s['title'])}</h2>"]
    for p in s.get("paragraphs", []):
        out.append(f"<p>{escape(p)}</p>")
    if "rows" in s:
        out.append("<table>" + "".join(f"<tr><td>{escape(a)}</td><td><b>{escape(b)}</b></td></tr>" for a, b in s["rows"]) + "</table>")
    if "boq" in s:
        b = s["boq"]
        rows = [f"<tr><th>No.</th><th>Description</th><th class='num'>Qty</th><th>Unit</th></tr>"]
        group = None
        for r in b["rows"]:
            g = r.get("group") or b["group"]
            if g != group:
                group = g
                rows.append(f"<tr class='group'><td colspan='4'>{escape(g)}</td></tr>")
            desc = f"<b>{escape(r['title'])}</b>" + "".join(f"<div class='spec'>- {escape(x)}</div>" for x in r.get("specs") or [])
            if r.get("note"):
                desc += f"<div class='note'>*{escape(r['note'])}</div>"
            rows.append(f"<tr><td>{r['no']}</td><td>{desc}</td><td class='num'>{escape(_n(r['qty']))}</td><td>{escape(r['unit'])}</td></tr>")
        out.append("<table>" + "".join(rows) + "</table>")
    if "svg" in s:
        out.append(f"<div>{s['svg']}</div>")
    if "nodes" in s:
        head, *rows = s["nodes"]
        out.append("<table><tr>" + "".join(f"<th>{escape(h)}</th>" for h in head) + "</tr>"
                   + "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows) + "</table><br>")
    if "table" in s:
        t = s["table"]
        mono = s["key"] == "basis"
        out.append("<table><tr>" + "".join(f"<th>{escape(h)}</th>" for h in t["head"]) + "</tr>"
                   + "".join("<tr>" + "".join(f"<td class='{'mono' if mono and i == 2 else ''}'>{escape(str(c))}</td>"
                                              for i, c in enumerate(row)) + "</tr>" for row in t["rows"]) + "</table>")
    for img in s.get("images", []):
        out.append(f"<figure><img src='{Path(img['path']).as_uri()}'><figcaption class='muted'>{escape(img['caption'])}</figcaption></figure>")
    if "bullets" in s:
        out.append("<ul>" + "".join(f"<li>{escape(x)}</li>" for x in s["bullets"]) + "</ul>")
    out.append("</section>")
    return "".join(out)


def _cover_html(doc: dict) -> str:
    rows = "".join(f"<tr><td>{escape(a)}</td><td><b>{escape(b)}</b></td></tr>" for a, b in doc["cover"])
    return (f"<div class='brand'>AUDAX</div><div class='muted'>AV PROPOSAL PLATFORM</div><br>"
            f"<h1>{escape(doc['title'])}</h1><div class='muted'>{escape(doc['stamp'])}</div><br>"
            f"<table class='cover'>{rows}</table>")


def html(doc: dict) -> str:
    mark = "<div class='watermark'>DRAFT</div>" if doc["draft"] else ""
    body = _cover_html(doc) + "".join(_section_html(s) for s in doc["sections"])
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{mark}{body}</body></html>"


@contextmanager
def _browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


def pdf(doc: dict) -> bytes:
    from pypdf import PdfReader, PdfWriter
    footer = (f"<div style='font-size:8px;width:100%;padding:0 12mm;color:{MUTED};display:flex;justify-content:space-between'>"
              f"<span>AUDAX · Confidential · {escape(doc['stamp'])}</span>"
              "<span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>")
    with _browser() as b:
        page = b.new_page()
        page.set_content(html(doc), wait_until="load")
        raw = page.pdf(format="A4", print_background=True, display_header_footer=True, header_template="<span></span>",
                       footer_template=footer, margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(raw)))
    writer.add_metadata({"/Title": doc["title"], "/Subject": doc["stamp"], "/Keywords": doc["stamp"],
                         "/Creator": "AV Proposal Platform"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


BOARD_GROUPS = [["concept", "config"], ["boq"], ["diagram", "links"], ["drawing"], ["pj_elevation"], ["pj_plan", "pj_section"],
                ["annotated"]]


def boards(doc: dict) -> bytes:
    """JPG Boards：16:9 的展示板，每块一张 JPG，打包成 ZIP。封面一块，其余按章节分组（风险与计算依据不出板）。"""
    by_key = {s["key"]: s for s in doc["sections"]}
    groups = [None] + [[by_key[k] for k in g if k in by_key] for g in BOARD_GROUPS]
    groups = [g for g in groups if g is None or g]
    mark = "<div class='mark'>DRAFT</div>" if doc["draft"] else ""
    css = CSS + (f".board {{ width: 1600px; height: 900px; box-sizing: border-box; padding: 48px 56px; position: relative;"
                 f" overflow: hidden; background: #fff; border-bottom: 1px solid {LINE}; }}"
                 f".foot {{ position: absolute; left: 56px; right: 56px; bottom: 18px; font-size: 11px; color: {MUTED}; }}"
                 ".board svg { max-height: 600px; } .board img { max-height: 620px; }"
                 ".mark { position: absolute; top: 360px; left: 0; right: 0; text-align: center; transform: rotate(-20deg);"
                 " font-size: 160px; font-weight: 800; color: rgba(194, 65, 12, 0.13); }")
    parts = []
    for g in groups:
        inner = _cover_html(doc) if g is None else "".join(_section_html(s) for s in g)
        parts.append(f"<div class='board'><div class='inner'>{inner}</div>"
                     f"<div class='foot'>AUDAX · Confidential · {escape(doc['stamp'])}</div>{mark}</div>")
    page_html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(parts)}</body></html>"
    buf = io.BytesIO()
    with _browser() as b, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        page = b.new_page(viewport={"width": 1600, "height": 900})
        page.set_content(page_html, wait_until="load")
        # 内容超过一块板的高度时整体缩小，不截掉（例如很长的 BOQ）
        page.evaluate("""() => document.querySelectorAll('.inner').forEach((el) => {
            const room = 900 - 48 - 40; if (el.scrollHeight > room) el.style.zoom = room / el.scrollHeight; })""")
        for i, el in enumerate(page.query_selector_all(".board"), 1):
            z.writestr(f"Board_{i:02d}.jpg", el.screenshot(type="jpeg", quality=90))
    return buf.getvalue()


def _pngs(svgs: list[str]) -> list[bytes]:
    """Word 不认 SVG：用无头 Chromium 把 SVG 画成 PNG（2 倍清晰度）。"""
    if not svgs:
        return []
    out = []
    with _browser() as b:
        page = b.new_page(device_scale_factor=2)
        for s in svgs:
            page.set_content(f"<html><body style='margin:0;background:#fff'>{s}</body></html>")
            out.append(page.query_selector("svg").screenshot(type="png"))
    return out


def docx(doc: dict) -> bytes:
    """可编辑 Word：标题、段落、表格都是原生对象；图是 PNG 图片，可以整张替换。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    svgs = [s["svg"] for s in doc["sections"] if "svg" in s]
    pngs = iter(_pngs(svgs))
    d = Document()
    sec = d.sections[0]
    sec.left_margin = sec.right_margin = Cm(2)
    style = d.styles["Normal"]
    style.font.name, style.font.size = "Microsoft YaHei", Pt(10)
    head = sec.header.paragraphs[0]
    head.text = "AUDAX · AV Proposal Platform" + ("    DRAFT — " + ("未批准" if doc["lang"] == "zh" else "not approved") if doc["draft"] else "")
    if doc["draft"]:
        for run in head.runs:
            run.font.color.rgb = RGBColor(0xC2, 0x41, 0x0C)
            run.font.bold = True
    foot = sec.footer.paragraphs[0]
    foot.text = f"Confidential · {doc['stamp']}"
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER

    d.add_heading(doc["title"], 0)
    t = d.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for a, b in doc["cover"]:
        cells = t.add_row().cells
        cells[0].text, cells[1].text = a, b
    for s in doc["sections"]:
        d.add_heading(s["title"], 1)
        for p in s.get("paragraphs", []):
            d.add_paragraph(p)
        if "rows" in s:
            t = d.add_table(rows=0, cols=2)
            t.style = "Table Grid"
            for a, b in s["rows"]:
                cells = t.add_row().cells
                cells[0].text, cells[1].text = a, b
        if "boq" in s:
            b = s["boq"]
            t = d.add_table(rows=1, cols=4)
            t.style = "Table Grid"
            for c, h in zip(t.rows[0].cells, ["No.", "Description", "Qty", "Unit"]):
                c.text = h
            group = None
            for r in b["rows"]:
                g = r.get("group") or b["group"]
                if g != group:
                    group = g
                    row = t.add_row().cells
                    merged = row[0].merge(row[3])
                    merged.text = g
                    merged.paragraphs[0].runs[0].font.bold = True
                cells = t.add_row().cells
                cells[0].text = str(r["no"])
                cells[1].text = r["title"]
                cells[1].paragraphs[0].runs[0].font.bold = True
                for x in r.get("specs") or []:
                    cells[1].add_paragraph(f"- {x}")
                if r.get("note"):
                    cells[1].add_paragraph(f"*{r['note']}").runs[0].font.italic = True
                cells[2].text, cells[3].text = _n(r["qty"]), r["unit"]
        if "svg" in s:
            d.add_picture(io.BytesIO(next(pngs)), width=Cm(17))
        if "nodes" in s:
            t = d.add_table(rows=0, cols=4)
            t.style = "Table Grid"
            for row in s["nodes"]:
                for c, x in zip(t.add_row().cells, row):
                    c.text = x
            d.add_paragraph()
        if "table" in s:
            tb = s["table"]
            t = d.add_table(rows=1, cols=len(tb["head"]))
            t.style = "Table Grid"
            for c, h in zip(t.rows[0].cells, tb["head"]):
                c.text = h
            for row in tb["rows"]:
                for c, x in zip(t.add_row().cells, row):
                    c.text = str(x)
        for img in s.get("images", []):
            d.add_picture(img["path"], width=Cm(17))
            d.add_paragraph(img["caption"]).runs[0].font.italic = True
        for x in s.get("bullets", []):
            d.add_paragraph(x, style="List Bullet")
    props = d.core_properties
    props.title, props.subject, props.keywords = doc["title"], doc["stamp"], doc["stamp"]
    props.comments, props.author = doc["stamp"], "AV Proposal Platform"
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()
