from alembic import context
from sqlalchemy import create_engine

from app.models import Base

config = context.config


def run(connection):
    # render_as_batch：SQLite 改表结构要整表重建
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:  # 服务器启动时由 app/db.py 传入
    run(connection)
else:  # 命令行：alembic revision --autogenerate
    with create_engine(config.get_main_option("sqlalchemy.url")).connect() as conn:
        run(conn)
