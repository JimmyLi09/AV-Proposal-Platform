from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from . import api
from .db import make_engine, migrate

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"


def load_config() -> dict:
    return yaml.safe_load((Path(__file__).parent / "config" / "deploy.yaml").read_text(encoding="utf-8"))


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or ROOT / load_config()["data_dir"]).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(data_dir / "avp.db")
    migrate(engine)

    app = FastAPI(title="AV Proposal Platform")
    app.state.data_dir = data_dir
    app.state.Session = sessionmaker(engine, expire_on_commit=False)
    app.include_router(api.router, prefix="/api")
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
