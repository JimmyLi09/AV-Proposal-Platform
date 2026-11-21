"""2026-11-21: LED rule set gets default inputs (to be confirmed) for image-only projects

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-21 00:00:00
"""
import json
import re
from pathlib import Path

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None

SEED = Path(__file__).resolve().parents[2] / "rules" / "seed" / "led.json"


def upgrade() -> None:
    # 只有图片的项目：使用环境、安装、维护、亮度、观看距离、信号源没写时先按缺省值算（待确定）。
    # 旧版本不改，在最新的 LED 版本上另存一个新版本
    params = [p for p in json.loads(SEED.read_text(encoding="utf-8"))["params"] if p["name"].startswith("default_")]
    sets = sa.table('rule_set_versions', sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                    sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                    sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))
    conn = op.get_bind()
    last = conn.execute(sa.select(sets).where(sets.c.business_line == "LED").order_by(sets.c.id.desc())).first()
    if last is None or any(p["name"].startswith("default_") for p in last.content["params"]):
        return
    content = dict(last.content, params=[*last.content["params"], *params])
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", last.version).groups())
    conn.execute(sets.insert().values(business_line="LED", version=f"v{major}.{minor + 1}", content=content,
                                      reason="资料没写的输入先按缺省值算（待确定）：使用环境、安装、维护、亮度、观看距离、信号源"
                                             "（升级时自动生成，算式和其它参数不变）",
                                      created_by=None, created_at=utcnow()))


def downgrade() -> None:
    pass
