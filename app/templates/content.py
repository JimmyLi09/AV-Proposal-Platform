"""模板：客户版 BOQ 的默认行（第 6 步再加章节、信头、条款）。每次保存整份另存新版本。

行里的 {名字} 换成规则结果或输入；数量要么是固定数（例如 1 lot），要么直接取某个规则结果，模板不自己算数量。
when（可选）：写一个规则结果的名字，它为 0 时这一行不出现（例如用了处理器含发送，就没有单独的控制器行）。
"""
import json
import re
from pathlib import Path

UNITS = ["sqm", "set", "lot", "pcs"]
NAME = re.compile(r"\{(\w+)\}")
LINE_NAMES = ["LED"]
CONTEXT = {"proposal_name", "project_name"}  # 除了规则里的名字，模板还能用方案名、项目名


class TemplateError(ValueError):
    pass


def load_seed(line: str) -> dict:
    return json.loads((Path(__file__).parent / f"seed_{line.lower()}.json").read_text(encoding="utf-8"))


def _text(where: str, value, known: set[str], required=False) -> None:
    if not isinstance(value, str) or len(value) > 300 or (required and not value.strip()):
        raise TemplateError(f"{where}：要填文字（最多 300 字）")
    if "{" in NAME.sub("", value) or "}" in NAME.sub("", value):
        raise TemplateError(f"{where}：花括号只能用来写 {{名字}}")
    if unknown := sorted(set(NAME.findall(value)) - known):
        raise TemplateError(f"{where}：不认识 {', '.join('{' + u + '}' for u in unknown)}")


def validate(content: dict, line: str, known: set[str]) -> None:
    """known：规则集里的输入和结果名字。"""
    if content.get("business_line") != line:
        raise TemplateError("业务线不对")
    known = known | CONTEXT
    boq = content["boq"]
    _text("组标题", boq["group"], known, required=True)
    rows, keys = boq["rows"], set()
    if not isinstance(rows, list) or not rows:
        raise TemplateError("至少要有一行")
    for i, r in enumerate(rows, 1):
        where = f"第 {i} 行"
        if not isinstance(r.get("key"), str) or not re.fullmatch(r"[a-z0-9_]{1,40}", r["key"]) or r["key"] in keys:
            raise TemplateError(f"{where}：编号要用小写字母、数字、下划线，且不能重复")
        keys.add(r["key"])
        _text(f"{where} 描述", r["title"], known, required=True)
        if not isinstance(r["specs"], list) or len(r["specs"]) > 12:
            raise TemplateError(f"{where}：规格最多 12 行")
        for j, spec in enumerate(r["specs"], 1):
            _text(f"{where} 规格 {j}", spec, known, required=True)
        for k in ("note", "source"):
            if k in r:
                _text(f"{where} {'备注' if k == 'note' else '来源'}", r[k], known)
        if "when" in r and r["when"] not in known:
            raise TemplateError(f"{where}：「出现条件」要填某个规则结果的名字")
        if r["unit"] not in UNITS:
            raise TemplateError(f"{where}：单位只能是 {' / '.join(UNITS)}")
        qty = r["qty"]
        if isinstance(qty, bool) or not (isinstance(qty, str) and qty in known
                                          or isinstance(qty, (int, float)) and qty >= 0):
            raise TemplateError(f"{where}：数量要填一个不小于 0 的数，或某个规则结果的名字")
