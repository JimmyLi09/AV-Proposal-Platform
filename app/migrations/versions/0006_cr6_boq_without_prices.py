"""CR-6: BOQ without prices, BOQ template versions

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23 00:00:00
"""
import re

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

PRICE_PARAMS = {"gst_rate"}


def upgrade() -> None:
    op.create_table('template_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_line', sa.String(length=10), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('content', sa.JSON(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_line', 'version')
    )
    with op.batch_alter_table('revisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('boq_edits', sa.JSON(), nullable=True))
        batch_op.drop_column('price_display')
        batch_op.drop_column('sell_price_cents')
        batch_op.drop_column('manual_lines')
    with op.batch_alter_table('cost_entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cost_entries_key'))
    op.drop_table('cost_entries')

    # V1 不含价格：规则集里的 GST 参数去掉。旧版本不改，在最新版本上另存一个新版本，写明原因
    sets = sa.table('rule_set_versions', sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                    sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                    sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))
    conn = op.get_bind()
    lines = conn.execute(sa.select(sets.c.business_line).distinct()).scalars().all()
    for line in lines:
        last = conn.execute(sa.select(sets).where(sets.c.business_line == line).order_by(sets.c.id.desc())).first()
        if not any(p["name"] in PRICE_PARAMS for p in last.content["params"]):
            continue
        content = dict(last.content, params=[p for p in last.content["params"] if p["name"] not in PRICE_PARAMS])
        major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", last.version).groups())
        conn.execute(sets.insert().values(business_line=line, version=f"v{major}.{minor + 1}", content=content,
                                          reason="CR-6：V1 不含价格，去掉 GST 参数（升级时自动生成，算式和其它参数不变）",
                                          created_by=None, created_at=utcnow()))


def downgrade() -> None:
    op.create_table('cost_entries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('sample', sa.Boolean(), nullable=False),
    sa.Column('entered_by', sa.Integer(), nullable=True),
    sa.Column('entered_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['entered_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('cost_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cost_entries_key'), ['key'], unique=False)
    with op.batch_alter_table('revisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('manual_lines', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('sell_price_cents', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('price_display', sa.String(length=10), nullable=True))
        batch_op.drop_column('boq_edits')
    op.drop_table('template_versions')
