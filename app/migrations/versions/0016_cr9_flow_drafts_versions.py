"""CR-9: flow aligned with PM Platform — drafts and official versions, bound library versions, expected delivery

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09 00:00:00
"""
import json

from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None

LOCKED = ("review", "approved")


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('delivery', sa.String(length=40), server_default='', nullable=False))
    with op.batch_alter_table('proposals') as batch:
        batch.add_column(sa.Column('reached', sa.Integer(), server_default='1', nullable=False))
        batch.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('updated_by', sa.Integer(), nullable=True))  # 用户 id，不加外键（加外键要重建整张表）
    with op.batch_alter_table('revisions') as batch:
        batch.add_column(sa.Column('saved_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('saved_by', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('pulled', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('rules_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('library_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('template_id', sa.Integer(), nullable=True))

    conn = op.get_bind()
    latest = {}
    for table in ('rule_set_versions', 'product_library_versions', 'template_versions'):
        for line, vid in conn.execute(sa.text(f"select business_line, max(id) from {table} group by business_line")):
            latest[(table, line)] = vid
    props = conn.execute(sa.text("select id, business_line, created_at, created_by from proposals")).all()
    for p in props:
        revs = conn.execute(sa.text("select id, rev_no, status, created_at, reviewed_at, author_id, locked from revisions "
                                    "where proposal_id = :p order by rev_no"), {"p": p.id}).all()
        for i, r in enumerate(revs):
            last = i == len(revs) - 1
            # 以前每个 Rev 都是直接改的：不是最新的（已经批准过）和审核中 / 已批准的算正式版本，最新还能改的算草稿
            saved = r.created_at if not last else (r.reviewed_at or r.created_at) if r.status in LOCKED else None
            # 建项时绑定版本：已锁定的用锁定时的版本，其余绑到升级时的最新版本（以后库更新不再自动跟着变）
            locked = json.loads(r.locked) if isinstance(r.locked, str) else r.locked
            ids = ((locked["rules_id"], locked["library_id"], locked["template_id"]) if locked else
                   tuple(latest.get((t, p.business_line)) for t in ('rule_set_versions', 'product_library_versions', 'template_versions')))
            conn.execute(sa.text("update revisions set saved_at = :s, saved_by = :b, rules_id = :r, library_id = :l, "
                                 "template_id = :t where id = :id"),
                         {"s": saved, "b": r.author_id if saved else None, "r": ids[0], "l": ids[1], "t": ids[2], "id": r.id})
        statuses = {r.status for r in revs}
        last = revs[-1] if revs else None
        # 走到过的最远一步：0 = 01 … 4 = 07
        reached = 4 if statuses & set(LOCKED) else 2 if last is not None and last.status == "calculated" else 1
        conn.execute(sa.text("update proposals set reached = :r, updated_at = :u, updated_by = :b where id = :id"),
                     {"r": reached, "u": last.created_at if last is not None else p.created_at, "b": p.created_by, "id": p.id})


def downgrade() -> None:
    with op.batch_alter_table('revisions') as batch:
        for col in ('template_id', 'library_id', 'rules_id', 'pulled', 'saved_by', 'saved_at'):
            batch.drop_column(col)
    with op.batch_alter_table('proposals') as batch:
        for col in ('updated_by', 'updated_at', 'reached'):
            batch.drop_column(col)
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('delivery')
