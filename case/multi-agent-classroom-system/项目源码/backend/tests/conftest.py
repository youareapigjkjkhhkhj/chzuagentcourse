"""pytest 全局夹具。

原则（AGENTS.md §23）：外部能力一律 Mock，无网络、无密钥也必须能跑通全流程。
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# 让 `app` 包可被直接 import（tests/ 在 backend/ 下，backend/ 不在 sys.path）
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ★ 必须在 import 任何 app 模块之前设上。
# 开发机上的 backend/.env 里是真凭据；一旦它漏进测试进程，
# 「未配置」这类断言就会随开发者本地的配置时红时绿，
# 而且测试可能真的去连上游（AGENTS.md §23 要求无网络、无密钥也能全绿）。
# app/config.py 也做了延迟加载，两道锁各自独立生效。
os.environ.setdefault("EDUAGENTX_DISABLE_DOTENV", "1")

# 一次性生成的 Fernet 密钥（32 字节 urlsafe base64），仅测试用
TEST_FERNET_KEY = "dGVzdC1rZXktZm9yLWVkdWFnZW50eC1vbmx5LTAwMDA="


def base_env(database_uri: str) -> dict:
    """测试环境基线。每次调用都带一个全新的库文件，测试之间互不污染。"""
    return {
        "EDUAGENTX_DISABLE_DOTENV": "1",
        "TESTING": "True",
        "SQLALCHEMY_DATABASE_URI": database_uri,
        "FERNET_KEY": TEST_FERNET_KEY,
        "SECRET_KEY": "test-secret-key-not-for-production",
        "DB_WRITE_SERIALIZE": "True",
        "LLM_API_KEY": "",
    }


def temp_database_uri() -> str:
    return f"sqlite:///{(Path(tempfile.mkdtemp(prefix='eduagentx-')) / 'test.db').as_posix()}"


@pytest.fixture()
def app_factory(monkeypatch):
    """按需创建应用。env 在建 app 之前注入 —— 配置是启动时快照，这是真实语义。

    默认只建表，不灌种子 —— 夹具做的每件事都该是看得见的。
    需要「一台刚部署好的机器」（内置服务商 / 老师 / 同学 / 示例课程）
    就显式传 seed=True，等价于生产上的 `flask db upgrade && flask seed`。
    想测未迁移状态传 create_tables=False。

    用法：
        app = app_factory(env={"VOLC_TTS_VOICE_TEACHER": "x"}, unset=["LLM_API_KEY"])
        app = app_factory(seed=True)
    """
    stack: list[tuple] = []

    def _make(
        env: dict | None = None,
        unset: tuple[str, ...] = (),
        create_tables: bool = True,
        database_uri: str | None = None,
        seed: bool = False,
    ):
        values = base_env(database_uri or temp_database_uri())
        values.update({k: str(v) for k, v in (env or {}).items()})
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        for key in unset:
            monkeypatch.delenv(key, raising=False)

        from app import create_app

        application = create_app("testing")
        context = application.app_context()
        context.push()

        from app.extensions import db

        if create_tables:
            db.create_all()
            if seed:
                from app.seeds import run_seed

                run_seed()
        stack.append((application, context, db))
        return application

    yield _make

    for _application, context, db in reversed(stack):
        db.session.remove()
        db.drop_all()
        context.pop()


@pytest.fixture()
def app(app_factory):
    """一个全新的 app + 数据库。"""
    return app_factory()


@pytest.fixture()
def client(app):
    """Flask 测试客户端。"""
    return app.test_client()


@pytest.fixture()
def unique_name() -> str:
    return f"n{uuid.uuid4().hex[:8]}"
