"""生成 CR-8 资料库的测试资料（自制，非客户资料；规格书里的数值是编的，不是厂家真实规格）。

用法：python tests/fixtures/knowledge/make_knowledge.py   （需要 requirements-dev.txt 里的 reportlab）
结构和服务器上的资料库文件夹一样：以往项目（一个子文件夹一个项目）、规格书、图纸、BOQ、模板与条款。
"""
import shutil
import zipfile
from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "kb"
SAMPLES = Path(__file__).parent.parent / "samples"


def pdf(path: Path, pages: list[list[str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in pages:
        c.setFont("Helvetica", 12)
        for i, line in enumerate(lines):
            c.drawString(50, 790 - i * 22, line)
        c.showPage()
    c.save()


def boq(path: Path, title: str, rows: list):
    """客户版 BOQ 格式（CR-6）：No. | Description | Qty | Unit，规格行以「-」开头。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws.append([title])
    ws.append(["DRAFT · Rev 0"])
    ws.append([])
    ws.append(["No.", "Description", "Qty", "Unit"])
    ws.append(["", title])
    no = 0
    for r in rows:
        if isinstance(r, str):
            ws.append(["", f"- {r}"])
        else:
            no += 1
            ws.append([no, *r])
    wb.save(path)


def docx(path: Path, paragraphs: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                   f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    # 规格书：一个文件一个型号；选型手册里有好几个型号，不认
    pdf(OUT / "规格书" / "VX1000_Spec_EN.pdf", [
        ["NovaStar VX1000 All-in-one Video Controller", "Overview"],
        ["Specifications", "Loading capacity: 6.5 million pixels", "Outputs: 10 x Gigabit Ethernet ports",
         "Inputs: 6 video inputs", "Power consumption: 32 W"]])
    pdf(OUT / "规格书" / "PT-BHZ611C_datasheet.pdf", [
        ["Panasonic PT-BHZ611C Laser Projector", "Brightness: 6,000 lm", "Resolution: 1920 x 1200 (WUXGA)"],
        ["Power consumption: 460 W", "Weight: 22.7 kg", "Noise: 37 dB"]])
    pdf(OUT / "规格书" / "Controller_Selection_Guide.pdf", [
        ["NovaStar controller selection guide", "VX400: 2.6 million pixels", "VX600: 3.9 million pixels",
         "VX1000: 6.5 million pixels"]])
    # 以往 BOQ：模板里没有的写法（弧形屏、内容制作、培训）会成为建议；数量不是 1 也不按面积的行（接收卡 12 pcs）不收
    boq(OUT / "BOQ" / "Discussion_Area_BOQ.xlsx", "Discussion Area · LED-1", [
        ["P2.5 Indoor LED screen on wall 3200 × 1760 mm", 5.63, "sqm"], "Overall dimension: 3200 × 1760 mm",
        ["P2.5 Curve LED screen on wall 6400 × 3600 mm", 23.04, "sqm"], "Overall dimension: 6400 × 3600 mm",
        "Curve radius R5000",
        ["Video processor", 1, "set"],
        ["Content production (30 s loop video)", 1, "lot"],
        ["Training for operators", 1, "lot"],
        ["Receiving card", 12, "pcs"],
        ["Supply and install metal frame structure (3200 × 1760 mm)", 5.63, "sqm"]])
    # 以往项目：143（标准答案，BOQ 里回路写成 4 路，和规则 3 路不一样）、GMC（U 形）、114（投影）
    pdf(OUT / "以往项目" / "143-Royal Plaza" / "143_Elevation.pdf", [
        ["143 ROYAL PLAZA LOBBY", "INDOOR LED WALL, PIXEL PITCH P2.5", "LED SCREEN 4480 (W) x 2560 (H)",
         "WALL MOUNT, FRONT MAINTENANCE", "BRIGHTNESS 600 NITS", "VIEWING DISTANCE 4-6M"]])
    boq(OUT / "以往项目" / "143-Royal Plaza" / "143_BOQ.xlsx", "Lobby LED Wall · LED-1", [
        ["P2.5 Indoor LED screen on wall 4480 × 2560 mm", 11.47, "sqm"], "Overall dimension: 4480 × 2560 mm",
        "Spares: 12 modules, 1 power supply, 1 receiving card",
        ["Video processor", 1, "set"],
        ["Sending controller", 1, "set"],
        ["Power distribution and cabling", 1, "lot"], "DB box with MCB × 4 circuits",
        "Power cables 4 + 1 spare, data cables CAT6 4 + 1 spare",
        ["Supply and install metal frame structure (4480 × 2560 mm)", 11.47, "sqm"]])
    pdf(OUT / "以往项目" / "GMC Virtual Office" / "GMC_Visuals_Office_r02.pdf", [
        ["GMC VIRTUAL OFFICE - U-SHAPE LED WALL", "LEFT 5760 x 4160 mm, MAIN 8000 x 4160 mm, RIGHT 5760 x 4160 mm",
         "PIXEL PITCH P2.5", "INDOOR LED, WALL MOUNT"]])
    pdf(OUT / "以往项目" / "114 Showroom" / "114_Showroom_Final.pdf", [
        ["114 SHOWROOM PROJECTION WALL", "5 x PT-BHZ611C LASER PROJECTORS, 0.5:1 FIXED LENS",
         "PROJECTION WALL 18325 x 2700 mm", "EDGE BLENDING, 5 CHANNELS"]])
    boq(OUT / "以往项目" / "114 Showroom" / "114_BOQ.xlsx", "Showroom projection wall · PJ-1", [
        ["Panasonic PT-BHZ611C laser projector", 5, "set"],
        ["Fixed lens 0.5", 5, "pcs"],
        ["Signal and control cabling", 1, "lot"], "Video 5 + 1 spare (HDBaseT)", "Control CAT6 5 + 1 spare"])
    (OUT / "以往项目" / "标准答案.txt").write_text("# 做完、可当标准答案的项目\n143-Royal Plaza\n", encoding="utf-8")
    # 图纸、模板与条款：只进全文索引，供搜索
    (OUT / "图纸").mkdir(parents=True)
    shutil.copy(SAMPLES / "Lobby_Elevation_RevB.pdf", OUT / "图纸" / "Lobby_Elevation_RevB.pdf")
    docx(OUT / "模板与条款" / "Terms_and_Conditions.docx",
         ["Warranty: 2 years on LED modules and power supplies", "Payment terms: 50% deposit, 40% on delivery, "
          "10% on handover", "所有设备保修两年"])


if __name__ == "__main__":
    main()
