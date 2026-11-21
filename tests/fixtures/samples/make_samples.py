"""生成第 4 步的测试样本（自制，非客户资料）。真实样本（清单 G1、G2）到了以后放到同一个目录旁边对比。

用法：python tests/fixtures/samples/make_samples.py   （需要 requirements-dev.txt 里的 reportlab）
内容仿照原型里的 143-Royal Plaza LED-1。
"""
import random
from pathlib import Path

import ezdxf
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def text_pdf():
    """带文字层的立面图 PDF：第 2 页标了屏幕尺寸和点间距。"""
    c = canvas.Canvas(str(OUT / "Lobby_Elevation_RevB.pdf"), pagesize=landscape(A3))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(60, 760, "LOBBY ELEVATION A")
    c.setFont("Helvetica", 12)
    c.drawString(60, 730, "FFL +0.000   CL +3.600")
    c.rect(300, 300, 500, 280)
    c.showPage()
    c.setFont("Helvetica", 14)
    c.drawString(60, 760, "LED SCREEN 4500 (W) x 2560 (H)")
    c.drawString(60, 735, "BOTTOM OF SCREEN +0.900")
    c.drawString(60, 710, "INDOOR LED WALL, PIXEL PITCH P2.5")
    c.rect(300, 300, 450, 256)
    c.save()


def excel():
    """需求表：栏名在左、值在右。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "LED"
    ws["A1"] = "LED Requirement"
    for row, (label, value) in {4: ("Indoor / Outdoor", "Indoor"), 6: ("Pixel pitch", "P2.5"),
                                9: ("Installation", "Wall mount"), 10: ("Maintenance", "Front"),
                                11: ("Brightness (nits)", 600)}.items():
        ws.cell(row, 1, label)
        ws.cell(row, 2, value)
    wb.save(OUT / "LED_Requirement.xlsx")


def _image(lines, size=(1400, 700), bg="white", angle=0.0, noise=False):
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    for y, (text, px) in enumerate(lines):
        d.text((60, 80 + y * 120), text, fill=(30, 30, 30), font=ImageFont.truetype(FONT, px))
    if angle:
        img = img.rotate(angle, expand=True, fillcolor=bg)
    if noise:
        rnd = random.Random(1)
        px = img.load()
        for _ in range(img.width * img.height // 40):
            x, y = rnd.randrange(img.width), rnd.randrange(img.height)
            px[x, y] = (rnd.randrange(150, 230),) * 3
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img


def photo():
    """手机拍的现场照片：有点歪、有噪点。"""
    _image([("SCREEN W4480 X H2560", 44), ("VIEWING DISTANCE 4-6M", 44)], bg=(225, 222, 214), angle=2.0,
           noise=True).save(OUT / "Lobby_site_photo.jpg", quality=85)


def scanned_pdf():
    """扫描版平面图：PDF 里只有图片，没有文字层。"""
    img = _image([("PLAN VIEW", 40), ("LED 4480 x 2560", 40)], size=(1600, 1100))
    png = OUT / "_scan.png"
    img.save(png)
    c = canvas.Canvas(str(OUT / "Scanned_Plan.pdf"), pagesize=landscape(A3))
    c.drawImage(str(png), 0, 0, width=landscape(A3)[0], height=landscape(A3)[1])
    c.save()
    png.unlink()


def render():
    """概念效果图：没有尺寸。"""
    img = Image.new("RGB", (1200, 700), (40, 50, 70))
    d = ImageDraw.Draw(img)
    d.rectangle((300, 200, 900, 500), fill=(90, 140, 200))
    d.text((60, 60), "CONCEPT", fill="white", font=ImageFont.truetype(FONT, 40))
    img.save(OUT / "Concept_render.png")


def dimension_image():
    """CR-1：图纸常见写法，尺寸线旁边单独一个数字。框上方「4480mm」，右侧「2560mm」，框里是标题。"""
    img = Image.new("RGB", (1400, 900), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 40)
    d.rectangle((250, 220, 1050, 660), outline="black", width=4)
    d.text((650, 440), "P2.5 LED SCREEN", fill="black", font=font, anchor="mm")
    d.line((250, 160, 1050, 160), fill="black", width=2)  # 上方尺寸线
    for x in (250, 1050):
        d.line((x, 140, x, 180), fill="black", width=2)
    d.text((650, 110), "4480mm", fill="black", font=font, anchor="mm")
    d.line((1110, 220, 1110, 660), fill="black", width=2)  # 右侧尺寸线
    for y in (220, 660):
        d.line((1090, y, 1130, y), fill="black", width=2)
    d.text((1250, 440), "2560mm", fill="black", font=font, anchor="mm")
    img.save(OUT / "Dimension_lines.png")


def layout_drawing():
    """2026-11-21 仿模组 / 箱体排布图截图：黑底细线，尺寸后面括号写像素数「3200 [1280]」，高度竖排写在左边，截图只有 ~1100 px 宽。"""
    img = Image.new("RGB", (1100, 520), "black")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 15)
    x0, y0, x1, y1 = 90, 100, 560, 390
    for i in range(11):
        d.line([(x0 + i * (x1 - x0) / 10, y0), (x0 + i * (x1 - x0) / 10, y1)], fill=(0, 170, 170))
    for j in range(13):
        d.line([(x0, y0 + j * (y1 - y0) / 12), (x1, y0 + j * (y1 - y0) / 12)], fill=(200, 200, 200))
    d.line([(x0, 62), (x1, 62)], fill=(0, 200, 0))
    d.text(((x0 + x1) / 2 - 40, 40), "3200 [1280]", fill=(0, 220, 0), font=font)
    d.line([(40, y0), (40, y1)], fill=(0, 200, 0))
    label = Image.new("RGB", (110, 24), "black")
    ImageDraw.Draw(label).text((4, 2), "1920 [768]", fill=(0, 220, 0), font=font)
    img.paste(label.rotate(90, expand=True), (12, (y0 + y1) // 2 - 55))
    d.text((260, 470), "MODULE LAYOUT", fill=(230, 220, 0), font=font)
    img.save(OUT / "Layout_drawing.png")


def dxf():
    """CAD 立面（DXF）：标注写在文字里。"""
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_text("LED SCREEN W4480 x H2560", dxfattribs={"layer": "A-ANNO", "height": 100}).set_placement((0, 3000))
    msp.add_mtext("PIXEL PITCH P2.5\\PINDOOR", dxfattribs={"layer": "A-ANNO", "char_height": 80, "insert": (0, 2700)})
    msp.add_lwpolyline([(0, 0), (4480, 0), (4480, 2560), (0, 2560)], close=True)
    doc.saveas(OUT / "Elevation.dxf")


if __name__ == "__main__":
    for make in (text_pdf, excel, photo, scanned_pdf, render, dxf, dimension_image, layout_drawing):
        make()
    print("samples written to", OUT)
