"""测试共用的设置。"""
import copy

from sqlalchemy import select

from app.models import RuleSetVersion


def count_grouping(app) -> None:
    """测试库里把 LED 种子规则集的网线分组改成「按箱数」（不另存版本）。

    CR-10 的默认值是按行整行：143-Royal Plaza 要 5 个网口，示例控制器 SC-4 只有 4 口，F11 阻断并建议 VX600
    （regression_cases.json 两种结果都有，默认值待 Jimmy 定）。审核、导出、BOQ 这些流程的测试不依赖这个待定的默认值，
    用按箱数（3 个网口，SC-4 够用）。"""
    with app.state.Session() as db:
        v = db.scalars(select(RuleSetVersion).where(RuleSetVersion.business_line == "LED")
                       .order_by(RuleSetVersion.id.desc())).first()
        content = copy.deepcopy(v.content)
        next(p for p in content["params"] if p["name"] == "data_grouping")["value"] = "count"
        v.content = content
        db.commit()


def count_content(content: dict) -> dict:
    """直接调规则引擎的测试用：同 count_grouping，返回网线按箱数的规则集副本。"""
    content = copy.deepcopy(content)
    next(p for p in content["params"] if p["name"] == "data_grouping")["value"] = "count"
    return content


def official(client, base: str, step: str = "05") -> dict:
    """CR-9：在 05（或 06）点「下一步」，把草稿保存为正式版本（只有正式版本能提交审批）。"""
    r = client.post(f"{base}/next", json={"step": step, "save": True})
    assert r.status_code == 200, r.text
    return r.json()
