"""设置页：人员（姓名、角色、做过的方案数，可改角色）、服务器与存储（只显示）、立即备份。
备份要有一致的数据库副本和资料目录里的原件；资料库文件夹（公司共享的原资料）和备份文件夹本身不打包。"""
import sqlite3
import time
import zipfile

from fastapi.testclient import TestClient

from app.main import create_app

SAMPLE = b"%PDF-1.4 sample"


def start(tmp_path):
    c = TestClient(create_app(tmp_path / "data"))
    c.__enter__()
    jimmy = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
    c.post("/api/users", json={"name": "Candy", "role": "Sales"})
    c.post("/api/session", json={"user_id": jimmy["id"]})
    return c, jimmy


def wait(c):
    for _ in range(200):
        s = c.get("/api/settings").json()
        if not s["backup"]["running"]:
            return s
        time.sleep(0.05)
    raise AssertionError("备份没有做完")


def test_people_and_server(tmp_path):
    c, jimmy = start(tmp_path)
    p = c.post("/api/projects", json={"name": "143-Royal Plaza", "client": "Royal", "business_line": "LED"}).json()
    c.post(f"/api/projects/{p['id']}/proposals", json={"name": "LED-2", "business_line": "LED"})
    s = c.get("/api/settings").json()
    assert [(u["name"], u["role"], u["proposals"]) for u in s["users"]] == [("Candy", "Sales", 0), ("Jimmy", "PM", 2)]
    server = s["server"]
    assert server["port"] == 8081 and server["data_dir"] == str((tmp_path / "data").resolve())
    assert server["backup_dir"] == str((tmp_path / "data" / "backups").resolve()) and server["kb_dir"].endswith("knowledge")
    assert server["project_platform"] == "http://192.168.1.241:3000" and server["version"] is None and server["dwg"] is False
    assert s["backups"] == [] and s["backup"] is None

    candy = next(u for u in s["users"] if u["name"] == "Candy")
    assert c.put(f"/api/users/{candy['id']}", json={"role": "工程"}).json()["role"] == "工程"
    assert c.put("/api/users/999", json={"role": "PM"}).status_code == 404
    c.delete("/api/session")
    assert c.put(f"/api/users/{candy['id']}", json={"role": "PM"}).status_code == 401  # 要先选名字


def test_backup_has_the_database_and_originals_but_not_the_knowledge_folder(tmp_path):
    c, _ = start(tmp_path)
    data = tmp_path / "data"
    p = c.post("/api/projects", json={"name": "143-Royal Plaza", "client": "Royal", "business_line": "LED"}).json()
    assert c.post(f"/api/projects/{p['id']}/files", files=[("files", ("Plan.pdf", SAMPLE))]).status_code == 201
    (data / "knowledge" / "以往项目" / "old.pdf").write_bytes(SAMPLE)  # 资料库的原资料：不打包

    r = c.post("/api/backups")
    assert r.status_code == 202 and r.json()["backup"]["by"] == "Jimmy"
    s = wait(c)
    assert s["backup"]["error"] is None and [b["name"] for b in s["backups"]] == [s["backup"]["name"]]
    zip_path = data / "backups" / s["backup"]["name"]
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        z.extract("avp.db", tmp_path / "restore")
    assert "avp.db" in names and not any(n.startswith(("knowledge/", "backups/")) or n.startswith("avp.db-") for n in names)
    assert [n for n in names if n.startswith("files/")] and all(n.endswith("Plan.pdf") for n in names if n.startswith("files/"))
    with sqlite3.connect(tmp_path / "restore" / "avp.db") as db:  # 备份里的数据库能打开，项目都在
        assert db.execute("select name from projects").fetchall() == [("143-Royal Plaza",)]
    assert not list((data / "backups").glob("*.part"))

    time.sleep(1.1)  # 文件名精确到秒
    c.post("/api/backups")
    s = wait(c)
    assert len(s["backups"]) == 2
    with zipfile.ZipFile(data / "backups" / s["backup"]["name"]) as z:
        assert not any(n.startswith("backups/") for n in z.namelist())  # 上一份备份不会被打进来


def test_only_one_backup_at_a_time(tmp_path):
    c, _ = start(tmp_path)
    lock = c.app.state.backup_lock
    lock.acquire()
    try:
        r = c.post("/api/backups")
        assert r.status_code == 409 and "正在进行" in r.json()["detail"]
    finally:
        lock.release()
