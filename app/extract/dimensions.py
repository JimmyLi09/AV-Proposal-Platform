"""尺寸线配对（CR-1）：图纸上最常见的写法是尺寸线旁边单独一个数字（框体上方「6400mm」、右侧「3520mm」），
没有栏名也没有 ×，逐行认不出来。这里按文字的位置判断：

- 横排、在框体上方或下方 → 屏宽候选；
- 在框体左侧或右侧，或者竖排（外框高大于宽）→ 屏高候选；
- 框体取同一页上包住「P2.5 LED SCREEN」这类标题的最小矩形；找不到框体，就用其它文字（标题、说明，不含这些数字）
  包围盒的中心来判断上下和左右。

每个方向只取最大的那个数（总尺寸），同一个数已经当作屏宽，就不再当屏高。只认数字，不计算任何数量。
"""
import re

from .fields import to_mm

Box = tuple[float, float, float, float]  # x0, y0, x1, y1（y 向下）
LONE = re.compile(r"^[\s←→↔<>|\-–—]*(\d{1,3}(?:,\d{3})+|\d{3,6})\s*(mm|m)?[\s←→↔<>|\-–—]*$", re.I)
TITLE = re.compile(r"\bP\s?\d{1,2}(?:\.\d{1,3})?\b.*(?:LED|SCREEN|屏)|LED\s*(?:SCREEN|WALL|DISPLAY|屏)", re.I)
NEAR = 0.5  # 离框体多远还算这块屏的尺寸：框体宽 / 高的一半


def lone_value(text: str) -> int | None:
    m = LONE.match(text)
    return to_mm(m[1], m[2] and m[2].lower()) if m else None


def _center(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _area(b: Box) -> float:
    return (b[2] - b[0]) * (b[3] - b[1])


def _contains(outer: Box, inner: Box) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def frame_for(lines: list[tuple[str, Box]], rects: list[Box]) -> Box | None:
    titles = [b for t, b in lines if TITLE.search(t)]
    around = [r for r in rects for t in titles if _contains(r, t)]
    return min(around, key=_area, default=None)


def _side(b: Box, frame: Box | None, extent: Box) -> str | None:
    """这个数字是屏宽（width）还是屏高（height）的候选；离框体太远或在框体里面的不算。"""
    cx, cy = _center(b)
    vertical = (b[3] - b[1]) > 1.5 * (b[2] - b[0])
    if frame is None:  # 退回：和其它文字的中心比，偏上下的是宽，偏左右的是高
        ex, ey = _center(extent)
        return "height_mm" if vertical or abs(cx - ex) > abs(cy - ey) else "width_mm"
    x0, y0, x1, y1 = frame
    dx, dy = (x1 - x0) * NEAR, (y1 - y0) * NEAR
    if not (x0 - dx <= cx <= x1 + dx and y0 - dy <= cy <= y1 + dy):
        return None
    above_below = x0 <= cx <= x1 and not y0 <= cy <= y1
    beside = y0 <= cy <= y1 and not x0 <= cx <= x1
    if vertical and (above_below or beside):
        return "height_mm"
    return "width_mm" if above_below else "height_mm" if beside else None


def pair(lines: list[tuple[str, Box]], rects: list[Box]) -> list[tuple[str, int, str, Box]]:
    """lines：一页上的文字行和外框；rects：这一页上画出来的矩形。返回 (字段, 值 mm, 原文, 外框)。"""
    nums = [(v, t, b) for t, b in lines if (v := lone_value(t)) is not None]
    if not nums:
        return []
    frame = frame_for(lines, rects)
    boxes = [b for t, b in lines if lone_value(t) is None] or [b for _, b in lines]
    extent = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    sides = {"width_mm": [], "height_mm": []}
    for v, t, b in nums:
        if side := _side(b, frame, extent):
            sides[side].append((v, t, b))
    out = []
    width = max(sides["width_mm"], default=None)
    if width:
        out.append(("width_mm", *width))
    height = max((x for x in sides["height_mm"] if not width or x[0] != width[0]), default=None)
    if height:
        out.append(("height_mm", *height))
    return out


def image_rects(img) -> list[Box]:
    """图片上画出来的矩形（框线或色块），面积太小的不要。"""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    rects, min_area = [], img.width * img.height * 0.01
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h >= min_area and len(cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)) == 4:
            rects.append((x, y, x + w, y + h))
    return rects
