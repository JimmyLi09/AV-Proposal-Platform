"""CR-13: client BOQ "Power distribution and cabling" spec lines from W1 and F6 / F7 / F9

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-08 16:00:00
"""
import re

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

OLD = ["DB box with MCB × {circuits} circuits",
       "Power cables {circuits} + {power_spares} spare, data cables CAT6 {data_runs} + {data_spares} spare"]
NEW = ["DB box with {mcb_a} A single-phase MCB × {circuits} circuits",
       "3-core {power_cable_mm2} mm² power cable × {power_cables} ({circuits} + {power_spares} spare)",
       "Power jumper cables between cabinets × {power_jumpers} (≈ {power_jumper_m} m)",
       "CAT6 data cable × {data_cables} ({data_runs} + {data_spares} spare)",
       "Data jumper cables between cabinets × {data_jumpers} (≈ {data_jumper_m} m)"]


def upgrade() -> None:
    # 最新的 LED 模板里「Power distribution and cabling」这一行还是原来的写法时，另存一个新版本换成接线规格行；
    # 用户自己改过写法的不动
    t = sa.table('template_versions', sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                 sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                 sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))
    conn = op.get_bind()
    last = conn.execute(sa.select(t).where(t.c.business_line == "LED").order_by(t.c.id.desc())).first()
    if last is None:
        return
    rows = [dict(r, specs=NEW, source="F6 / F7 / F9 / F12 / W1") if r.get("key") == "power_cabling" and r.get("specs") == OLD
            else r for r in last.content["boq"]["rows"]]
    if rows == last.content["boq"]["rows"]:
        return
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", last.version).groups())
    conn.execute(t.insert().values(business_line="LED", version=f"v{major}.{minor + 1}",
                                   content=dict(last.content, boq=dict(last.content["boq"], rows=rows)),
                                   reason="CR-13：配电和线缆一行的规格改成接线结果（空开、线径、跳线根数和长度；升级时自动生成）",
                                   created_by=None, created_at=utcnow()))


def downgrade() -> None:
    pass
