"""CR-8: knowledge base (files, full-text index, past projects, learned items to confirm)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-24 06:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'kb_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rel_path', sa.String(length=500), nullable=False),
        sa.Column('doc_type', sa.String(length=12), nullable=False),
        sa.Column('project_key', sa.String(length=200), nullable=True),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('mtime_ns', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('read_status', sa.String(length=10), nullable=False),
        sa.Column('read_method', sa.String(length=20), nullable=True),
        sa.Column('read_note', sa.Text(), nullable=False),
        sa.Column('chunks', sa.Integer(), nullable=False),
        sa.Column('facts', sa.JSON(), nullable=True),
        sa.Column('missing', sa.Boolean(), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rel_path'),
    )
    op.create_index('ix_kb_files_project_key', 'kb_files', ['project_key'])
    op.create_table(
        'kb_projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('project_no', sa.String(length=40), nullable=True),
        sa.Column('record', sa.JSON(), nullable=True),
        sa.Column('record_version', sa.Integer(), nullable=False),
        sa.Column('record_by', sa.Integer(), nullable=True),
        sa.Column('record_at', sa.DateTime(), nullable=True),
        sa.Column('standard_manual', sa.Boolean(), nullable=False),
        sa.Column('standard_by', sa.Integer(), nullable=True),
        sa.Column('standard_at', sa.DateTime(), nullable=True),
        sa.Column('standard_list', sa.Boolean(), nullable=False),
        sa.Column('missing', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['record_by'], ['users.id']),
        sa.ForeignKeyConstraint(['standard_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_table(
        'kb_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('business_line', sa.String(length=10), nullable=True),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('source_file_id', sa.Integer(), nullable=True),
        sa.Column('location', sa.String(length=200), nullable=False),
        sa.Column('snippet', sa.Text(), nullable=False),
        sa.Column('confidence', sa.String(length=6), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('decided_by', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id']),
        sa.ForeignKeyConstraint(['source_file_id'], ['kb_files.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_kb_items_fingerprint', 'kb_items', ['fingerprint'])
    op.create_table(
        'kb_settings',
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    # 全文索引：trigram 分词，中文不用分词也能按任意 3 个字以上查；更短的词用 LIKE 逐行比
    op.execute("CREATE VIRTUAL TABLE kb_fts USING fts5(text, file_id UNINDEXED, location UNINDEXED, "
               "tokenize='trigram')")


def downgrade() -> None:
    op.execute("DROP TABLE kb_fts")
    op.drop_table('kb_settings')
    op.drop_index('ix_kb_items_fingerprint', table_name='kb_items')
    op.drop_table('kb_items')
    op.drop_table('kb_projects')
    op.drop_index('ix_kb_files_project_key', table_name='kb_files')
    op.drop_table('kb_files')
