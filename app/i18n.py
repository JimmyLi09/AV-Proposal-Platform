"""界面语言（CR-4）：界面一次只显示一种语言，默认中文，按用户保存。

- 浏览器每个请求带 X-Lang（zh / en），服务器生成的提示句按它返回；两种语言各写一份：tr("中文", "English")。
- 导出文件按导出时选的语言，和界面语言分开（导出接口自己用 use(...) 切换）。
- 不翻译：数字、型号、规则编号、文件名、Rev 和版本号、单位，以及用户录入的内容（项目名、备注、原因）。
- 后台读文件时写进数据库的说明是中文；stored() 在显示时换成当前语言（旧数据也能换）。
"""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

LANGS = ("zh", "en")
_lang: ContextVar[str] = ContextVar("lang", default="zh")


def current() -> str:
    return _lang.get()


def tr(zh: str, en: str) -> str:
    return en if _lang.get() == "en" else zh


@contextmanager
def use(lang: str | None):
    token = _lang.set(lang if lang in LANGS else "zh")
    try:
        yield
    finally:
        _lang.reset(token)


# 系统写进数据库的固定说明（读文件结果、初始版本的原因）。整句先换，剩下的片段再换。
STORED = {
    "初始版本（平台方案 V1，2026-10-14）": "Initial version (platform plan V1, 2026-10-14)",
    "CR-6：V1 不含价格，去掉 GST 参数（升级时自动生成，算式和其它参数不变）":
        "CR-6: V1 has no prices; GST parameter removed (generated on upgrade; formulas and other parameters unchanged)",
    "初始模板：客户版 BOQ 默认行（CR-6）": "Initial template: default client BOQ rows (CR-6)",
    "示例产品，清单 D 组填好后替换": "Sample products; to be replaced once checklist group D is filled in",
    "DWG 要在服务器装免费的 ODA File Converter 才能读取，目前只随项目保存":
        "DWG needs the free ODA File Converter on the server; kept with the project for now",
    "这类文件不读取，只随项目保存": "This file type is not read; kept with the project only",
    "未找到尺寸，仅作参考": "No dimensions found; for reference only",
}
FRAGMENTS = {"读取失败：": "Read failed: ", "文字识别": "OCR", "尺寸线": "dimension line", "尺寸标注": "dimension",
             "加入建议型号 ": "Added suggested model ",
             "（参考型号表，数值待核对规格书）": " (reference model table; values to be checked against the datasheet)"}
_FRAGMENT_RE = re.compile("|".join(map(re.escape, sorted(FRAGMENTS, key=len, reverse=True))))


def stored(text: str | None) -> str:
    if not text or _lang.get() != "en":
        return text or ""
    if text in STORED:
        return STORED[text]
    return _FRAGMENT_RE.sub(lambda m: FRAGMENTS[m[0]], text)


# 种子内容（规则集的标签、标题、说明，参考型号的备注等）的两种语言；用户改过的文字不在表里，按原样显示
CONTENT = json.loads((Path(__file__).parent / "i18n_data" / "content.json").read_text(encoding="utf-8"))
# 中文量词在英文界面换成英文（「路」用在回路、信号源上，英文不写）；mm、kW、㎡、px 等单位不翻译
UNITS_EN = {"个": "pcs", "块": "pcs", "张": "pcs", "根": "pcs", "台": "units", "套": "set", "路": ""}


def text(s):
    if not isinstance(s, str):
        return s
    entry = CONTENT.get(s)
    return entry.get(_lang.get(), s) if entry else s


def unit(u: str | None) -> str:
    return UNITS_EN.get(u, u) if _lang.get() == "en" else (u or "")
