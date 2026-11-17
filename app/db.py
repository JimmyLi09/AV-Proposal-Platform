from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event

MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def migrate(engine: Engine) -> None:
    """启动时把数据库升级到最新结构，已有数据保留。"""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.connect() as conn:
        # SQLite 改表是整表重建（删旧表）：外键检查开着时，有引用的表删不掉，迁移会中断。
        # PRAGMA 只能在事务外切换，所以迁移前关、迁移后再开。
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        try:
            with conn.begin():
                # 上次迁移中断留下的临时表（原表还在）先清掉，否则这次重建会报「已存在」
                names = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
                for tmp in sorted(n for n in names if n.startswith("_alembic_tmp_")):
                    if tmp.removeprefix("_alembic_tmp_") in names:
                        conn.exec_driver_sql(f'DROP TABLE "{tmp}"')
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
