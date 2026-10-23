"""CR-4 验收：界面一次只显示一种语言，默认中文，按用户保存；服务器生成的提示句按 X-Lang 返回当前语言。
切到 EN 后服务器返回的内容里没有中文（用户录入的内容除外）；语言包 zh.json / en.json 键一致，界面代码里不再写中文。"""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rules.engine import load_seed

ROOT = Path(__file__).resolve().parent.parent
CJK = re.compile(r"[　-〿一-鿿＀-￯]")
RULES, SAMPLE = load_seed("LED")
EN = {"X-Lang": "en"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        user = c.post("/api/users", json={"name": "Jimmy", "role": "PM"}).json()
        c.post("/api/session", json={"user_id": user["id"]})
        pid = c.post("/api/projects", json={"name": "143-Royal Plaza LED", "client": "Royal Plaza"}).json()["id"]
        c.project = pid
        c.proposal = c.post(f"/api/projects/{pid}/proposals", json={"name": "LED-1 大堂", "business_line": "LED"}).json()["id"]
        c.put(f"/api/proposals/{c.proposal}/inputs", json={"inputs": SAMPLE["input"]})
        yield c


def test_language_is_saved_per_user_and_defaults_to_chinese(client):
    assert client.get("/api/session").json()["lang"] == "zh"
    assert client.put("/api/session/lang", json={"lang": "en"}).json()["lang"] == "en"
    assert client.get("/api/session").json()["lang"] == "en"  # 刷新、下次登录都保持
    other = client.post("/api/users", json={"name": "Wei", "role": "PM"}).json()
    assert other["lang"] == "zh"  # 每个人自己的设置
    assert client.put("/api/session/lang", json={"lang": "fr"}).status_code == 422


def test_server_messages_follow_x_lang(client):
    assert client.get("/api/projects/999").json()["detail"] == "项目不存在"
    assert client.get("/api/projects/999", headers=EN).json()["detail"] == "Project not found"
    assert client.post("/api/users", json={"name": "Jimmy"}, headers=EN).json()["detail"] == "This name already exists"


# ---- 服务器返回的内容 ----

def _strings(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v, path)
    elif isinstance(x, str):
        yield path, x


def test_english_responses_have_no_chinese(client):
    """规则结果、示意图、BOQ、图纸、产品库字段、版本说明都按英文返回。
    例外：规则结果的原始值（value / values，算式算出来的原样数据，界面显示 display）和规则集内容本身（规则页按 text 显示）。"""
    pages = [f"/api/proposals/{client.proposal}", f"/api/projects/{client.project}", "/api/projects", "/api/session",
             "/api/products/LED", "/api/products/LED/versions", "/api/rules/LED", "/api/rules/LED/versions",
             "/api/templates/LED", "/api/templates/LED/versions"]
    for url in pages:
        body = client.get(url, headers=EN).json()
        leaks = [(p, s) for p, s in _strings(body) if CJK.search(s.replace("LED-1 大堂", ""))  # 方案名是用户录入的
                 and not p.endswith((".value", ".values.installation_items")) and not p.startswith(".content.")]
        assert leaks == [], (url, leaks)
    text = client.get("/api/rules/LED", headers=EN).json()["text"]
    assert text["Environment 使用环境"] == "Environment" and text["根"] == "pcs"
    assert client.get("/api/rules/LED").json()["text"]["Environment 使用环境"] == "使用环境"


def test_rule_results_and_diagram_in_both_languages(client):
    zh = client.get(f"/api/proposals/{client.proposal}").json()["result"]
    en = client.get(f"/api/proposals/{client.proposal}", headers=EN).json()["result"]
    f3 = lambda r: next(x for x in r["rules"] if x["id"] == "F3")  # noqa: E731
    assert (f3(zh)["title"], f3(en)["title"]) == ("箱体排布", "Cabinet layout")
    assert f3(zh)["display"].startswith("35 个") and f3(en)["display"].startswith("35 (")
    f2 = lambda r: next(x for x in r["rules"] if x["id"] == "F2")["display"]  # noqa: E731
    assert (f2(zh), f2(en)) == ("224 块", "224 pcs")  # 数字不翻译，中文量词换成英文
    assert en["diagram"]["nodes"]["screen"]["title"] == "LED wall" and "LED wall" in en["diagram"]["svg"]
    assert zh["diagram"]["nodes"]["screen"]["title"] == "LED 屏"


def test_exports_keep_their_own_language(client):
    """导出文件按导出时选的语言，和界面语言分开。"""
    r = client.get(f"/api/proposals/{client.proposal}/drawing.svg?lang=zh", headers=EN)
    assert "拼接与线路图" in r.text
    r = client.get(f"/api/proposals/{client.proposal}/drawing.svg?lang=en")
    assert "Cabinet &amp; cabling drawing" in r.text and not CJK.search(r.text.replace("LED-1 大堂", ""))


# ---- 语言包 ----

PACKS = ROOT / "web" / "src" / "i18n"
SRC = ROOT / "web" / "src"


def _keys(node, prefix=""):
    for k, v in node.items():
        if isinstance(v, dict):
            yield from _keys(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def test_language_packs_have_the_same_keys_and_english_has_no_chinese():
    zh = dict(_keys(json.loads((PACKS / "zh.json").read_text(encoding="utf-8"))))
    en = dict(_keys(json.loads((PACKS / "en.json").read_text(encoding="utf-8"))))
    assert zh.keys() == en.keys()
    assert [k for k, v in en.items() if CJK.search(v)] == []
    assert all(v.strip() for v in zh.values()) and all(v.strip() for v in en.values())


def test_every_key_used_in_the_interface_exists():
    zh = dict(_keys(json.loads((PACKS / "zh.json").read_text(encoding="utf-8"))))
    prefixes = {k.rsplit(".", 1)[0] + "." for k in zh}
    code = "\n".join(p.read_text(encoding="utf-8") for p in SRC.glob("*.ts*"))
    used = set(re.findall(r"\bt\(\"([\w.]+)\"", code))
    assert used and used - zh.keys() == set()
    dynamic = set(re.findall(r"\bt(?:Or)?\(`([\w.]+\.)\$\{", code))  # 例如 t(`ws.tabs.${k}`)
    assert dynamic and dynamic - prefixes == set()


def test_interface_code_has_no_chinese_text():
    """界面文字都在语言包里。例外：切换按钮在英文界面显示「中文」，以及存进数据库的角色值「工程」。"""
    allowed = {'{lang === "zh" ? "EN" : "中文"}', 'const ROLES = ["Sales", "PM", "工程"];'}
    found = []
    for p in SRC.glob("*.ts*"):
        for line in p.read_text(encoding="utf-8").splitlines():
            code = re.sub(r"/\*.*?\*/|//.*", "", line).strip()
            if CJK.search(code) and code not in allowed:
                found.append((p.name, code))
    assert found == []
