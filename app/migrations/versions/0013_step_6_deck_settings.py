"""Step 6: proposal deck settings on each Rev (cover fields, slides left out)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-07 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('revisions') as batch:
        batch.add_column(sa.Column('deck', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('revisions') as batch:
        batch.drop_column('deck')
