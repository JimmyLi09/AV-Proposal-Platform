"""《项目需求单》Excel 模板（2026-11-21 Jimmy）。

栏名和读取规则（extract.fields.LABELS）对得上：上传到 02–04 后按「栏名在左、值在右」读，置信度高（A 级），
不用逐项确认。LED 和投影各一份；「填写说明」页只给人看，平台不读（里面有示例值）。
"""
import io

from fastapi import APIRouter, HTTPException, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

router = APIRouter()

# (栏名——要能被 LABELS 认出来, 写法, 示例, 下拉选项)
LED = [
    ("屏宽 Screen width (mm)", "数字，毫米；弧形 / 多面屏写展开后的总宽，每一面在平台里再分", "4480", None),
    ("屏高 Screen height (mm)", "数字，毫米", "2560", None),
    ("点间距 Pixel pitch (mm)", "数字，例 2.5；不确定可空着", "2.5", None),
    ("使用环境 Environment", "下拉选", "室内", ["室内", "户外", "租赁"]),
    ("安装方式 Installation", "下拉选", "壁挂", ["壁挂", "落地", "吊装", "嵌入"]),
    ("维护方式 Maintenance", "下拉选", "前维护", ["前维护", "后维护"]),
    ("亮度要求 Brightness (nits)", "数字；不知道可空着（室内常用 600–800，户外 5000 以上）", "600", None),
    ("观看距离 Viewing distance (m)", "范围，例 4-6", "4-6", None),
    ("信号源数量 Signal sources", "数字，同时要接进来的信号路数", "1", None),
]
PJ = [
    ("墙宽 Wall width (mm)", "数字，毫米；投影画面总宽", "18325", None),
    ("墙高 Wall height (mm)", "数字，毫米；投影画面高", "2700", None),
    ("可用进深 Available depth (mm)", "数字，毫米；投影机到墙最多能放多远", "3200", None),
    ("天花高度 Ceiling height (mm)", "数字，毫米", "3000", None),
    ("投影安装方式 Projector mount", "下拉选", "吊装", ["吊装", "落地", "壁挂"]),
    ("镜头高度 Lens height (m)", "数字，米；镜头离地高度", "2.8", None),
    ("环境光 Ambient light (lux)", "数字；不知道可空着（展厅常见 100–300）", "150", None),
    ("幕面增益 Surface gain", "数字；白墙 / 普通幕 1.0", "1.0", None),
    ("最近观看距离 Nearest viewing (m)", "数字，米", "1.5", None),
    ("信号距离 Signal run (m)", "数字，米；播放源到投影机的走线长度", "35", None),
    ("中控 Central control", "下拉选：有中控（PJLink 网络控制）/ 无", "无", ["有（PJLink）", "无"]),
    ("机房功率口径 Server room power", "下拉选：机房电源按全部设备算，还是只算播放电脑", "全部设备", ["全部设备", "只算播放电脑"]),
]
FORMS = {"LED": ("LED 屏项目需求单", LED), "PJ": ("投影项目需求单", PJ)}
INFO = ["项目名称", "客户", "地点", "期望交付", "填写人 / 日期"]  # 只给人看，平台不读

HEAD = PatternFill("solid", fgColor="1F2A44")
FILL = PatternFill("solid", fgColor="FFF7E0")


def build(line: str) -> bytes:
    title, rows = FORMS[line]
    wb = Workbook()
    ws = wb.active
    ws.title = "需求单"
    ws["A1"] = f"Audax · {title}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "黄色格子填值，一格一个；不知道的空着，平台会标「待确定」。填好后上传到项目 02–04，或放进服务器项目文件夹。"
    ws["A2"].font = Font(italic=True, color="666666")
    r = 4
    for name in INFO:
        ws.cell(r, 1, name)
        r += 1
    r += 1
    for col, text_ in ((1, "项目"), (2, "填写")):
        cell = ws.cell(r, col, text_)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), HEAD
    first = r + 1
    for i, (label, _, _, options) in enumerate(rows):
        row = first + i
        ws.cell(row, 1, label).font = Font(bold=True)
        ws.cell(row, 2).fill = FILL
        if options:
            dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(ws.cell(row, 2))
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 22
    ws.freeze_panes = ws.cell(first, 1)

    help_ws = wb.create_sheet("填写说明")
    help_ws.append(["项目", "写法", "示例"])
    for cell in help_ws[1]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), HEAD
    for label, how, example, _ in rows:
        help_ws.append([label, how, example])
    help_ws.append([])
    help_ws.append(["只有图片的项目", "尽量让对方在图上写明「屏宽 / W」「屏高 / H」或「宽×高」，例 W4480×H2560；"
                    "截图别缩太小；图上写「P2.5 LED SCREEN」这类标题平台更容易找到屏体", ""])
    for col, width in zip("ABC", (34, 70, 14)):
        help_ws.column_dimensions[col].width = width
    for row in help_ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/templates/requirement/{line}.xlsx")
def download(line: str):
    if line not in FORMS:
        raise HTTPException(404)
    name = "requirement-form-LED.xlsx" if line == "LED" else "requirement-form-projection.xlsx"
    return Response(build(line), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
