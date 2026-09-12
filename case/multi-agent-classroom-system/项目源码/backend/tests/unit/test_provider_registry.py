"""Provider 注册表测试（F0-8 / P0-B3）。

注册表是业务代码接触厂商能力的唯一入口（P0 §6）：
业务层只写 `current_llm()` / `get_tts(name)`，永远不 import 厂商 SDK。
"""

from __future__ import annotations

import pytest

from app.extensions import db

pytestmark = pytest.mark.unit


def _registry():
    from app.services.provider_registry import get_registry

    return get_registry()


def _set_active(name: str) -> None:
    from app.models import KEY_ACTIVE_PROVIDER, SettingsKV

    row = db.session.get(SettingsKV, KEY_ACTIVE_PROVIDER)
    if row is None:
        row = SettingsKV(key=KEY_ACTIVE_PROVIDER)
        db.session.add(row)
    row.value = name
    db.session.commit()


# --- 注册与解析 ---


def test_registry_registers_mock_providers_out_of_the_box(app):
    """没有网络、没有密钥也必须能跑通全流程（AGENTS.md §23）。"""
    with app.app_context():
        registry = _registry()
        available = registry.available()

    assert "mock" in available["llm"]
    assert "mock" in available["tts"]
    assert "mock" in available["asr"]


def test_get_llm_by_name_returns_registered_instance(app):
    with app.app_context():
        provider = _registry().get_llm("mock")
        assert provider.name == "mock"
        assert provider.kind == "llm"


def test_get_llm_unknown_name_raises_not_found(app):
    from app.common.errors import NotFoundError

    with app.app_context(), pytest.raises(NotFoundError):
        _registry().get_llm("完全没有这家")


def test_get_llm_error_message_lists_what_is_available(app):
    from app.common.errors import NotFoundError

    with app.app_context(), pytest.raises(NotFoundError) as excinfo:
        _registry().get_llm("nope")

    assert "mock" in excinfo.value.message, "报错要告诉用户有哪些可选，而不是只说找不到"


def test_registry_exposes_all_three_kinds(app):
    with app.app_context():
        available = _registry().available()

    assert set(available.keys()) >= {"llm", "tts", "asr", "realtime"}


# --- current_* 解析规则 ---


def test_current_llm_follows_env_default(app_factory):
    """没在设置页改过时，用 .env 里的 LLM_PROVIDER。"""
    application = app_factory(env={"LLM_PROVIDER": "mock"})

    with application.app_context():
        assert _registry().current_llm().name == "mock"


def test_settings_override_beats_env(app):
    """设置页选的服务商优先于 .env 默认值。"""
    with app.app_context():
        _registry()  # 先建出来
        _set_active("mock")
        assert _registry().current_llm().name == "mock"


def test_current_llm_raises_40201_when_not_configured(app_factory):
    """选了服务商但没填 Key：必须报 40201 让人去配置，而不是偷偷降级（P0-B3）。"""
    from app.providers.base import ProviderNotConfiguredError

    application = app_factory(env={"LLM_PROVIDER": "deepseek", "LLM_API_KEY": ""})

    with application.app_context(), pytest.raises(ProviderNotConfiguredError) as excinfo:
        _registry().current_llm()

    assert excinfo.value.code == 40201
    assert excinfo.value.http_status == 400
    assert "deepseek" in excinfo.value.message


def test_current_llm_error_never_leaks_the_key(app_factory):
    """报错信息里不能出现 Key 的任何片段。

    这里故意配了 Key 但不配 base_url：仍然算「没配好」，必然报 40201，
    于是能稳定地检查那次报错的文本 —— 而不是碰运气等一个错误。
    """
    from app.providers.base import ProviderNotConfiguredError

    secret = "sk-9f2c4a1b7e8d4f6a0011223344556677"
    application = app_factory(
        env={"LLM_PROVIDER": "deepseek", "LLM_API_KEY": secret, "LLM_BASE_URL": ""}
    )

    with application.app_context(), pytest.raises(ProviderNotConfiguredError) as excinfo:
        _registry().current_llm()

    assert secret not in excinfo.value.message
    assert "9f2c" not in excinfo.value.message
    assert "deepseek" in excinfo.value.message, "得说清是哪一家没配好"


def test_current_tts_and_asr_resolve(app_factory):
    application = app_factory(env={"LLM_PROVIDER": "mock"})

    with application.app_context():
        registry = _registry()
        assert registry.current_tts().name == "mock"
        assert registry.current_asr().name == "mock"


def test_unknown_active_provider_reports_clearly(app):
    """settings_kv 里被手工改成一个不存在的名字，报错要能看懂。"""
    from app.common.errors import NotFoundError

    with app.app_context():
        _registry()
        _set_active("手改坏了的名字")
        with pytest.raises(NotFoundError):
            _registry().current_llm()


# --- 与数据库的联动 ---


def test_registry_picks_up_providers_from_database(app_factory):
    """providers 表里配置了 Key 的行会被构建成真实 Provider。"""
    from app.models import Provider

    application = app_factory(seed=True)

    with application.app_context():
        row = db.session.get(Provider, "deepseek")
        assert row is not None, "种子应当已经建好 DeepSeek 这一行"
        row.base_url = "https://llm.example.invalid/v1"
        row.default_model = "deepseek-chat"
        row.api_key = "sk-9f2c4a1b7e8d4f6a0011223344556677"
        db.session.commit()

        from app.services.provider_registry import refresh_registry

        registry = refresh_registry()
        provider = registry.get_llm("deepseek")

        assert provider.name == "deepseek"
        assert provider.configured is True
        assert provider.default_model == "deepseek-chat"
        # 明文只在 Provider 内部，不暴露成公开属性
        assert not hasattr(provider, "api_key")


def test_registry_is_per_app(app_factory):
    """两个 app 的注册表不能互相串（测试并行 / 多租户场景）。"""
    first = app_factory(env={"LLM_PROVIDER": "mock"})
    with first.app_context():
        registry_a = _registry()

    second = app_factory(env={"LLM_PROVIDER": "mock"})
    with second.app_context():
        registry_b = _registry()

    assert registry_a is not registry_b


def test_registry_survives_missing_tables(app_factory):
    """迁移还没跑时（表不存在）也不能崩 —— 只注册 mock，服务照常起来。"""
    application = app_factory(create_tables=False, env={"LLM_PROVIDER": "mock"})

    with application.app_context():
        available = _registry().available()

    assert "mock" in available["llm"]


def test_registry_reports_unconfigured_providers_honestly(app):
    """没 Key 的服务商要**列出来并标成未配置**，而不是藏起来。

    设置页得先看得见这一行，用户才知道去哪儿填 Key；
    藏起来的后果是「明明有这个选项，页面却像没这回事」。
    current_llm() 才是那道拦住调用的闸门。
    """
    with app.app_context():
        registry = _registry()
        listed = registry.available()["llm"]

        assert "deepseek" in listed, "内置服务商必须可见"
        assert listed["deepseek"]["configured"] is False
