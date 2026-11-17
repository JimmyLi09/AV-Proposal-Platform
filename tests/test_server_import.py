"""2026-11-17：从服务器项目文件夹（D:\\LED Projects）直接导入项目文件。"""
from test_step1 import client, login, new_project  # noqa: F401


def _tree(client):
    root = client.data_dir / "LED Projects"
    job = root / "2026" / "143-Royal Plaza"
    (job / "Drawings").mkdir(parents=True)
    (job / "Drawings" / "elevation.pdf").write_bytes(b"%PDF-1.4 elevation")
    (job / "spec.xlsx").write_bytes(b"xlsx bytes")
    (job / "render.mp4").write_bytes(b"video")      # 平台不读的类型：不导入
    (job / "~$spec.xlsx").write_bytes(b"lock")      # Office 临时文件：不导入
    client.app.state.import_dir = root.resolve()
    return root, job


def test_not_configured(client):
    assert client.get("/api/import-folder").json() == {"configured": False}


def test_browse_and_import(client):
    login(client)
    root, job = _tree(client)
    top = client.get("/api/import-folder").json()
    assert top["folders"] == ["2026"] and top["files"] == 2 and top["path"] == ""
    assert client.get("/api/import-folder", params={"path": "2026"}).json()["folders"] == ["143-Royal Plaza"]

    p = new_project(client)
    r = client.post(f"/api/projects/{p['id']}/import-folder", json={"path": "2026/143-Royal Plaza"})
    assert r.status_code == 201, r.text
    assert sorted(f["filename"] for f in r.json()["files"]) == ["Drawings/elevation.pdf", "spec.xlsx"]
    assert r.json()["skipped"] == 0
    # 复制成项目原件；服务器上的原文件还在、没被改
    assert (job / "spec.xlsx").read_bytes() == b"xlsx bytes"
    assert len(list(client.data_dir.glob("files/*/*/spec.xlsx"))) == 1

    # 再导入一次：相同内容跳过
    r = client.post(f"/api/projects/{p['id']}/import-folder", json={"path": "2026/143-Royal Plaza"})
    assert r.json() == {"files": [], "skipped": 2}
    assert len(client.get(f"/api/projects/{p['id']}").json()["files"]) == 2


def test_cannot_leave_the_folder(client):
    login(client)
    _tree(client)
    p = new_project(client)
    assert client.get("/api/import-folder", params={"path": ".."}).status_code == 400
    r = client.post(f"/api/projects/{p['id']}/import-folder", json={"path": "../files"})
    assert r.status_code == 400


def test_empty_folder_and_login(client):
    login(client)
    root, job = _tree(client)
    (root / "empty").mkdir()
    p = new_project(client)
    r = client.post(f"/api/projects/{p['id']}/import-folder", json={"path": "empty"})
    assert r.status_code == 422
    client.delete("/api/session")
    assert client.post(f"/api/projects/{p['id']}/import-folder", json={"path": "2026"}).status_code == 401
