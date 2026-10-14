"""从文字里认出 LED 输入字段。模型（OCR）只负责认文字，这里只做格式匹配，不计算任何数量。

置信度：
- high：明确标注的写法（W4480 x H2560、Width: 4480、P2.5、600 nits、Excel 里对得上的栏名），且来自文字层 / Excel / DXF；
- medium：没有标注的尺寸对、关键词判断（室内、壁挂…），或 OCR 读到的明确写法；
- low：OCR 读到的没有标注的尺寸对。
medium / low 必须人工逐项确认后才能计算。
"""
import re

NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
UNIT = r"\s*(mm|m)?"
X = r"\s*[xX×*]\s*"


def _num(s: str) -> float | int:
    v = float(str(s).replace(",", ""))
    return int(v) if v.is_integer() else v


def to_mm(value: str, unit: str | None) -> float | None:
    """5000 / 5,000 / 5m / 4.48 m → 毫米；不合理的尺寸丢掉。"""
    v = _num(value)
    if unit == "m" or (unit is None and v < 30):  # 没写单位又很小，按米算
        v *= 1000
    v = round(v)
    return v if 100 <= v <= 100_000 else None


CHOICES = {
    "environment": [("outdoor", r"outdoor|户外|室外"), ("rental", r"rental|租赁"), ("indoor", r"indoor|室内")],
    "installation": [("wall", r"wall[\s-]*mount|wall|壁挂|墙面"), ("floor", r"floor[\s-]*stand|落地"),
                     ("hanging", r"hanging|suspend|吊装"), ("embedded", r"embedded|recessed|嵌入")],
    "maintenance": [("front", r"front|前维护"), ("rear", r"rear|back|后维护")],
}

# 图纸里的自由文字更容易误判，只认明确的写法（Excel 有栏名时用上面宽松的 CHOICES）
TEXT_CHOICES = {
    "environment": CHOICES["environment"],
    "installation": [("wall", r"wall[\s-]*mount(?:ed)?|壁挂"), ("floor", r"floor[\s-]*stand(?:ing)?|落地"),
                     ("hanging", r"hanging|吊装"), ("embedded", r"recessed|embedded|嵌入")],
    "maintenance": CHOICES["maintenance"],
}

# Excel 栏名 / 标注文字 → 字段
LABELS = {
    "width_mm": r"screen\s*width|width|屏宽|屏幕宽度|宽度",
    "height_mm": r"screen\s*height|height|屏高|屏幕高度|高度",
    "pixel_pitch_mm": r"pixel\s*pitch|pitch|点间距|像素间距",
    "environment": r"indoor\s*/\s*outdoor|environment|使用环境|室内\s*/\s*户外",
    "installation": r"installation|mounting|安装方式",
    "maintenance": r"maintenance|维护方式",
    "brightness_required_nits": r"brightness|亮度",
    "viewing_distance_m": r"viewing\s*distance|观看距离|视距",
    "signal_sources": r"signal\s*sources?|信号源",
}


def parse_value(field: str, raw) -> object | None:
    """把一个单元格 / 标注后面的值按字段类型读出来。"""
    text = str(raw).strip()
    if field in CHOICES:
        for value, pattern in CHOICES[field]:
            if re.search(pattern, text, re.I):
                return value
        return None
    if field == "viewing_distance_m":
        m = re.search(rf"{NUM}\s*(?:-|–|~|to|至)\s*{NUM}", text)
        if m:
            return [_num(m[1]), _num(m[2])]
        m = re.search(NUM, text)
        return [_num(m[1]), _num(m[1])] if m else None
    if field == "pixel_pitch_mm":
        m = re.search(r"(\d+(?:\.\d+)?)", text)
        return _num(m[1]) if m and 0.3 <= _num(m[1]) <= 40 else None
    if field in ("width_mm", "height_mm"):
        m = re.search(NUM + UNIT, text)
        return to_mm(m[1], m[2]) if m else None
    m = re.search(NUM, text)
    return _num(m[1]) if m else None


def find_in_text(text: str, ocr: bool) -> list[tuple[str, object, str, str]]:
    """一行文字里能认出的字段：(字段, 值, 置信度, 匹配到的原文)。"""
    found = []
    strong = "medium" if ocr else "high"

    def add(field, value, conf, match):
        if value is not None:
            found.append((field, value, conf, match.group(0).strip()))

    pair = None
    for pattern in (rf"W{NUM}{UNIT}{X}H{NUM}{UNIT}",  # W4480 x H2560
                    rf"{NUM}{UNIT}\s*\(W\){X}{NUM}{UNIT}\s*\(H\)"):  # 4500 (W) x 2560 (H)
        pair = re.search(pattern, text, re.I)
        if pair:
            add("width_mm", to_mm(pair[1], pair[2] and pair[2].lower()), strong, pair)
            add("height_mm", to_mm(pair[3], pair[4] and pair[4].lower()), strong, pair)
            break
    if not pair:
        m = re.search(rf"(?<![\d.]){NUM}{UNIT}{X}{NUM}{UNIT}", text)
        if m:
            conf = "low" if ocr else "medium"
            add("width_mm", to_mm(m[1], m[2] and m[2].lower()), conf, m)
            add("height_mm", to_mm(m[3], m[4] and m[4].lower()), conf, m)
    for field in ("width_mm", "height_mm"):
        m = re.search(rf"(?:{LABELS[field]})\s*[:：=]?\s*{NUM}{UNIT}", text, re.I)
        if m and not any(f == field for f, *_ in found):
            add(field, to_mm(m[1], m[2] and m[2].lower()), strong, m)

    m = re.search(r"\bP\s?(\d{1,2}\.\d{1,3})\b", text) or re.search(
        r"(?:pixel\s*pitch|pitch|点间距|像素间距)\s*[:：=]?\s*P?(\d{1,2}(?:\.\d{1,3})?)\s*(?:mm)?", text, re.I)
    if m:
        add("pixel_pitch_mm", parse_value("pixel_pitch_mm", m[1]), strong, m)
    m = re.search(r"(\d{1,3}(?:,\d{3})*|\d+)\s*(?:nits?|cd/m2|cd/m²)", text, re.I)
    if m:
        add("brightness_required_nits", _num(m[1]), strong, m)
    m = re.search(rf"(?:{LABELS['viewing_distance_m']})\D{{0,6}}{NUM}\s*(?:(?:-|–|~|to|至)\s*{NUM})?\s*m", text, re.I)
    if m:
        add("viewing_distance_m", [_num(m[1]), _num(m[2] or m[1])], strong, m)
    for field, options in TEXT_CHOICES.items():
        for value, pattern in options:
            m = re.search(rf"(?<![A-Za-z])(?:{pattern})(?![A-Za-z])", text, re.I)
            if m and (field != "maintenance" or re.search(r"mainten|维护", text, re.I)):
                add(field, value, "medium", m)
                break
    return found
