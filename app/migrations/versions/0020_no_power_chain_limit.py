"""2026-11-21: remove the cabinets-per-power-chain limit (circuits by current only)

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-21 00:00:00
"""
import json
import re
from pathlib import Path

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None

SEED = Path(__file__).resolve().parents[2] / "rules" / "seed" / "led.json"
NOTE = ("每回路额定电流取空开和线径载流的小者，乘持续负载系数得可用电流；按最大单箱电流算每回路能带几箱，得回路数。"
        "每条电源线最多串接几箱默认不限（0）；填了箱数时再按串接算，两者取大。")
DISPLAY = "{circuits}（每回路最多 {cab_per_circuit} 箱，按电流）"
LABEL = "Max cabinets per power chain 每条电源线最多串接箱体（0 = 不限）"
SOURCE = "2026-11-21 Jimmy：去掉串接上限，回路只按电流算（以前取 10）；要限制时填箱数"
REASON = "去掉每条电源线的串接上限，回路只按电流算（2026-11-21 Jimmy；升级时自动生成，其它算式和参数不变）"


def upgrade() -> None:
    # Jimmy：回路按电流算就够，串接 10 箱的上限去掉（接线图一直报「串接 11 箱，超过上限 10」）。
    # F6 换成新算式（串接上限 0 = 不算），chain_max 改 0；旧版本不改，在最新的 LED 版本上另存一个新版本
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    f6 = dict(next(r for r in seed["rules"] if r["id"] == "F6"), note=NOTE, display=DISPLAY)  # 种子里的 F6 已支持 0 = 不限
    chain = dict(next(p for p in seed["params"] if p["name"] == "chain_max"), value=0, label=LABEL, source=SOURCE)
    sets = sa.table('rule_set_versions', sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                    sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                    sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))
    conn = op.get_bind()
    last = conn.execute(sa.select(sets).where(sets.c.business_line == "LED").order_by(sets.c.id.desc())).first()
    if last is None:
        return
    content = json.loads(last.content) if isinstance(last.content, str) else last.content
    if not any(p["name"] == "chain_max" for p in content["params"]):
        return
    content = dict(content, rules=[f6 if r["id"] == "F6" else r for r in content["rules"]],
                   params=[chain if p["name"] == "chain_max" else p for p in content["params"]])
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", last.version).groups())
    conn.execute(sets.insert().values(business_line="LED", version=f"v{major}.{minor + 1}", content=content,
                                      reason=REASON, created_by=None, created_at=utcnow()))


def downgrade() -> None:
    pass
