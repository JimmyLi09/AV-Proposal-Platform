"""启动服务器：python -m app"""
import uvicorn

from .knowledge.scan import nightly
from .main import create_app, load_config

cfg = load_config()
app = create_app()
nightly(app.state)  # 资料库每晚自动复扫（CR-8）
uvicorn.run(app, host=cfg["host"], port=cfg["port"])
