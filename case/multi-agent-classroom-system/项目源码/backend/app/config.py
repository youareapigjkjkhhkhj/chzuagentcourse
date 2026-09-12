"""应用配置。

安全基线（AGENTS.md §4.1）：厂商凭据 / 端点 / 音色 ID 一律来自环境变量或 .env，
代码里不得出现任何字面量。没有 .env 也必须能启动（走 Mock Provider）。

注意：所有环境变量都在 create_app 时读取，不在 import 时冻结 ——
否则测试里 monkeypatch.setenv 会失效，多环境部署也会互相污染。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# --- 静态常量（与环境无关，不随 .env 变化）---

# 内网网段黑名单：自定义 base_url 命中即拒绝（AGENTS.md §4.1 防 SSRF）
SSRF_BLOCKED_NETWORKS = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

SSRF_BLOCKED_SCHEMES = ["file", "gopher", "ftp", "dict", "ldap", "data"]

# 上传白名单（AGENTS.md §4.1：类型白名单 + 魔数校验 + 大小上限）
ALLOWED_UPLOAD_EXTENSIONS = [
    ".pdf",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
]

ALLOWED_UPLOAD_MIMETYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "image/webp",
]


_dotenv_loaded = False


def _load_dotenv_once() -> None:
    """加载 backend/.env。测试可设 EDUAGENTX_DISABLE_DOTENV=1 跳过。

    在**第一次读配置时**加载，而不是 import 这个模块时 ——
    否则「测试不要读 .env」这个开关永远慢半拍：pytest 在 import 阶段
    就跑完了 app.config，而那会儿夹具还没机会设这个变量，开发机上的
    .env（含真实 Key）就漏进了整个测试进程。
    """
    # 模块级的一次性标记：测试要能把它重置回 False 来复现加载过程，
    # 所以用全局变量而不是闭包 / lru_cache
    global _dotenv_loaded  # noqa: PLW0603
    if _dotenv_loaded or os.environ.get("EDUAGENTX_DISABLE_DOTENV"):
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - 依赖缺失时不阻断启动
        return
    # override=False：真实环境变量优先于 .env，便于容器 / CI 覆盖
    load_dotenv(BACKEND_DIR / ".env", override=False)


def env_str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def default_database_uri(env_name: str) -> str:
    """显式配置优先；否则用 backend/data 下的 SQLite 文件（测试走内存库）。"""
    explicit = env_str("DATABASE_URL") or env_str("SQLALCHEMY_DATABASE_URI")
    if explicit:
        return explicit
    if env_name == "testing":
        return "sqlite://"
    return f"sqlite:///{(BACKEND_DIR / 'data' / 'eduagentx.db').as_posix()}"


def read_env_config(env_name: str) -> dict:
    """把当前进程环境读成一份配置字典。每次调用都重新读，不缓存。"""
    return {
        # --- 基础 ---
        "SECRET_KEY": env_str("SECRET_KEY", ""),
        "FERNET_KEY": env_str("FERNET_KEY", ""),
        # --- 数据库 ---
        "SQLALCHEMY_DATABASE_URI": default_database_uri(env_name),
        "DB_WRITE_SERIALIZE": env_bool("DB_WRITE_SERIALIZE", True),
        # --- 上传 ---
        "UPLOAD_DIR": env_str("UPLOAD_DIR") or str(BACKEND_DIR / "data" / "uploads"),
        "MAX_CONTENT_LENGTH": env_int("MAX_CONTENT_LENGTH", 20 * 1024 * 1024),
        # --- 文本 LLM（OpenAI 兼容）---
        "LLM_PROVIDER": env_str("LLM_PROVIDER", "deepseek"),
        "LLM_API_KEY": env_str("LLM_API_KEY", ""),
        "LLM_BASE_URL": env_str("LLM_BASE_URL", ""),
        "LLM_MODEL": env_str("LLM_MODEL", ""),
        "LLM_TIMEOUT": env_float("LLM_TIMEOUT", 120.0),
        "LLM_MAX_RETRIES": env_int("LLM_MAX_RETRIES", 2),
        # --- 课程生成管线 ---
        # 单页生成的超时（秒）。与 LLM_TIMEOUT 是两回事：后者是共享 HTTP 客户端的
        # 传输超时，前者是「这一页给你多少秒」（P1-F4）。并发写页时各自计时，
        # 慢的一页到点就放弃并标记失败，不让整门课等它。
        "GEN_PAGE_TIMEOUT": env_float("GEN_PAGE_TIMEOUT", 60.0),
        # 写页的并发路数（默认 3）。它是一次任务的平均速度与上游限流之间的平衡点：
        # 调大能更快跑完，但多数兼容实现在 5~10 路并发时开始返回 429。
        "GEN_CONCURRENCY": env_int("GEN_CONCURRENCY", 3),
        # 后台线程池大小（同时能跑几门课）。写页的并发数在上面，这里是任务级的
        # 并发：超出的任务会**被拒绝**（返回 False）而不是排队 —— 同一门课的两次
        # 生成同时跑会把页码与版本号写乱（见 common/tasks.py）。
        "GEN_WORKERS": env_int("GEN_WORKERS", 4),
        # SSE 心跳间隔（秒）。中间代理（Nginx 默认 60s）会掐掉长时间没有字节的
        # 连接，15s 是「比任何常见代理超时都短、又不至于刷屏」的取值（AGENTS §17）。
        "SSE_HEARTBEAT": env_float("SSE_HEARTBEAT", 15.0),
        # 敏感词表的**本地追加项**（逗号分隔）。内置表在 services/generation/filter.py，
        # 这里只放「这台机器/这所学校额外要拦的词」——不在代码里写死，
        # 是因为它随场景变化，而内置表要能保证「一份代码到哪都拦得住基本盘」。
        "SENSITIVE_WORDS": env_str("SENSITIVE_WORDS", ""),
        # --- 语音：大模型 TTS 2.0（双向流式 WS，二进制私有帧）---
        "VOLC_TTS_ENDPOINT": env_str("VOLC_TTS_ENDPOINT", ""),
        "VOLC_TTS_API_KEY": env_str("VOLC_TTS_API_KEY", ""),
        "VOLC_TTS_RESOURCE_ID": env_str("VOLC_TTS_RESOURCE_ID", ""),
        "VOLC_TTS_AUDIO_FORMAT": env_str("VOLC_TTS_AUDIO_FORMAT", "mp3"),
        "VOLC_TTS_SAMPLE_RATE": env_int("VOLC_TTS_SAMPLE_RATE", 24000),
        "VOLC_TTS_SPEECH_RATE": env_int("VOLC_TTS_SPEECH_RATE", 0),
        "VOLC_TTS_ENABLE_SUBTITLE": env_bool("VOLC_TTS_ENABLE_SUBTITLE", True),
        # 音色必须来自 TTS 2.0 池（_uranus_bigtts），与实时语音池不通用
        "VOLC_TTS_SPEAKER": env_str("VOLC_TTS_SPEAKER", ""),
        # 内置音色卡的厂商音色 ID（种子数据从这里取，代码里零字面量）
        "VOLC_TTS_VOICE_TEACHER": env_str("VOLC_TTS_VOICE_TEACHER", ""),
        "VOLC_TTS_VOICE_HISTORY": env_str("VOLC_TTS_VOICE_HISTORY", ""),
        "VOLC_TTS_VOICE_SCIENCE": env_str("VOLC_TTS_VOICE_SCIENCE", ""),
        # --- 语音：端到端实时语音（全双工，纯 JSON 文本帧 + Base64）---
        "VOLC_REALTIME_ENDPOINT": env_str("VOLC_REALTIME_ENDPOINT", ""),
        "VOLC_REALTIME_API_KEY": env_str("VOLC_REALTIME_API_KEY", ""),
        "VOLC_REALTIME_MODEL": env_str("VOLC_REALTIME_MODEL", ""),
        # 音色必须来自实时池（_jupiter_bigtts），中文只有 4 个
        "VOLC_REALTIME_SPEAKER": env_str("VOLC_REALTIME_SPEAKER", ""),
        "VOLC_REALTIME_QPM_LIMIT": env_int("VOLC_REALTIME_QPM_LIMIT", 60),
        # --- 语音：流式 ASR（二进制私有帧，与 TTS 编解码器不通用）---
        "VOLC_ASR_ENDPOINT": env_str("VOLC_ASR_ENDPOINT", ""),
        "VOLC_ASR_API_KEY": env_str("VOLC_ASR_API_KEY", ""),
        "VOLC_ASR_RESOURCE_ID": env_str("VOLC_ASR_RESOURCE_ID", ""),
        "VOLC_ASR_PACKET_MS": env_int("VOLC_ASR_PACKET_MS", 200),
        # --- 日志 ---
        "LOG_LEVEL": env_str("LOG_LEVEL", "INFO").upper(),
    }


class BaseConfig:
    """跨环境共享的配置。所有属性都可被环境变量覆盖（见 read_env_config）。"""

    ENV_NAME = "base"
    DEBUG = False
    TESTING = False

    JSON_SORT_KEYS = False
    PROPAGATE_EXCEPTIONS = None  # 交给 Flask 按 TESTING/DEBUG 决定

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict] = {
        # SQLite 单写者：由 common.dbw 串行化，连接本身放开线程检查
        "connect_args": {"check_same_thread": False, "timeout": 15},
        "pool_pre_ping": True,
    }

    ALLOWED_UPLOAD_EXTENSIONS: ClassVar[list[str]] = list(ALLOWED_UPLOAD_EXTENSIONS)
    ALLOWED_UPLOAD_MIMETYPES: ClassVar[list[str]] = list(ALLOWED_UPLOAD_MIMETYPES)
    SSRF_BLOCKED_NETWORKS: ClassVar[list[str]] = list(SSRF_BLOCKED_NETWORKS)
    SSRF_BLOCKED_SCHEMES: ClassVar[list[str]] = list(SSRF_BLOCKED_SCHEMES)
    # 校验自定义 base_url 时是否解析域名。IP 字面量不受此开关影响，永远会查黑名单。
    SSRF_RESOLVE_HOSTS = True

    # 生成参数边界（P0 §4.2：页数 8~20、同学数 0~5）
    MIN_PAGE_COUNT = 8
    MAX_PAGE_COUNT = 20
    MIN_CLASSMATE_COUNT = 0
    MAX_CLASSMATE_COUNT = 5

    @classmethod
    def load(cls) -> dict:
        """展开成 Flask 可直接 from_mapping 的字典：静态 → 父类 → 子类 → 环境变量。"""
        _load_dotenv_once()  # 读环境变量之前先把 .env 铺进 os.environ（只做一次）
        config: dict = {}
        for klass in reversed(cls.__mro__):
            config.update({k: v for k, v in vars(klass).items() if k.isupper()})
        config.update(read_env_config(cls.ENV_NAME))
        return config


class DevelopmentConfig(BaseConfig):
    ENV_NAME = "development"
    DEBUG = env_bool("DEBUG", True)


class TestingConfig(BaseConfig):
    ENV_NAME = "testing"
    TESTING = True
    DEBUG = False
    # 测试不联网（AGENTS.md §23）。关掉域名解析，但内网 IP 字面量照样会被拒 ——
    # 那一条判定不需要 DNS，所以 SSRF 的契约测试仍然测的是真代码。
    SSRF_RESOLVE_HOSTS = False


class ProductionConfig(BaseConfig):
    ENV_NAME = "production"
    DEBUG = False
    TESTING = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "dev": DevelopmentConfig,
    "testing": TestingConfig,
    "test": TestingConfig,
    "production": ProductionConfig,
    "prod": ProductionConfig,
}


def resolve_config(name: str | None = None):
    """按名字取配置类，未知名字回落到 development。"""
    key = (name or os.environ.get("APP_ENV") or "development").strip().lower()
    return CONFIG_MAP.get(key, DevelopmentConfig)


# 注：这里曾有一个 describe_capabilities()，只按 .env 判断能力可用性。
# 它会有第二个事实来源 —— 设置页存进 providers 表的凭据它看不见。
# 现在统一由 services/provider_registry.capabilities() 回答（基于注册表）。
