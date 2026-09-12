"""EduAgentX 后端应用工厂。

用法：
    from app import create_app
    app = create_app()            # 读 APP_ENV，默认 development
    app = create_app("testing")   # 显式指定
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from flask import Flask
from flask.json.provider import DefaultJSONProvider

from app.config import resolve_config
from app.extensions import cors, db, migrate

# 注意：import app.extensions 这个动作本身就会给 SQLAlchemy Engine 注册
# SQLite PRAGMA 监听器（见 extensions.py），import 语句不能省略。

__version__ = "0.1.0"


def create_app(config_name: str | None = None) -> Flask:
    config_class = resolve_config(config_name)

    app = Flask(__name__, instance_relative_config=False)
    # 在调用时展开配置（含环境变量），不在 import 时冻结
    app.config.from_mapping(config_class.load())

    # 中文原样返回，前端调试不用看 \uXXXX。
    # 这两个属性是 DefaultJSONProvider 的，但 Flask 把 app.json 标注成了
    # 基类 JSONProvider —— cast 一下才能让类型检查看到它们。
    json_provider = cast(DefaultJSONProvider, app.json)
    json_provider.ensure_ascii = False
    json_provider.sort_keys = False

    _ensure_directories(app)
    _init_extensions(app)
    _install_error_handlers(app)
    _register_blueprints(app)
    _register_cli(app)

    from app.common.logging import configure_logging, get_logger

    if not app.config.get("TESTING"):
        configure_logging(app)

    logger = get_logger("app")
    logger.info(
        "EduAgentX 后端启动 env=%s version=%s llm=%s",
        app.config.get("ENV_NAME"),
        __version__,
        app.config.get("LLM_PROVIDER"),
    )

    if not app.config.get("SECRET_KEY"):
        logger.warning("未配置 SECRET_KEY，指纹盐与 Flask 会话都会退化（仅限本地开发）")

    if app.config.get("ENV_NAME") == "production":
        _warn_missing_credentials(app, logger)

    _log_provider_self_check(app, logger)
    _recover_stuck_jobs(app, logger)

    return app


def _recover_stuck_jobs(app: Flask, logger) -> None:
    """启动时收拾上一次进程留下的「还在生成中」（P1-C5）。

    这一步要读库，所以只能在表建好之后跑；库还没迁移时跳过 ——
    `flask db upgrade` 得先能建出 app 来，恢复不能把启动卡死。
    跳过是安全的：那些任务此刻也还是 `running`，下次启动照样会被收拾。
    """
    from app.services.generation.pipeline import recover_stuck_jobs

    try:
        with app.app_context():
            report = recover_stuck_jobs()
    except Exception as exc:  # pragma: no cover - 未迁移 / 库被占用
        logger.debug("跳过重启收拾（库还没就绪）：%s", type(exc).__name__)
        return
    if report["jobs"] or report["courses"]:
        logger.warning(
            "启动收拾了 %d 个中断任务、%d 门课程（状态已置 failed，可重试）",
            report["jobs"],
            report["courses"],
        )


def _log_provider_self_check(app: Flask, logger) -> None:
    """启动自检（F0-8）：把「哪几个能力现在真的能用」写进日志。

    只按 .env 判断，**不读数据库也不联网**：
    - 不读库：迁移还没跑的时候应用照样要能起来（见 services/provider_registry.py）
    - 不联网：「连不连得上」是设置页「测试连接」按钮的职责；
      把探活塞进启动会让断网直接等于服务起不来
    """
    if app.config.get("TESTING"):
        return

    from app.services.provider_registry import registry_from_config, self_check

    report = self_check(registry_from_config(app.config))
    active = " ".join(f"{kind}={name}" for kind, name in report["active"].items())
    logger.info("Provider 自检：%s", active)
    for issue in report["issues"]:
        log = logger.error if issue["level"] == "error" else logger.warning
        log("Provider 自检：%s", issue["message"])


def _ensure_directories(app: Flask) -> None:
    """上传目录 / 数据库目录必须在启动时存在，否则第一次写入才炸。"""
    for key in ("UPLOAD_DIR",):
        raw = app.config.get(key)
        if raw:
            Path(raw).mkdir(parents=True, exist_ok=True)

    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if uri.startswith("sqlite:///") and ":memory:" not in uri and uri != "sqlite://":
        db_path = Path(uri.removeprefix("sqlite:///"))
        if not db_path.is_absolute():
            db_path = Path(app.root_path).parent / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(
        app,
        db,
        # SQLite 不支持大部分 ALTER TABLE：batch mode 会「建新表→拷数据→换名」，
        # 让后续阶段的加列/改约束能正常迁移。现在开好，省得 P1 再改。
        render_as_batch=True,
        compare_type=True,
    )

    # import 即注册模型到 db.metadata —— 漏了它 create_all / autogenerate 会看不到表
    from app import models  # noqa: F401

    # 前端只与自己的 Flask 通信（AGENTS.md §4.1）；
    # 开发期 Vite 跑在 5173，生产同源部署时 cors 不生效也无所谓。
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": [o.strip() for o in origins.split(",") if o.strip()]}},
        supports_credentials=True,
    )


def _install_error_handlers(app: Flask) -> None:
    from app.common.errors import install_error_handlers

    install_error_handlers(app)


def _register_blueprints(app: Flask) -> None:
    """注册 API 蓝图。蓝图缺失时不阻断启动（P0 早期渐进接入）。"""
    try:
        from app.api import register_api
    except ImportError:  # pragma: no cover - 蓝图尚未就绪
        return
    register_api(app)


def _register_cli(app: Flask) -> None:
    from app.seeds import register_cli
    from app.services.provider_registry import register_cli as register_provider_cli

    register_cli(app)
    register_provider_cli(app)


def _warn_missing_credentials(app: Flask, logger) -> None:
    """生产模式缺凭据只警告不崩溃 —— 缺什么由 /api/capabilities 告诉前端。"""
    checks = {
        "SECRET_KEY": "会话与指纹盐",
        "FERNET_KEY": "API Key 落库加密",
        "LLM_API_KEY": "文本生成（PPT / 讲稿 / 测验）",
    }
    for key, why in checks.items():
        if not app.config.get(key):
            logger.warning("生产模式缺少 %s（%s），相关功能会在调用时报 40101", key, why)
