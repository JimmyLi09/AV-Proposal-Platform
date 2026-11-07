"""Step 6: review history on each Rev (submit / approve / send back / new Rev)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-07 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('revisions') as batch:
        batch.add_column(sa.Column('history', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('revisions') as batch:
        batch.drop_column('history')
