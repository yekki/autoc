"""首页路由与静态文件服务"""

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from autoc.server import app, BASE_DIR


# ==================== 首页 ====================

@app.get("/", response_class=HTMLResponse)
async def index():
    """返回主页面 (web/dist)"""
    html_path = BASE_DIR / "web" / "dist" / "index.html"
    if not html_path.exists():
        return HTMLResponse(
            "<h1>web/dist/index.html 未找到，请先构建前端: cd web && npm run build</h1>",
            status_code=404,
        )
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ==================== 静态文件服务 ====================

_frontend_dist = BASE_DIR / "web" / "dist"
if _frontend_dist.exists() and _frontend_dist.is_dir():
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")
