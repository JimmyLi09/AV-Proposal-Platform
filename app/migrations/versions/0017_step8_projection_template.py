"""Step 8: projection proposal template — data completeness inputs, template clauses and page size

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-09 10:00:00
"""
import json
import re
from pathlib import Path

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None

SEEDS = Path(__file__).resolve().parents[2]
DOC_INPUTS = ["doc_plan", "doc_elevation", "doc_section", "doc_rcp"]


def _table(name):
    return sa.table(name, sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                    sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                    sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))


def _next(version: str) -> str:
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", version).groups())
    return f"v{major}.{minor + 1}"


def _seed(path: str) -> dict:
    return json.loads((SEEDS / path).read_text(encoding="utf-8"))


def _content(row) -> dict:
    return json.loads(row.content) if isinstance(row.content, str) else row.content


def upgrade() -> None:
    conn = op.get_bind()
    # 投影规则集：确认输入里加资料齐全度（平面图、立面图、剖面图、天花图）；不影响任何算式，另存一个新版本
    sets = _table('rule_set_versions')
    last = conn.execute(sa.select(sets).where(sets.c.business_line == "PJ").order_by(sets.c.id.desc())).first()
    if last is not None:
        content = _content(last)
        if not any(i["name"] == "doc_plan" for i in content["inputs"]):
            seed = {i["name"]: i for i in _seed("rules/seed/pj.json")["inputs"]}
            inputs = list(content["inputs"])
            at = next((k + 1 for k, i in enumerate(inputs) if i["name"] == "existing_control_total"),
                      next((k for k, i in enumerate(inputs) if i["name"] == "native_px_w"), len(inputs)))
            content = dict(content, inputs=inputs[:at] + [seed[n] for n in DOC_INPUTS] + inputs[at:])
            conn.execute(sets.insert().values(business_line="PJ", version=_next(last.version), content=content,
                                              reason="第 8 步：确认输入加资料齐全度（平面图、立面图、剖面图、天花图；升级时自动生成，算式不变）",
                                              created_by=None, created_at=utcnow()))
    # 模板：加固定条款（原来写在代码里的风险与假设，现在在模板页改、带版本）和纸张；已经有条款的不动
    templates = _table('template_versions')
    for line in ("LED", "PJ"):
        last = conn.execute(sa.select(templates).where(templates.c.business_line == line).order_by(templates.c.id.desc())).first()
        if last is None:
            continue
        content = _content(last)
        if "clauses" in content:
            continue
        seed = _seed(f"templates/seed_{line.lower()}.json")
        content = dict(content, page=seed["page"], clauses=seed["clauses"])
        conn.execute(templates.insert().values(business_line=line, version=_next(last.version), content=content,
                                               reason="第 8 步：风险与假设的固定条款和纸张放进模板（升级时自动生成）",
                                               created_by=None, created_at=utcnow()))


def downgrade() -> None:
    pass
