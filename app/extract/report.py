"""逐个记录样本文件的识别结果（第 4 步验收）。

用法：python -m app.extract.report <样本文件夹> > docs/step4-识别记录.md
真实样本（清单 G1、G2）到了以后，用同一个命令再跑一次，记录追加到文档里。
"""
import sys
import tempfile
from datetime import date
from pathlib import Path

from .run import extract, method_label

GRADE = {"A": "A 数值直接读取", "B": "B 文字识别，须逐项确认", "C": "C 仅作参考，不用于计算"}
CONF = {"high": "High 高", "medium": "Medium 中（须确认）", "low": "Low 低（须确认）"}


def main(folder: str) -> None:
    files = sorted(p for p in Path(folder).iterdir() if p.is_file() and not p.name.startswith(("_", ".")) and p.suffix != ".py")
    print(f"# 第 4 步识别记录 · {folder} · {date.today().isoformat()}\n")
    print("| 文件 | 等级 | 读取方式 | 认出的字段（值 · 置信度 · 位置） |\n| --- | --- | --- | --- |")
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(files):
            r = extract(path, path.suffix[1:].lower(), Path(tmp), f"derived/{i}", None)
            found = "<br>".join(f"{f['field']} = {f['value']} · {CONF[f['confidence']]} · {f['location']}"
                                for f in r["fields"]) or r["note"]
            print(f"| {path.name} | {GRADE[r['grade']]} | {method_label(r["method"])} | {found} |")


if __name__ == "__main__":
    main(sys.argv[1])
