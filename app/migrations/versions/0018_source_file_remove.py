"""Source files can be removed from a project (soft delete: the original stays on disk and can be restored)

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-13 18:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('source_files') as batch:
        batch.add_column(sa.Column('removed_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('removed_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_source_files_removed_by'),
                                   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('source_files') as batch:
        batch.drop_column('removed_by')
        batch.drop_column('removed_at')
