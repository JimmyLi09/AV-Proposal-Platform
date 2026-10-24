"""CR-7: LED rule set gets the S5 per-output width limit (multi-face screens)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24 00:00:00
"""
import re

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

PARAM = {"name": "output_max_px_w", "group": "Checks 校核", "label": "Output width limit 每路输出宽度上限（多面屏 S5）",
         "unit": "px", "value": 3840, "status": "sample"}


def upgrade() -> None:
    # 多面屏 S5：每面接处理器的一路输出，单路宽度不超过上限。旧版本不改，在最新的 LED 版本上另存一个新版本
    sets = sa.table('rule_set_versions', sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                    sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                    sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))
    conn = op.get_bind()
    last = conn.execute(sa.select(sets).where(sets.c.business_line == "LED").order_by(sets.c.id.desc())).first()
    if last is None or any(p["name"] == PARAM["name"] for p in last.content["params"]):
        return
    content = dict(last.content, params=[*last.content["params"], PARAM])
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", last.version).groups())
    conn.execute(sets.insert().values(business_line="LED", version=f"v{major}.{minor + 1}", content=content,
                                      reason="CR-7：多面屏 S5 每路输出宽度上限（升级时自动生成，算式和其它参数不变）",
                                      created_by=None, created_at=utcnow()))


def downgrade() -> None:
    pass
