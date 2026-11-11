"""Vercel 在线测试版入口（只在 vercel-test 分支）。

数据放在函数实例的 /tmp：实例回收后会清空，只用于试用，不用于正式数据。
OCR 和 PDF/PPT 导出依赖的重组件（Playwright/Chromium）不在这里，正式版用公司服务器。
"""
from pathlib import Path

from app.main import create_app

app = create_app(Path("/tmp/avp-data"))
