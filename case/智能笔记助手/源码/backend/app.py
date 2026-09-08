"""Flask 应用入口：创建 app、注册蓝图、可选托管前端构建产物。"""
import logging
from pathlib import Path
from flask import Flask, send_from_directory
from flask_cors import CORS
from src.config import settings
from src.api import api_bp

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("notes-assistant")


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)  # 允许前端（Vite 5173 / 生产同源）跨域调用
    app.register_blueprint(api_bp)

    @app.route("/api/health")
    @app.route("/health")
    def _health():
        return {"service": "智能笔记助手 RAG 后端", "version": "1.0.0"}

    # 可选：若前端已构建到 ../frontend/dist，则由 Flask 一并托管（单服务部署）
    frontend_dist = settings.BASE_DIR.parent / "frontend" / "dist"
    if frontend_dist.exists():
        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_frontend(path):
            target = frontend_dist / path
            if path and target.exists() and target.is_file():
                return send_from_directory(str(frontend_dist), path)
            return send_from_directory(str(frontend_dist), "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    logger.info("启动智能笔记助手后端 %s:%s", settings.APP_HOST, settings.APP_PORT)
    app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False, threaded=True)
