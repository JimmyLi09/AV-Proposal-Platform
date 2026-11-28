"""2026-11-17：产品库导入文件——Excel 导出 / 批量导入，规格书读参数。"""
import io
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook

from test_step1 import client, login  # noqa: F401

KB = Path(__file__).parent / "fixtures" / "knowledge" / "kb" / "规格书"


def _library(client, line="LED"):
    return client.get(f"/api/products/{line}").json()


def _import(client, wb, content, line="LED"):
    buf = io.BytesIO()
    wb.save(buf)
    return client.post(f"/api/products/{line}/excel", files={"file": ("p.xlsx", buf.getvalue())},
                       data={"content": json.dumps(content)})


def test_export_then_import_is_a_round_trip(client):
    login(client)
    lib = _library(client)
    r = client.get("/api/products/LED/excel")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["箱体", "控制器", "视频处理器"]
    assert wb["控制器"]["A1"].value == "编号 ID" and wb["控制器"]["A2"].value == "SC-4"
    out = _import(client, wb, lib["content"]).json()
    assert out["errors"] == [] and out["added"] == [] and out["updated"] == []
    assert out["products"] == lib["content"]["products"]


def test_import_adds_and_updates_without_saving(client):
    login(client)
    lib = _library(client)
    wb = Workbook()
    ws = wb.active
    ws.title = "Controller"  # 英文表名、只写英文的表头也认
    ws.append(["ID", "Brand", "Model", "Status", "Load px", "Ports", "Sample data"])
    ws.append(["VX1000", "NovaStar", "VX1000", "首选", "6,500,000", 10, "否"])
    ws.append(["SC-4", None, None, None, 2600000, None, None])        # 已有：只改带载，空格子不改
    ws.append(["BAD", "X", "Y", "首选", "很多", 4, "否"])               # 看不懂的数 → 这一行不导入
    ws.append([None, "no id", "Z", None, None, None, None])           # 没编号的行跳过
    out = _import(client, wb, lib["content"]).json()
    assert out["added"] == ["VX1000"] and out["updated"] == ["SC-4"]
    assert len(out["errors"]) == 1 and out["errors"][0].startswith("Controller!4")
    vx = next(p for p in out["products"] if p["id"] == "VX1000")
    assert (vx["category"], vx["capacity_px"], vx["ports"], vx["status"], vx["scenes"]) == \
        ("controller", 6500000, 10, "preferred", ["indoor"])
    sc4 = next(p for p in out["products"] if p["id"] == "SC-4")
    old = next(p for p in lib["content"]["products"] if p["id"] == "SC-4")
    assert sc4 == old | {"capacity_px": 2600000}
    assert _library(client)["version"] == lib["version"]  # 只是草稿，没有另存版本
    # 草稿照常保存成新版本
    r = client.post("/api/products/LED", json={"base_id": lib["id"], "reason": "Excel 导入", "content":
                                                {**lib["content"], "products": out["products"]}})
    assert r.status_code == 201, r.text


def test_cabinet_sizes_and_scenes(client):
    login(client)
    lib = _library(client)
    wb = Workbook()
    ws = wb.active
    ws.title = "箱体"
    ws.append(["编号", "型号", "适用场景", "点间距 mm", "模组宽 mm", "模组高 mm", "箱体尺寸 mm（第一个为主尺寸）", "维护方式"])
    ws.append(["P1538", "P1.538", "室内、租赁", 1.538, 320, 160, "640x480; 640 × 360", "前维护"])
    out = _import(client, wb, lib["content"]).json()
    assert out["errors"] == []
    p = next(p for p in out["products"] if p["id"] == "P1538")
    assert p["scenes"] == ["indoor", "rental"] and p["cabinet_sizes_mm"] == [[640, 480], [640, 360]]
    assert p["pixel_pitch_mm"] == 1.538 and p["maintenance"] == "front"


def test_not_an_excel(client):
    login(client)
    r = client.post("/api/products/LED/excel", files={"file": ("p.xlsx", b"nope")},
                    data={"content": json.dumps(_library(client)["content"])})
    assert r.status_code == 422


def test_datasheet_values_with_source_text(client):
    login(client)
    pdf = (KB / "VX1000_Spec_EN.pdf").read_bytes()
    r = client.post("/api/products/LED/datasheet", files={"file": ("VX1000_Spec_EN.pdf", pdf)},
                    data={"category": "controller"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["datasheet"] == "VX1000_Spec_EN.pdf" and out["read"] and not out["ocr"]
    assert out["values"]["capacity_px"]["value"] == 6500000
    assert out["values"]["ports"]["value"] == 10
    assert "6.5 million" in out["values"]["capacity_px"]["snippet"]
    saved = list(client.data_dir.glob("datasheets/*/VX1000_Spec_EN.pdf"))  # 原件存档
    assert len(saved) == 1 and saved[0].read_bytes() == pdf

    pj = (KB / "PT-BHZ611C_datasheet.pdf").read_bytes()
    out = client.post("/api/products/PJ/datasheet", files={"file": ("PT-BHZ611C.pdf", pj)},
                      data={"category": "projector"}).json()
    assert {f: v["value"] for f, v in out["values"].items()} == {
        "lumens": 6000, "native_px_w": 1920, "native_px_h": 1200, "power_w": 460, "weight_kg": 22.7, "noise_db": 37}


def test_datasheet_rejects(client):
    login(client)
    assert client.post("/api/products/LED/datasheet", files={"file": ("a.exe", b"x")},
                       data={"category": "controller"}).status_code == 422
    assert client.post("/api/products/LED/datasheet", files={"file": ("a.pdf", b"x")},
                       data={"category": "lens"}).status_code == 422
    client.delete("/api/session")
    assert client.post("/api/products/LED/datasheet", files={"file": ("a.pdf", b"x")},
                       data={"category": "controller"}).status_code == 401


# ---- 2026-11-18：规格书批量导入（Word / PDF / 图片 / Excel / 旧版 .xls），可直接读服务器文件夹 ----
SPECS = Path(__file__).parent / "fixtures" / "specs"
ZH = "P1.538室内52扫-640X480 模组规格书V1.0.docx"
EN = "P1.538 indoor 52scan -640X480 module specs V1.0.docx"
XLS = "MCTRL700 controller spec.xls"


def _items(r):
    assert r.status_code == 200, r.text
    return {i["file"]: i for i in r.json()["items"]}


def test_batch_reads_word_and_old_excel(client):
    login(client)
    files = [("files", (n, (SPECS / n).read_bytes())) for n in (ZH, EN, XLS)]
    files.append(("files", ("notes.txt", b"x")))
    r = client.post("/api/products/LED/datasheets", files=files)
    items = _items(r)
    assert r.json()["skipped"] == ["notes.txt"]

    zh = items[ZH]
    assert (zh["category"], zh["model"], zh["read"], zh["ocr"]) == ("cabinet", "P1.538室内52扫-640X480", True, False)
    got = {f: v["value"] for f, v in zh["values"]["cabinet"].items()}
    assert got == {"pixel_pitch_mm": 1.538, "module_w_mm": 320, "module_h_mm": 160, "cabinet_sizes_mm": [[640, 480]],
                   "brightness_nits": 600, "max_power_w_m2": 450, "maintenance": "front", "scenes": ["indoor"], "ip": "IP30"}
    assert "像素间距" in zh["values"]["cabinet"]["pixel_pitch_mm"]["snippet"]  # 每个值带原文

    en = items[EN]
    assert en["category"] == "cabinet" and en["same_as"] == 0  # 中英文两份是同一个产品
    assert {f: v["value"] for f, v in en["values"]["cabinet"].items()} == got

    mc = items[XLS]
    assert (mc["category"], mc["brand"], mc["id"]) == ("controller", "NovaStar", "MCTRL700-CONTROLLER")
    assert {f: v["value"] for f, v in mc["values"]["controller"].items()} == {"capacity_px": 2300000, "ports": 6}
    assert len(list(client.data_dir.glob("datasheets/*/*"))) == 3  # 原件都存档
    assert _library(client)["version"] == "v1.0"  # 只是复核表，没改产品库


def test_batch_from_the_server_folder(client):
    login(client)
    root = client.data_dir / "LED Projects"
    (root / "Specs").mkdir(parents=True)
    for n in (ZH, XLS):
        (root / "Specs" / n).write_bytes((SPECS / n).read_bytes())
    client.app.state.import_dir = root.resolve()
    listing = client.get("/api/import-folder", params={"path": "Specs", "entries": 1}).json()
    assert sorted(e["name"] for e in listing["entries"]) == sorted([ZH, XLS])
    items = _items(client.post("/api/products/LED/datasheets/server", json={"paths": [f"Specs/{ZH}", f"Specs/{XLS}"]}))
    assert items[ZH]["values"]["cabinet"]["pixel_pitch_mm"]["value"] == 1.538
    assert (root / "Specs" / ZH).exists()  # 服务器上的原文件不动
    assert client.post("/api/products/LED/datasheets/server", json={"paths": ["../avp.db"]}).status_code == 404


def test_batch_knows_products_already_in_the_library(client):
    login(client)
    pdf = (KB / "VX1000_Spec_EN.pdf").read_bytes()
    lib = _library(client)
    content = {**lib["content"], "products": [*lib["content"]["products"], {
        "id": "VX1000", "category": "controller", "brand": "NovaStar", "model": "VX1000", "status": "approved",
        "scenes": ["indoor"], "datasheet": "", "sample": False, "capacity_px": None, "ports": None}]}
    assert client.post("/api/products/LED", json={"base_id": lib["id"], "reason": "t", "content": content}).status_code == 201
    item = _items(client.post("/api/products/LED/datasheets", files=[("files", ("VX1000_Spec_EN.pdf", pdf))]))["VX1000_Spec_EN.pdf"]
    assert item["match"] == "VX1000" and item["id"] == "VX1000"


def test_vx_series_is_a_processor_with_sending(client):
    """VX 系列一体机：类别猜视频处理器；写了带载和网口 → 含发送（CR-2，可以代替控制器）。"""
    login(client)
    pdf = (KB / "VX1000_Spec_EN.pdf").read_bytes()
    item = _items(client.post("/api/products/LED/datasheets", files=[("files", ("VX1000_Spec_EN.pdf", pdf))]))["VX1000_Spec_EN.pdf"]
    assert (item["category"], item["model"], item["brand"], item["match"]) == ("processor", "VX1000", "NovaStar", None)
    got = {f: v["value"] for f, v in item["values"]["processor"].items()}
    assert got["sending"] is True and got["capacity_px"] == 6500000 and got["ports"] == 10


def test_spec_patterns_for_module_datasheets():
    from app.knowledge.learn import spec_values

    fields = {"pixel_pitch_mm", "module_w_mm", "module_h_mm", "cabinet_sizes_mm", "brightness_nits", "max_power_w_m2"}
    got = lambda t: {k: v[0] for k, v in spec_values([("¶1", t)], fields).items()}  # noqa: E731
    assert got("点间距 P1.86\n模组尺寸 172.8*86.4mm\n亮度均匀性 ≥97%\n亮度 800") == \
        {"pixel_pitch_mm": 1.86, "module_w_mm": 172.8, "module_h_mm": 86.4, "brightness_nits": 800}
    assert got("Max power consumption 120 W/cabinet") == {}  # 每箱功耗不是 W/㎡
    assert got("亮度调节 256级") == {}


# ---- 2026-11-19：导入模板；产品表 Excel 和规格书一起批量导入（也可以从服务器文件夹） ----

def _template_with_rows(client):
    wb = load_workbook(io.BytesIO(client.get("/api/products/template.xlsx").content))
    assert wb.sheetnames == ["说明", "箱体", "控制器", "视频处理器", "投影机", "镜头", "融合器"]
    assert wb["控制器"].max_row == 1  # 只有表头
    head = [c.value for c in wb["控制器"][1]]
    row = {h: None for h in head}
    row.update({"编号 ID": "MCTRL4K", "品牌": "NovaStar", "型号": "MCTRL4K", "状态": "首选", "适用场景": "室内、租赁",
                "带载像素 px": "8,800,000", "网口数": 16})
    wb["控制器"].append([row[h] for h in head])
    wb["控制器"].append(["SC-4"] + [None] * (len(head) - 1))  # 已有产品：空格子不改 → 不算改动也照样列出
    wb["控制器"].append(["BAD", None, "X", None, None, None, None, "很多"] + [None] * (len(head) - 8))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), head


def test_template_has_a_help_sheet_and_round_trips(client):
    login(client)
    data, head = _template_with_rows(client)
    help_rows = [[c.value for c in r] for r in load_workbook(io.BytesIO(data))["说明"].iter_rows()]
    assert ["控制器", "带载像素 px", "数字，可以带千分位逗号", 2300000] in help_rows
    # 「导入 Excel」也认模板（说明页跳过）
    out = client.post("/api/products/LED/excel", files={"file": ("t.xlsx", data)},
                      data={"content": json.dumps(_library(client)["content"])}).json()
    assert out["added"] == ["MCTRL4K"] and len(out["errors"]) == 1


def test_product_table_and_datasheets_in_one_batch(client):
    login(client)
    data, _ = _template_with_rows(client)
    files = [("files", ("产品表.xlsx", data)), ("files", (ZH, (SPECS / ZH).read_bytes()))]
    r = client.post("/api/products/LED/datasheets", files=files)
    assert r.status_code == 200, r.text
    out = r.json()
    rows = {i["id"]: i for i in out["items"]}
    mc = rows["MCTRL4K"]
    assert (mc["table"], mc["category"], mc["brand"], mc["model"], mc["match"]) == (True, "controller", "NovaStar", "MCTRL4K", None)
    assert {f: v["value"] for f, v in mc["values"]["controller"].items()} == {
        "status": "preferred", "scenes": ["indoor", "rental"], "capacity_px": 8800000, "ports": 16}
    assert mc["file"] == "产品表.xlsx · 控制器!2"
    assert rows["SC-4"]["match"] == "SC-4" and rows["SC-4"]["model"] == next(p["model"] for p in _library(client)["content"]["products"] if p["id"] == "SC-4")
    assert len(out["errors"]) == 1 and "控制器!4" in out["errors"][0]
    assert any(i["file"] == ZH and i["category"] == "cabinet" for i in out["items"])  # 规格书照常读


def test_settings_show_the_server_folder(client):
    login(client)
    assert client.get("/api/settings").json()["server"]["import_dir"] is None
    client.app.state.import_dir = (client.data_dir / "LED Projects").resolve()
    assert client.get("/api/settings").json()["server"]["import_dir"].endswith("LED Projects")


# ---- 2026-11-28 用 Jimmy 的真实规格书（G:\Works\LED Projects\Specs）调读取 ----

def test_real_datasheet_wordings():
    from app.knowledge.learn import spec_values

    fields = {"module_w_mm", "module_h_mm", "cabinet_sizes_mm", "cabinet_max", "max_power_w_m2"}
    got = lambda t: {k: v[0] for k, v in spec_values([("¶1", t)], fields).items()}  # noqa: E731
    en = ("Module Resolution\n160(W) X 80(H)\nModule Size\n320mm(W) X 160mm(H)\nModule Maximum Power Consumption\nAbout 20W (typ.)\n"
          "Cabinet Size\n640*480mm\nCabinet Maximum Current\nAbout 0.55 A\nCabinet Maximum Power Consumption\nAbout 120W")
    assert got(en) == {"module_w_mm": 320, "module_h_mm": 160, "cabinet_sizes_mm": [[640, 480]],
                                               "cabinet_max": {"640x480": {"a": 0.55, "w": 120, "sample": False}}}
    zh = "模组分辨率\n宽256点X 高128点\n模组尺寸\n宽320mmX 高160mm\n箱体尺寸\n640*480mm\n箱体最大电流\n约 0.6 A\n箱体最大功耗\n约 136W"
    assert got(zh) == {"module_w_mm": 320, "module_h_mm": 160, "cabinet_sizes_mm": [[640, 480]],
                                               "cabinet_max": {"640x480": {"a": 0.6, "w": 136, "sample": False}}}
    assert got("Module Size\n(W) 240mm X (h) 120mm x 8.0mm(d)") == {"module_w_mm": 240, "module_h_mm": 120}


def test_reimporting_a_datasheet_updates_the_product_it_made(client):
    """以前导入时没读到模组尺寸的产品：同一份规格书再导入 → 按文件名对上，改为更新，不重复新增。"""
    login(client)
    lib = _library(client)
    old = {"id": "P1538-OLD", "category": "cabinet", "brand": "", "model": "P1.538室内52扫-640X480", "status": "approved",
           "scenes": ["indoor"], "sample": False, "datasheet": ZH, "pixel_pitch_mm": 1.538, "module_w_mm": None,
           "module_h_mm": None, "cabinet_sizes_mm": None, "maintenance": "front"}
    blank = {f["name"]: None for f in lib["fields"]["cabinet"]}
    content = {**lib["content"], "products": [*lib["content"]["products"], blank | old]}
    assert client.post("/api/products/LED", json={"base_id": lib["id"], "reason": "t", "content": content}).status_code == 201
    item = _items(client.post("/api/products/LED/datasheets", files=[("files", (ZH, (SPECS / ZH).read_bytes()))]))[ZH]
    assert item["match"] == "P1538-OLD" and item["values"]["cabinet"]["module_w_mm"]["value"] == 320


def test_brightness_ignores_numbers_that_cannot_be_nits():
    """服务器上读出过亮度 422500、288895：不是亮度的数跳过，接着找下一行。"""
    from app.knowledge.learn import spec_values

    lines = [("¶1", "Brightness uniformity ≥97%  Contrast 422500"), ("¶2", "亮度 288895"), ("¶3", "Brightness 800 nits")]
    assert spec_values(lines, {"brightness_nits"})["brightness_nits"][0] == 800
