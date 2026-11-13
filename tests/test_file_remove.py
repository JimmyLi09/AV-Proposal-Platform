"""2026-11-13 试用反馈 1：导入的文件可以移除。移除只是从项目里拿掉，原件留在磁盘上，可以恢复。"""
from test_step1 import client, login, new_project, upload  # noqa: F401


def test_remove_and_restore_keeps_original(client):
    login(client)
    p = new_project(client)
    f = upload(client, p["id"], "wall.jpg", b"not really a jpg")
    stored = next(client.data_dir.glob("files/*/*/wall.jpg"))

    r = client.delete(f"/api/files/{f['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files"] == []
    assert [x["filename"] for x in body["removed_files"]] == ["wall.jpg"]
    assert body["removed_files"][0]["removed_by"] == "Jimmy"
    assert stored.read_bytes() == b"not really a jpg"  # 原件不删
    assert client.get(f"/api/files/{f['id']}").status_code == 200
    assert client.get(f"/api/projects/{p['id']}").json()["files"] == []

    r = client.post(f"/api/files/{f['id']}/restore")
    assert [x["filename"] for x in r.json()["files"]] == ["wall.jpg"]
    assert r.json()["removed_files"] == []


def test_remove_needs_a_name(client):
    login(client)
    p = new_project(client)
    f = upload(client, p["id"], "a.pdf", b"%PDF-1.4")
    client.delete("/api/session")
    assert client.delete(f"/api/files/{f['id']}").status_code == 401
    assert client.delete("/api/files/999").status_code in (401, 404)
