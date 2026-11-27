"""内置页面模板与静态资源入口。

页面 HTML、样式与脚本拆成同级独立文件，本模块只负责读取并暴露 PAGE，
鉴权 token 仍由 _handlers.py 通过 Set-Cookie 响应头注入，不写入页面。
"""

from pathlib import Path

_ASSET_DIR = Path(__file__).resolve().parent

PAGE = (_ASSET_DIR / "page.html").read_text(encoding="utf-8")
