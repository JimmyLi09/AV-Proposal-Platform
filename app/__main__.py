"""启动服务器：python -m app"""
import uvicorn

from .main import create_app, load_config

cfg = load_config()
uvicorn.run(create_app(), host=cfg["host"], port=cfg["port"])
