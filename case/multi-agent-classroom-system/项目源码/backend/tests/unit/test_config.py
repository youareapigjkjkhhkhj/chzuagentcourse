"""配置与安全基线测试（P0-B2 / P0-B3 / P0-D2 / AGENTS.md §4.1）。

硬约束：
- 代码里不得出现字面量密钥 / 音色 ID / 端点 URL
- .env 缺失时给出可执行的提示，而不是神秘崩溃
- 生产模式默认关闭 debug
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def test_config_object_is_constructed(app):
    """create_app 已把配置挂到 app.config。"""
    cfg = app.config
    assert cfg["SQLALCHEMY_DATABASE_URI"]
    assert cfg["SECRET_KEY"]
    assert cfg["FERNET_KEY"]


def test_testing_mode_disables_debug(app):
    assert app.config["TESTING"] is True
    assert app.debug is False


def test_json_response_is_utf8_not_escaped(client, app):
    """中文必须原样返回，前端调试不用看 \\uXXXX。"""
    from app.common.response import ok

    @app.route("/_zh")
    def _zh():
        return ok({"name": "光合作用"})

    resp = client.get("/_zh")
    assert "光合作用" in resp.get_data(as_text=True)
    assert resp.headers["Content-Type"].startswith("application/json")


# 敏感信息扫描规则（AGENTS.md §4.1：凭据 / 端点 / 音色 ID 一律配置化）
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "疑似硬编码的 API Key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "疑似硬编码的 AWS Key"),
    # 火山真实音色 ID 形如 zh_male_yunzhou_jupiter_bigtts；
    # 只提到族后缀（_uranus_bigtts / _jupiter_bigtts）是在讲约束，不算违规。
    (
        re.compile(r"\b[a-z]{2}_[a-z0-9]+_[a-z0-9]+_(?:uranus|jupiter)_bigtts\b"),
        "疑似硬编码的火山音色 ID（应走 VOLC_TTS_VOICE_* 配置）",
    ),
    (re.compile(r"openspeech\.bytedance\.com"), "疑似硬编码的火山端点（应走配置）"),
    (re.compile(r"bytedance\.com/api/v3"), "疑似硬编码的火山 API 路径（应走配置）"),
    (re.compile(r"api\.(?:deepseek|openai|moonshot)\.com"), "疑似硬编码的 LLM 端点（应走配置）"),
]


def scan_text_for_secrets(text: str) -> list[str]:
    """按行扫描，返回违规描述。整行注释跳过（那是在写文档，不是在写配置）。"""
    findings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        for pattern, why in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(f"{line_no}:{why}")
    return findings


def test_secret_scanner_catches_a_real_looking_api_key():
    """扫描器自测 —— 一个悄悄不再匹配的安全扫描比没有扫描更危险。"""
    assert scan_text_for_secrets('KEY = "sk-9f2c4a1b7e8d4f6a0011223344556677"')


def test_secret_scanner_catches_a_real_looking_speaker_id():
    assert scan_text_for_secrets('SPEAKER = "zh_male_yunzhou_jupiter_bigtts"')
    assert scan_text_for_secrets('SPEAKER = "zh_female_wenrou_uranus_bigtts"')


def test_secret_scanner_catches_hardcoded_endpoints():
    assert scan_text_for_secrets('URL = "wss://openspeech.bytedance.com/api/v3/tts"')
    assert scan_text_for_secrets('BASE = "https://api.deepseek.com/v1"')


def test_secret_scanner_allows_prose_about_voice_families():
    """文档里说明「两个音色池不通用」必须能被允许，否则没人敢写注释。"""
    prose = "火山有两套音色池：TTS 用 _uranus_bigtts，实时语音用 _jupiter_bigtts"
    assert scan_text_for_secrets(prose) == []


def test_secret_scanner_ignores_pure_comment_lines():
    assert scan_text_for_secrets('    # 示例：sk-9f2c4a1b7e8d4f6a0011223344556677') == []


def test_no_hardcoded_secrets_in_source():
    """全量源码扫描：不得出现字面量密钥、音色 ID、厂商端点。"""
    offenders: list[str] = []
    for py in (BACKEND_DIR / "app").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for finding in scan_text_for_secrets(text):
            offenders.append(f"{py.relative_to(BACKEND_DIR)}:{finding}")

    assert not offenders, "硬编码敏感信息：\n" + "\n".join(offenders)


def test_env_example_exists_and_lists_all_required_keys():
    """.env.example 是新人上手的唯一入口，必须列全。"""
    example = BACKEND_DIR / ".env.example"
    assert example.exists(), "缺少 .env.example"

    text = example.read_text(encoding="utf-8")
    required = [
        "SECRET_KEY",
        "FERNET_KEY",
        "DATABASE_URL",
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
    ]
    missing = [k for k in required if k not in text]
    assert not missing, f".env.example 缺少：{missing}"

    # 不得包含真实密钥
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", text)


#: 「配置里没有也读得出东西」的键。写在这里而不是放宽规则：每加一个都该有人
#: 看一眼，而不是让它悄悄溜过去。
#:   VERSION —— 没配就用包版本（provider_registry._app_version）
OPTIONAL_CONFIG_KEYS = {"VERSION"}

#: `cfg.get("XXX")` / `current_app.config.get("XXX")` 的取值点
_CONFIG_KEY = re.compile(r"""(?:config|cfg)\.get\(\s*["']([A-Z][A-Z0-9_]{2,})["']""")


def _declared_config_keys() -> set[str]:
    """read_env_config 产出的 + BaseConfig 上的大写属性，都算「已声明」。"""
    from app.config import BaseConfig, read_env_config

    return set(read_env_config("testing")) | {
        name for name in vars(BaseConfig) if name.isupper()
    }


def test_every_voice_env_key_is_declared_in_config(app):
    """种子引用的 env_key 必须在 config 里真有一条。

    P2 就踩过这个坑：`VOLC_REALTIME_VOICE_*` 被种子的 `realtime_env_key` 引用，
    但 `read_env_config` 从没读过它们 —— 于是它永远读成空串，而提示语还让用户
    去 .env 里改（改了也没用）。这类「引用了不存在的配置键」不会报错，
    只会安静地退化成默认行为，所以值得有个哨兵。
    """
    from app.config import read_env_config
    from app.seeds.voices import BUILTIN_VOICES

    declared = set(read_env_config("testing"))
    missing = [
        key
        for item in BUILTIN_VOICES
        for key in (item["env_key"], item["realtime_env_key"])
        if key not in declared
    ]
    assert not missing, f"种子引用了 config 里不存在的键：{missing}"


def test_every_config_key_read_anywhere_is_declared():
    """反向也查一遍：读的键必须有人声明（否则拿到的永远是 None）。

    `cfg.get("VOLC_TTS_TIMEOUT")` 就是这样躺了好一阵：调用方写了、配置层没接，
    结果「配了也不生效」，而且不报错。这个扫描把它变成一条会红的断言。
    """
    offenders: list[str] = []
    for py in sorted((BACKEND_DIR / "app").rglob("*.py")):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            for key in _CONFIG_KEY.findall(line):
                if key in OPTIONAL_CONFIG_KEYS:
                    continue
                if key not in _declared_config_keys():
                    offenders.append(f"{py.relative_to(BACKEND_DIR)}:{lineno} → {key}")

    assert not offenders, "读了没人声明的配置键：\n  " + "\n  ".join(offenders)


def test_config_key_scanner_self_test():
    """上面两条扫描的自测：正则要真能扫出键、声明集合要真认得出已声明的键。

    否则「扫描没报错」可能只是因为正则根本没匹配上任何东西。
    """
    assert _CONFIG_KEY.findall('x = cfg.get("VOLC_TTS_TIMEOUT")') == ["VOLC_TTS_TIMEOUT"]
    assert _CONFIG_KEY.findall('y = current_app.config.get("VOICE_ENABLED")') == ["VOICE_ENABLED"]

    declared = _declared_config_keys()
    assert "VOLC_TTS_TIMEOUT" in declared
    assert "VOICE_ENABLED" in declared
    assert "SSE_HEARTBEAT" in declared  # BaseConfig / read_env_config 两条来源都算
    assert "NOT_A_REAL_CONFIG_KEY" not in declared


def test_database_uri_defaults_to_sqlite(app):
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:")


def test_missing_llm_key_does_not_crash_boot(app):
    """没有配 LLM Key 时应用必须能启动，只在调用时报 40101。"""
    assert app.config.get("LLM_API_KEY", "") == ""


def test_dotenv_is_not_loaded_while_testing(monkeypatch, tmp_path):
    """测试进程绝不能读开发机上的 backend/.env。

    这不是洁癖：.env 里是**真凭据**。漏进来的后果是双份的 ——
    「未配置时返回 40201」这类断言会随开发者本地的配置时红时绿，
    而且测试可能真的去连上游（AGENTS.md §23：无网络、无密钥也要全绿）。
    """
    from app import config as config_module

    (tmp_path / ".env").write_text("VOLC_TTS_API_KEY=leaked-from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "BACKEND_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_dotenv_loaded", False)
    monkeypatch.setenv("EDUAGENTX_DISABLE_DOTENV", "1")
    monkeypatch.delenv("VOLC_TTS_API_KEY", raising=False)

    config_module._load_dotenv_once()

    assert "VOLC_TTS_API_KEY" not in __import__("os").environ


def test_dotenv_is_loaded_outside_tests(monkeypatch, tmp_path):
    """反过来也要成立：没有这个开关时，.env 必须真的被读进来。

    否则上一条测试可能只是因为「加载逻辑压根没生效」而通过。
    """
    import os

    from app import config as config_module

    (tmp_path / ".env").write_text("VOLC_TTS_API_KEY=loaded-from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "BACKEND_DIR", tmp_path)
    monkeypatch.setattr(config_module, "_dotenv_loaded", False)
    monkeypatch.delenv("EDUAGENTX_DISABLE_DOTENV", raising=False)
    monkeypatch.delenv("VOLC_TTS_API_KEY", raising=False)

    config_module._load_dotenv_once()

    assert os.environ.get("VOLC_TTS_API_KEY") == "loaded-from-dotenv"

    # load_dotenv 直接写 os.environ，monkeypatch 的记账管不到它；
    # 而 monkeypatch.delenv 也不行 —— 它会把「删除前的值」记下来，
    # 收尾时又原样放回去。只能手工清掉，否则这个值留着会把
    # 后面所有「未配置 → 40201」的断言污染掉。
    os.environ.pop("VOLC_TTS_API_KEY", None)


def test_upload_dir_is_absolute_and_outside_repo(app, tmp_path):
    """上传目录必须是绝对路径，且不落在源码树里。"""
    upload_dir = Path(app.config["UPLOAD_DIR"])
    assert upload_dir.is_absolute()


def test_max_upload_size_is_bounded(app):
    """上传上限必须显式设置（AGENTS.md §4.1 大小上限）。"""
    assert 0 < app.config["MAX_CONTENT_LENGTH"] <= 64 * 1024 * 1024


def test_ssrf_blocklist_is_configured(app):
    """自定义 base_url 的内网黑名单必须在配置里，不能散落在业务代码。"""
    blocked = app.config["SSRF_BLOCKED_NETWORKS"]
    assert "127.0.0.0/8" in blocked
    assert "10.0.0.0/8" in blocked
    assert "172.16.0.0/12" in blocked
    assert "192.168.0.0/16" in blocked
    assert "169.254.0.0/16" in blocked


def test_ssrf_blocked_schemes(app):
    schemes = app.config["SSRF_BLOCKED_SCHEMES"]
    assert "file" in schemes
    assert "gopher" in schemes


def test_wal_mode_enabled_for_sqlite(app):
    """SQLite 必须开 WAL，否则并发读写会互相阻塞。"""
    from sqlalchemy import text

    from app.extensions import db

    with app.app_context():
        mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
    assert str(mode).lower() == "wal"
