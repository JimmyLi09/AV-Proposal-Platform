"""服务器升级到 0.10.2 时迁移 0018 中断：source_files 被 extracted_fields 引用，
外键检查开着时整表重建删不掉旧表，并留下 _alembic_tmp_source_files，之后每次启动都失败。"""
import sqlite3

from alembic import command
from alembic.config import Config

from app.db import MIGRATIONS, make_engine, migrate


def _db_at_0017_with_data(path):
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    engine = make_engine(path)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        with conn.begin():
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0017")
    engine.dispose()
    db = sqlite3.connect(path)
    db.execute("INSERT INTO users (id, name, role, created_at) VALUES (1, 'Jimmy', 'PM', '2026-11-01')")
    db.execute("INSERT INTO projects (id, name, client, location, notes, owner_id, created_by, created_at)"
               " VALUES (1, 'P', '', '', '', 1, 1, '2026-11-01')")
    db.execute("INSERT INTO source_files (id, project_id, filename, file_type, stored_path, sha256, size, uploaded_by,"
               " uploaded_at) VALUES (1, 1, 'a.pdf', 'pdf', 'files/1/a.pdf', 'x', 1, 1, '2026-11-01')")
    db.execute("INSERT INTO extracted_fields (id, source_file_id, field, value, confidence, location, snippet)"
               " VALUES (1, 1, 'width_mm', '4500', 'High', 'p1', 's')")
    db.commit()
    return db


def _check(path):
    db = sqlite3.connect(path)
    assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] != "0017"
    assert db.execute("SELECT filename, removed_at FROM source_files").fetchall() == [("a.pdf", None)]
    assert db.execute("SELECT source_file_id FROM extracted_fields").fetchall() == [(1,)]
    assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp_%'").fetchall()
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_upgrade_with_referenced_rows(tmp_path):
    path = tmp_path / "avp.db"
    _db_at_0017_with_data(path).close()
    engine = make_engine(path)
    migrate(engine)
    with engine.connect() as conn:  # 迁移后外键检查要恢复
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()
    _check(path)


def test_resume_after_interrupted_upgrade(tmp_path):
    """服务器上的状态：还在 0017，留着上次失败的临时表。"""
    path = tmp_path / "avp.db"
    db = _db_at_0017_with_data(path)
    db.execute("CREATE TABLE _alembic_tmp_source_files (id INTEGER NOT NULL PRIMARY KEY)")
    db.commit()
    db.close()
    engine = make_engine(path)
    migrate(engine)
    engine.dispose()
    _check(path)
