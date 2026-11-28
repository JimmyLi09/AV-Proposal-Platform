"""2026-11-28: projection rule set gets a default surface gain (to be confirmed)

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-28 00:00:00
"""
import json
import re
from pathlib import Path

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None

SEED = Path(__file__).resolve().parents[2] / "rules" / "seed" / "pj.json"
REASON = "资料没写幕面增益时先按缺省值算（待确定）（升级时自动生成，算式和其它参数不变）"


def upgrade() -> None:
    # 只有图片的投影项目常常没写幕面增益：先按缺省值算，待确定。旧版本不改，在最新的投影版本上另存一个新版本
    params = [p for p in json.loads(SEED.read_text(encoding="utf-8"))["params"] if p["name"] == "default_surface_gain"]
    sets = sa.table('rule_set_versions', sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                    sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                    sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))
    conn = op.get_bind()
    last = conn.execute(sa.select(sets).where(sets.c.business_line == "PJ").order_by(sets.c.id.desc())).first()
    if last is None or any(p["name"] == "default_surface_gain" for p in last.content["params"]):
        return
    content = dict(last.content, params=[*params, *last.content["params"]])
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", last.version).groups())
    conn.execute(sets.insert().values(business_line="PJ", version=f"v{major}.{minor + 1}", content=content, reason=REASON,
                                      created_by=None, created_at=utcnow()))


def downgrade() -> None:
    pass
