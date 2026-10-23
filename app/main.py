from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from . import annotate, api, workspace
from .db import make_engine, migrate
from .products import api as products_api
from .rules import api as rules_api
from .templates import api as templates_api

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"


def load_config() -> dict:
    """deploy.yaml 是默认值；服务器自己的设置写在 deploy.local.yaml（不进 git，更新代码时不会被覆盖）。"""
    folder = Path(__file__).parent / "config"
    cfg = yaml.safe_load((folder / "deploy.yaml").read_text(encoding="utf-8"))
    local = folder / "deploy.local.yaml"
    if local.exists():
        cfg |= yaml.safe_load(local.read_text(encoding="utf-8")) or {}
    return cfg


def create_app(data_dir: Path | None = None) -> FastAPI:
    cfg = load_config()
    data_dir = Path(data_dir or ROOT / cfg["data_dir"]).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(data_dir / "avp.db")
    migrate(engine)

    app = FastAPI(title="AV Proposal Platform")
    app.state.data_dir = data_dir
    app.state.oda = cfg.get("oda_converter") or None
    app.state.Session = sessionmaker(engine, expire_on_commit=False)
    with app.state.Session() as db:
        for module in (rules_api, products_api, templates_api):
            module.ensure_seed(db)
    for module in (api, rules_api, products_api, templates_api, workspace, annotate):
        app.include_router(module.router, prefix="/api")
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
