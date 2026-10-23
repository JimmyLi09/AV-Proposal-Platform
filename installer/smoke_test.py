"""安装包验收（在 GitHub Actions 的 Windows 机器上，装好之后跑）。

python installer/smoke_test.py fresh <资料目录>      服务能打开，能建项目，上传的样本能读出来，原件只读；
                                                    算出结果后能导出 BOQ Excel、图纸 DXF 和技术方案 PDF（服务里的 Chromium 能用）
python installer/smoke_test.py upgraded <资料目录>   再装一次（更新）之后，之前的项目还在
"""
import stat
import sys
import time
from pathlib import Path

import httpx

SAMPLES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "samples"
GRADES = {"Lobby_Elevation_RevB.pdf": "A", "LED_Requirement.xlsx": "A", "Lobby_site_photo.jpg": "B",
          "Concept_render.png": "C"}
PROJECT = "CI 安装包验收"


def ok(r: httpx.Response) -> httpx.Response:
    if r.is_error:
        raise SystemExit(f"{r.request.method} {r.request.url} → {r.status_code} {r.text}")
    return r


def wait_until_up(c: httpx.Client, seconds=180):
    end = time.time() + seconds
    while True:
        try:
            if c.get("/api/users").status_code == 200:
                return
        except httpx.TransportError:
            pass
        if time.time() > end:
            raise SystemExit("服务没有起来")
        time.sleep(2)


def fresh(c: httpx.Client, data: Path):
    page = ok(c.get("/"))
    assert "text/html" in page.headers["content-type"], page.headers
    user = ok(c.post("/api/users", json={"name": "CI", "role": "PM"})).json()
    ok(c.post("/api/session", json={"user_id": user["id"]}))
    pid = ok(c.post("/api/projects", json={"name": PROJECT, "client": "CI"})).json()["id"]
    ok(c.post(f"/api/projects/{pid}/files", files=[("files", (n, (SAMPLES / n).read_bytes())) for n in GRADES]))

    end = time.time() + 300
    while True:
        try:
            files = ok(c.get(f"/api/projects/{pid}")).json()["files"]
            if all(f["read_status"] != "reading" for f in files):
                break
        except httpx.TransportError:  # 识别时服务器很忙，空闲连接可能刚好被关掉；浏览器会自动重试，这里也重试
            pass
        if time.time() > end:
            raise SystemExit("读取超时")
        time.sleep(3)
    for f in files:
        print(f["filename"], f["grade"], f["read_status"], f["read_method"], f["fields_found"], f["read_note"])
        assert f["grade"] == GRADES[f["filename"]], f
        assert f["read_status"] == ("attached" if f["grade"] == "C" else "read"), f

    prop = ok(c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1 Lobby", "business_line": "LED"})).json()["id"]
    inputs = {"environment": "indoor", "pixel_pitch_mm": 2.5, "width_mm": 4480, "height_mm": 2560, "installation": "wall",
              "maintenance": "front", "brightness_required_nits": 600, "viewing_distance_m": [4, 6], "signal_sources": 1}
    assert ok(c.put(f"/api/proposals/{prop}/inputs", json={"inputs": inputs})).json()["rev"]["status"] == "calculated"
    for path, magic in (("boq.xlsx", b"PK"), ("drawing.dxf", b"  0"), ("drawing.pdf", b"%PDF-")):
        body = ok(c.get(f"/api/proposals/{prop}/{path}", timeout=180)).content
        assert body.startswith(magic), (path, body[:20])
        print(path, len(body), "bytes")

    stored = list((data / "files").rglob("*.*"))
    assert len(stored) == len(GRADES) and not any(p.stat().st_mode & stat.S_IWRITE for p in stored), stored  # 原件只读
    assert (data / "avp.db").exists()


def upgraded(c: httpx.Client, data: Path):
    names = [p["name"] for p in ok(c.get("/api/projects")).json()]
    assert PROJECT in names, names
    assert len(list((data / "files").rglob("*.*"))) == len(GRADES)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认编码打不出中文
    step, data = sys.argv[1], Path(sys.argv[2])
    with httpx.Client(base_url="http://localhost:8081", timeout=60) as client:
        wait_until_up(client)
        {"fresh": fresh, "upgraded": upgraded}[step](client, data)
    print(step, "OK")
