"""产品库：推荐只从这里选。每次保存整库另存新版本，已发出的 Rev 保留当时的版本。"""
import json
from pathlib import Path

from ..i18n import text, tr

STATUSES = ["preferred", "approved", "retired"]  # 首选排在已批准前面；已停用不参与推荐
SCENES = ["indoor", "outdoor", "rental"]

# 每类产品的字段（界面按这个出表单）：name, label, type
COMMON = [
    ("brand", "Brand 品牌", "text"),
    ("model", "Model 型号", "text"),
    ("status", "Status 状态", "status"),
    ("scenes", "Use 适用场景", "scenes"),
    ("datasheet", "Datasheet 规格书文件名", "text"),
    ("sample", "Sample data 示例数据", "bool"),
]
PJ_COMMON = [f for f in COMMON if f[0] != "scenes"]  # 投影不按室内外选型
FIELDS = {
    "LED": {
        "cabinet": COMMON + [
            ("pixel_pitch_mm", "Pixel pitch 点间距 mm", "number"),
            ("module_w_mm", "Module width 模组宽 mm", "number"),
            ("module_h_mm", "Module height 模组高 mm", "number"),
            ("cabinet_sizes_mm", "Cabinet sizes 箱体尺寸 mm（第一个为主尺寸）", "sizes"),
            ("brightness_nits", "Brightness 亮度 nits", "number"),
            ("max_power_w_m2", "Max power 最大功耗 W/㎡", "number"),
            ("ip", "IP rating 防护等级", "text"),
            ("weight_kg", "Weight 重量 kg / cabinet 箱体", "number"),
            ("maintenance", "Maintenance 维护方式", "maintenance"),
            ("psu_per_cabinet", "PSU per cabinet 每箱电源数", "number"),
            ("rx_per_cabinet", "Receiving cards per cabinet 每箱接收卡数", "number"),
        ],
        "controller": COMMON + [
            ("capacity_px", "Load 带载像素 px", "number"),
            ("ports", "Ports 网口数", "number"),
        ],
        "processor": COMMON + [
            ("inputs", "Inputs 输入数", "number"),
            ("max_px", "Max resolution 最大分辨率 px", "number"),
            # CR-2：处理器（含发送）——一台同时做视频处理和发送，不用另配控制器
            ("sending", "With sending 含发送", "flag"),
            ("capacity_px", "Load 带载像素 px（含发送时）", "number"),
            ("ports", "Ports 网口数（含发送时）", "number"),
            ("max_input_px", "Max input 最大输入分辨率 px", "number"),
        ],
    },
    # 投影（第 7 步 / CR-7）：镜头单独成为一类产品，写明适配哪几款投影机
    "PJ": {
        "projector": PJ_COMMON + [
            ("lumens", "Brightness 流明 lm", "number"),
            ("native_px_w", "Native width 横向像素 px", "number"),
            ("native_px_h", "Native height 纵向像素 px", "number"),
            ("power_w", "Power 功率 W", "number"),
            ("weight_kg", "Weight 重量 kg", "number"),
            ("noise_db", "Noise 噪音 dB", "number"),
        ],
        "lens": PJ_COMMON + [
            ("throw_ratio", "Throw ratio 投射比（变焦填最小）", "number"),
            ("throw_max", "Throw ratio max 最大投射比（定焦不填）", "number"),
            ("shift", "Lens shift 镜头位移", "text"),
            ("fits", "Fits 适配投影机型号", "ids"),
        ],
        "blender": PJ_COMMON + [
            ("outputs", "Outputs 输出路数", "number"),
            ("curved", "Curved correction 曲面几何校正", "flag"),
        ],
    },
}
CATEGORY_LABEL = {"cabinet": "Cabinet 箱体", "controller": "Controller 控制器", "processor": "Processor 视频处理器",
                  "projector": "Projector 投影机", "lens": "Lens 镜头", "blender": "Blender 融合器"}


def _number(v):
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0)


CHECKS = {
    "text": lambda v: v is None or isinstance(v, str),
    "status": lambda v: v in STATUSES,
    "scenes": lambda v: isinstance(v, list) and all(s in SCENES for s in v),
    "bool": lambda v: isinstance(v, bool),
    "flag": lambda v: v is None or isinstance(v, bool),
    "number": _number,
    "sizes": lambda v: v is None or (isinstance(v, list) and all(
        isinstance(s, list) and len(s) == 2 and all(_number(x) and x is not None for x in s) for s in v)),
    "maintenance": lambda v: v in ("front", "rear", "both"),
    "ids": lambda v: v is None or (isinstance(v, list) and all(isinstance(x, str) for x in v)),
}


class LibraryError(ValueError):
    pass


def load_seed(line: str) -> dict:
    return json.loads((Path(__file__).parent / f"seed_{line.lower()}.json").read_text(encoding="utf-8"))


def load_reference(line: str) -> list[dict]:
    """参考型号表：不在产品库里，只用来给建议型号（数值待核对规格书）。"""
    path = Path(__file__).parent / f"reference_{line.lower()}.json"
    return json.loads(path.read_text(encoding="utf-8"))["products"] if path.exists() else []


def validate(content: dict, line: str) -> None:
    if content.get("business_line") != line:
        raise LibraryError(tr("业务线不对", "Wrong business line"))
    ids = [p.get("id") for p in content["products"]]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i.strip() for i in ids):
        raise LibraryError(tr("产品编号不能为空，也不能重复", "Product IDs must be filled in and unique"))
    for p in content["products"]:
        fields = FIELDS[line].get(p.get("category"))
        if fields is None:
            raise LibraryError(p["id"] + tr("：类别不对", ": wrong category"))
        for name, label, kind in fields:
            if not CHECKS[kind](p.get(name)):
                raise LibraryError(p["id"] + tr(f"：{text(label)} 填写不对", f": {text(label)} is not valid"))
        if not (p.get("model") or "").strip():
            raise LibraryError(p["id"] + tr("：型号不能为空", ": model is required"))
        if p.get("sending") and not (p.get("capacity_px") and p.get("ports")):
            raise LibraryError(p["id"] + tr("：含发送的处理器要填带载像素和网口数",
                                               ": a processor with sending needs load and ports"))


def active(content: dict, category: str) -> list[dict]:
    """可推荐的产品：未停用，首选在前，其余保持产品库顺序。"""
    items = [p for p in content["products"] if p["category"] == category and p["status"] != "retired"]
    return sorted(items, key=lambda p: STATUSES.index(p["status"]))


def name(p: dict) -> str:
    return f"{p.get('brand') or ''} {p['model']}".strip()
