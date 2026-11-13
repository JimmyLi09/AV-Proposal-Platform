"""从文字里认出 LED 和投影的输入字段。模型（OCR）只负责认文字，这里只做格式匹配，不计算任何数量。

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


def to_m(value: str, unit: str | None) -> float | None:
    """2.8 / 2.8 m / 2800 mm → 米；没写单位又很大的按毫米算。"""
    v = _num(value)
    if unit == "mm" or (unit is None and v >= 100):
        v = v / 1000
    v = round(v, 3)
    return (int(v) if float(v).is_integer() else v) if 0.1 <= v <= 200 else None


CHOICES = {
    "environment": [("outdoor", r"outdoor|户外|室外"), ("rental", r"rental|租赁"), ("indoor", r"indoor|室内")],
    "installation": [("wall", r"wall[\s-]*mount|wall|壁挂|墙面"), ("floor", r"floor[\s-]*stand|落地"),
                     ("hanging", r"hanging|suspend|吊装"), ("embedded", r"embedded|recessed|嵌入")],
    "maintenance": [("front", r"front|前维护"), ("rear", r"rear|back|后维护")],
    # 投影安装方式（2026-11-13）
    "mounting": [("ceiling", r"ceiling[\s-]*mount|吊顶|吊装|吸顶"), ("floor", r"floor|table|落地|桌面|地台"),
                 ("wall", r"wall[\s-]*mount|壁挂|墙装")],
}

# 图纸里的自由文字更容易误判，只认明确的写法（Excel 有栏名时用上面宽松的 CHOICES）
TEXT_CHOICES = {
    "environment": CHOICES["environment"],
    "installation": [("wall", r"wall[\s-]*mount(?:ed)?|壁挂"), ("floor", r"floor[\s-]*stand(?:ing)?|落地"),
                     ("hanging", r"hanging|吊装"), ("embedded", r"recessed|embedded|嵌入")],
    "maintenance": CHOICES["maintenance"],
    "mounting": [("ceiling", r"ceiling[\s-]*mount(?:ed)?|吊顶安装|吊装|吸顶"), ("floor", r"floor[\s-]*stand(?:ing)?|落地|地台"),
                 ("wall", r"wall[\s-]*mount(?:ed)?|壁挂")],
}

# 投影输入（2026-11-13 试用反馈 4）：只认带标注的写法，没标注的数字不猜
PJ_MM = {  # 毫米
    "available_depth_mm": r"available\s*depth|room\s*depth|throw\s*depth|可用进深|房间进深|进深",
    "ceiling_height_mm": r"ceiling\s*height|clear\s*height|C\.\s?H\.?|(?<![A-Za-z])CH(?![A-Za-z])|天花高度|天花板高度|吊顶高度|天花净高|净高|层高",
}
PJ_M = {  # 米
    "mount_height_m": r"lens\s*height|mount(?:ing)?\s*height|projector\s*height|镜头高度|安装高度|投影机高度",
    "nearest_viewing_m": r"nearest\s*viewing|min(?:imum)?\.?\s*viewing\s*distance|最近观看距离|最近视距",
    "signal_run_m": r"signal\s*(?:run|distance)|cable\s*run|信号距离|走线距离|信号线长度",
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
    "mounting": r"mounting|projector\s*mount|投影安装方式",
    "ambient_lux": r"ambient\s*light|环境光|照度",
    "surface_gain": r"screen\s*gain|surface\s*gain|幕面增益|增益",
}
LABELS = PJ_MM | PJ_M | LABELS  # Excel 栏名先认投影的（「天花高度」「镜头高度」不能当成「高度」）
# 墙宽 / 墙高 也读成屏宽 / 屏高，投影方案里对应墙宽 / 墙高（见 workspace.FIELD_ALIAS）
LABELS["width_mm"] += r"|wall\s*width|墙宽|墙面宽度|幕宽|投影宽度"
LABELS["height_mm"] += r"|wall\s*height|墙高|墙面高度|幕高|投影高度"


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
    if field in ("width_mm", "height_mm") or field in PJ_MM:
        m = re.search(NUM + UNIT, text)
        return to_mm(m[1], m[2]) if m else None
    if field in PJ_M:
        m = re.search(NUM + r"\s*(mm|m)?", text)
        return to_m(m[1], m[2]) if m else None
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
    # 投影的标注先认（天花高度、镜头高度…），这些位置上的「高度」不再当成屏高
    taken: list[tuple[int, int]] = []
    for field, pattern in PJ_MM.items():
        m = re.search(rf"(?:{pattern})\s*[:：=]?\s*(?:约|approx\.?\s*)?{NUM}{UNIT}", text, re.I)
        if m:
            taken.append(m.span())
            add(field, to_mm(m[1], m[2] and m[2].lower()), strong, m)
    for field, pattern in PJ_M.items():
        m = re.search(rf"(?:{pattern})\s*[:：=]?\s*(?:约|approx\.?\s*)?{NUM}\s*(mm|m)?", text, re.I)
        if m:
            taken.append(m.span())
            add(field, to_m(m[1], m[2] and m[2].lower()), strong, m)
    for field in ("width_mm", "height_mm"):
        m = re.search(rf"(?:{LABELS[field]})\s*[:：=]?\s*{NUM}{UNIT}", text, re.I)
        if m and any(a <= m.start(1) < b for a, b in taken):
            m = None
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
    m = re.search(r"(\d{1,3}(?:,\d{3})*|\d+)\s*(?:lux|lx)(?![A-Za-z])", text, re.I)
    if m:
        add("ambient_lux", _num(m[1]), strong, m)
    m = re.search(rf"(?:{LABELS['surface_gain']})\s*[:：=]?\s*(\d(?:\.\d+)?)", text, re.I)
    if m:
        add("surface_gain", _num(m[1]), strong, m)
    for field, options in TEXT_CHOICES.items():
        for value, pattern in options:
            m = re.search(rf"(?<![A-Za-z])(?:{pattern})(?![A-Za-z])", text, re.I)
            if m and (field != "maintenance" or re.search(r"mainten|维护", text, re.I)) and (
                    field != "mounting" or value == "ceiling" or re.search(r"projector|投影", text, re.I)):
                add(field, value, "medium", m)
                break
    return found
