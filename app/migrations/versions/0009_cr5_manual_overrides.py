"""CR-5: manual overrides of rule results per Rev

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('revisions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('overrides', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('revisions', schema=None) as batch_op:
        batch_op.drop_column('overrides')
