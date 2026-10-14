"""第 1 步验收：能建项目、传文件，原件无法被覆盖。"""
import hashlib
import io
import stat

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import create_app
from app.models import Base
from app.storage import save_original


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        c.data_dir = tmp_path
        yield c


def login(client, name="Jimmy", role="PM"):
    user = client.post("/api/users", json={"name": name, "role": role}).json()
    assert client.post("/api/session", json={"user_id": user["id"]}).status_code == 200
    return user


def new_project(client, **extra):
    r = client.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, project_id, name, content):
    r = client.post(f"/api/projects/{project_id}/files", files=[("files", (name, content))])
    assert r.status_code == 201, r.text
    return r.json()[0]


def test_migrations_match_models(client):
    engine = create_engine(f"sqlite:///{client.data_dir / 'avp.db'}")
    with engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_writes_need_a_chosen_name(client):
    r = client.post("/api/projects", json={"name": "X", "client": "Y"})
    assert r.status_code == 401


def test_name_login_without_password(client):
    jimmy = login(client)
    assert client.get("/api/session").json() == jimmy
    assert client.post("/api/users", json={"name": "Jimmy"}).status_code == 409
    client.delete("/api/session")
    assert client.get("/api/session").json() is None


def test_project_first_number_later(client):
    jimmy = login(client)
    p = new_project(client)
    assert p["project_no"] is None
    assert p["owner"] == jimmy

    p = client.patch(f"/api/projects/{p['id']}", json={"project_no": " 143 "}).json()
    assert p["project_no"] == "143"
    assert client.get("/api/projects").json()[0]["project_no"] == "143"


def test_upload_keeps_bytes_fingerprint_and_is_read_only(client):
    login(client)
    p = new_project(client)
    content = b"%PDF-1.7 lobby elevation"
    f = upload(client, p["id"], "Lobby_Elevation_RevB.pdf", content)

    assert f["sha256"] == hashlib.sha256(content).hexdigest()
    assert f["size"] == len(content) and f["file_type"] == "pdf" and f["uploaded_by"] == "Jimmy"
    assert client.get(f"/api/files/{f['id']}").content == content

    stored = next((client.data_dir / "files" / str(p["id"])).rglob("*.pdf"))
    assert stat.S_IMODE(stored.stat().st_mode) & 0o222 == 0  # 无写权限


def test_same_name_upload_never_overwrites(client):
    login(client)
    p = new_project(client)
    first = upload(client, p["id"], "plan.pdf", b"version 1")
    second = upload(client, p["id"], "plan.pdf", b"version 2")

    assert first["id"] != second["id"]
    assert client.get(f"/api/files/{first['id']}").content == b"version 1"
    assert client.get(f"/api/files/{second['id']}").content == b"version 2"
    assert len(client.get(f"/api/projects/{p['id']}").json()["files"]) == 2


def test_no_api_changes_or_deletes_an_original(client):
    login(client)
    p = new_project(client)
    f = upload(client, p["id"], "plan.pdf", b"original")
    for method in ("put", "patch", "delete"):
        assert getattr(client, method)(f"/api/files/{f['id']}").status_code == 405
    assert client.get(f"/api/files/{f['id']}").content == b"original"


def test_storage_refuses_existing_path(tmp_path):
    save_original(tmp_path, "a/plan.pdf", io.BytesIO(b"original"))
    with pytest.raises(FileExistsError):
        save_original(tmp_path, "a/plan.pdf", io.BytesIO(b"overwrite"))
    assert (tmp_path / "a/plan.pdf").read_bytes() == b"original"


def test_windows_path_in_filename_stays_inside_data_dir(client):
    login(client)
    p = new_project(client)
    f = upload(client, p["id"], "..\\..\\CON.pdf", b"x")
    assert f["filename"] == "CON.pdf"
    stored = list((client.data_dir / "files").rglob("*"))
    assert any(s.name == "_CON.pdf" for s in stored)


def test_new_proposal_starts_at_rev0_draft(client):
    login(client)
    p = new_project(client)
    r = client.post(f"/api/projects/{p['id']}/proposals", json={"name": "LED-1 Lobby", "business_line": "LED"})
    assert r.status_code == 201
    assert r.json() | {"id": 0, "created_at": ""} == {
        "id": 0, "name": "LED-1 Lobby", "business_line": "LED", "mode": "A",
        "rev_no": 0, "status": "draft", "author": "Jimmy", "created_at": "",
    }
    bad = client.post(f"/api/projects/{p['id']}/proposals", json={"name": "X", "business_line": "CCTV"})
    assert bad.status_code == 422
