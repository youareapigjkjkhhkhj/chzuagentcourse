"""pytest 全局夹具。

原则（AGENTS.md §23）：外部能力一律 Mock，无网络、无密钥也必须能跑通全流程。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

# 让 `app` 包可被直接 import（tests/ 在 backend/ 下，backend/ 不在 sys.path）
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 下面的桩 Provider 是现成 Mock 改一个标志位来的，所以放在 sys.path 就位之后再 import。
from app.providers.asr.mock import MockASR  # noqa: E402
from app.providers.tts.mock import MockRealtime, MockTTS  # noqa: E402

# ★ 必须在 import 任何 app 模块之前设上。
# 开发机上的 backend/.env 里是真凭据；一旦它漏进测试进程，
# 「未配置」这类断言就会随开发者本地的配置时红时绿，
# 而且测试可能真的去连上游（AGENTS.md §23 要求无网络、无密钥也能全绿）。
# app/config.py 也做了延迟加载，两道锁各自独立生效。
os.environ.setdefault("EDUAGENTX_DISABLE_DOTENV", "1")

# 一次性生成的 Fernet 密钥（32 字节 urlsafe base64），仅测试用
TEST_FERNET_KEY = "dGVzdC1rZXktZm9yLWVkdWFnZW50eC1vbmx5LTAwMDA="


def base_env(database_uri: str, audio_dir: str = "", material_dir: str = "") -> dict:
    """测试环境基线。每次调用都带一个全新的库文件，测试之间互不污染。"""
    # 音频/材料/导出目录默认取库文件旁边：一次合成会留下 mp3、一次上传会留下原文件、
    # 一次导出会留下 pptx，而默认值指向的是 backend/data/...（开发机上那正是用户的
    # 音频、材料与产物所在的地方）。测试跑一遍不该往那儿写东西 —— 也不该读到上一次
    # 留下的文件而变成「缓存命中」。
    near_db = (
        Path()
        if ":memory:" in database_uri
        else Path(database_uri.removeprefix("sqlite:///")).parent
    )
    default_audio = "" if ":memory:" in database_uri else str(near_db / "audio")
    default_materials = "" if ":memory:" in database_uri else str(near_db / "materials")
    default_exports = "" if ":memory:" in database_uri else str(near_db / "exports")
    return {
        "EDUAGENTX_DISABLE_DOTENV": "1",
        "TESTING": "True",
        "SQLALCHEMY_DATABASE_URI": database_uri,
        "FERNET_KEY": TEST_FERNET_KEY,
        "SECRET_KEY": "test-secret-key-not-for-production",
        "DB_WRITE_SERIALIZE": "True",
        "LLM_API_KEY": "",
        "AUDIO_DIR": audio_dir or default_audio,
        "MATERIAL_DIR": material_dir or default_materials,
        "EXPORT_DIR": default_exports,
    }


#: 这次会话建出来的临时库目录，跑完由 `_clean_temp_databases` 收走。
_TEMP_DATABASES: list[Path] = []


def temp_database_uri() -> str:
    directory = Path(tempfile.mkdtemp(prefix="eduagentx-"))
    _TEMP_DATABASES.append(directory)
    return f"sqlite:///{(directory / 'test.db').as_posix()}"


@pytest.fixture(scope="session", autouse=True)
def _clean_temp_databases():
    """跑完把这一轮建的临时库目录删掉。

    `temp_database_uri()` 每调一次建一个目录（`app_factory()` 默认就会调），
    之前谁都不删 —— 一个 775 条用例的套件跑一遍，系统临时目录里就多出几百个
    `eduagentx-xxxx/test.db`。放在会话末尾删是因为 Windows 上删不掉还开着的
    sqlite 文件（`-wal`/`-shm` 也在同一个目录里）。
    """
    yield
    for directory in _TEMP_DATABASES:
        for _attempt in range(3):
            shutil.rmtree(directory, ignore_errors=True)
            if not directory.exists():
                break
            time.sleep(0.05)  # 句柄刚松开时 Windows 还会拒一小会儿
    _TEMP_DATABASES.clear()


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
        # `session.remove()` 只是把连接还回池子，句柄还开着；不 dispose 的话
        # 会话末尾删临时目录时 Windows 会拒绝（POSIX 上删得掉，所以这件事
        # 只在 Windows 上现形 —— 而这里就是 Windows）。
        db.engine.dispose()
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


# --- 「实现还没写」的语音桩（P0 的 *_pending 提示要一直有人验）---


class PendingTTS(MockTTS):
    """占住 volc_tts 的名字，但声明自己还没实现。

    P2 之前这三个位置本来就是空壳；现在它们真能用了，
    于是「凭据齐了但代码没写」这条路上就没有实例了 —— 机制本身还在
    （设置页要能显示「已配置，但还不可用」），所以测试自带一个桩来走它。
    """

    implemented = False

    def __init__(self, name: str = "volc_tts") -> None:
        super().__init__(name)


class PendingASR(MockASR):
    implemented = False

    def __init__(self, name: str = "volc_asr") -> None:
        super().__init__(name)


class PendingRealtime(MockRealtime):
    implemented = False

    def __init__(self, name: str = "volc_realtime") -> None:
        super().__init__(name)


@pytest.fixture()
def stub_speech():
    """把语音三件套换成上面那三个桩（覆盖式注册，名字不变）。"""

    def _install() -> None:
        from app.services.provider_registry import get_registry

        registry = get_registry()
        registry.register(PendingTTS())
        registry.register(PendingASR())
        registry.register(PendingRealtime())

    return _install
