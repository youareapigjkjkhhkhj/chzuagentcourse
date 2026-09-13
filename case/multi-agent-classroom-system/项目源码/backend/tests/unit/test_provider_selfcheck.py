"""启动自检（F0-8）。

自检要回答的是「这台机器现在到底能不能干活」，而且**答案必须是真的**：
- 报 ok 却在生成课程时 40201 → 用户白跑一趟
- 报 error 但明明配好了 → 用户开始不信日志

所以这里既测「该报的报了」，也测「不该报的别乱报」。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# --- 不联网、不读库 ---


def test_registry_from_config_does_not_touch_the_database(app):
    """启动自检跑在「数据库可能还没迁移」的时刻，所以它不能读库。

    这条不是洁癖：flask db upgrade 之前 create_app() 必须先能成功，
    否则连迁移命令都跑不起来 —— 死锁。
    """
    from app.services.provider_registry import registry_from_config

    registry = registry_from_config(app.config)

    assert registry.names("llm")  # mock 一定在
    assert "mock" in registry.names("tts")


def test_self_check_never_calls_the_upstream(monkeypatch):
    """自检只判断配置齐不齐，不发请求。

    真探活要走网络，可能卡 30 秒 —— 放进启动路径等于让启动时长
    取决于别人家的服务。探活是设置页按钮的职责（P0-A5）。
    """
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("自检不应该发起网络请求")

    monkeypatch.setattr(httpx.Client, "send", explode)

    from app.services.provider_registry import self_check

    assert self_check(_registry())["ok"] is True


def test_self_check_survives_a_broken_registry():
    """自检自己崩掉比不自检还糟 —— 用户会以为整个应用起不来了。"""
    from app.providers.registry import ProviderRegistry
    from app.services.provider_registry import self_check

    report = self_check(ProviderRegistry())  # 一个什么都没注册的空表

    assert report["ok"] is False  # 有问题要说出来……
    assert [i for i in report["issues"] if i["level"] == "error"]  # ……而不是抛异常


# --- 判断本身 ---


def _registry(**config):
    """装配成生产的样子（离线替身一定在），但不读数据库。

    刻意不用 registry_from_config：那个会把 .env 里选中的服务商也建出来，
    于是「名字写错」被它悄悄补上了 —— 而这里正要看走错路时的表现。
    """
    from app.providers.registry import ProviderRegistry
    from app.services.provider_registry import _register_mocks

    registry = ProviderRegistry(config=config)
    _register_mocks(registry)
    return registry


def test_self_check_passes_with_nothing_configured():
    """裸装配（只有 mock）是「能跑」的 —— 离线链路必须自洽。

    P0 的验收前提是「无网络无密钥也能跑通全流程」（AGENTS.md §23），
    如果这种情况自检报 error，那这条验收条件本身就是假的。
    """
    from app.services.provider_registry import self_check

    report = self_check(_registry())

    assert report["ok"] is True
    assert report["active"]["llm"] == "mock"


def test_self_check_reports_missing_llm_key_as_an_error(app_factory):
    """选了服务商却没填 Key：这是 error，不是 warning。

    因为用户下一步就是去生成课程，而他一定会拿到 40201 ——
    与其到那时才发现，不如启动时就说清楚。
    """
    from app.services.provider_registry import self_check

    app_factory(seed=True, env={"LLM_PROVIDER": "deepseek"})

    report = self_check()

    assert report["ok"] is False
    issue = next(i for i in report["issues"] if i["code"] == "llm_not_configured")
    assert issue["level"] == "error"
    assert "deepseek" in issue["message"]
    # 缺什么要说具体，不能只说「配置有误」
    assert "API Key" in issue["message"]


def test_self_check_accepts_a_fully_configured_llm(app_factory):
    from app.services.provider_registry import self_check

    app_factory(
        seed=True,
        env={
            "LLM_PROVIDER": "deepseek",
            "LLM_API_KEY": "sk-test-not-a-real-key",
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_MODEL": "deepseek-chat",
        },
    )

    report = self_check()

    assert report["ok"] is True
    assert not [i for i in report["issues"] if i["level"] == "error"]


def test_self_check_flags_a_dangling_llm_provider():
    """指向一个不存在的服务商（写错了名字）要能认出来。"""
    from app.services.provider_registry import self_check

    report = self_check(_registry(LLM_PROVIDER="deseek"))  # 少一个 p

    assert report["ok"] is False
    issue = next(i for i in report["issues"] if i["code"] == "llm_unknown")
    assert "deseek" in issue["message"]
    # 光说错了没用，得把能选的名字列出来
    assert "mock" in issue["message"]


def test_self_check_warns_but_does_not_fail_when_speech_is_offline():
    """语音没配是 warning：P1 之前它就是该空着的，不该把自检弄成红的。"""
    from app.services.provider_registry import self_check

    report = self_check(_registry())

    codes = {issue["code"] for issue in report["issues"]}
    assert {"tts_offline", "asr_offline", "realtime_offline"} <= codes
    assert all(
        issue["level"] == "warning"
        for issue in report["issues"]
        if issue["code"].endswith("_offline")
    )
    assert report["ok"] is True


def test_self_check_names_the_mock_so_the_user_knows_why_there_is_no_sound():
    from app.services.provider_registry import self_check

    report = self_check(_registry())
    issue = next(i for i in report["issues"] if i["code"] == "tts_offline")

    assert "mock" in issue["message"]


#: 三个 VOLC_* 都填齐的样子。P0 的语音适配器只有骨架，所以这份配置
#: 证明的是「凭据齐了」，离「能出声」还差 P2 的实现 —— 下面几条测的正是这个差。
_SPEECH_ENV = {
    "VOLC_TTS_API_KEY": "k",
    "VOLC_TTS_ENDPOINT": "wss://example.invalid/tts",
    "VOLC_TTS_RESOURCE_ID": "volc.service_type.10029",
    "VOLC_TTS_SPEAKER": "zh_female_x",
    "VOLC_ASR_API_KEY": "k",
    "VOLC_ASR_ENDPOINT": "wss://example.invalid/asr",
    "VOLC_ASR_RESOURCE_ID": "volc.bigasr.sauc.duration",
    "VOLC_REALTIME_API_KEY": "k",
    "VOLC_REALTIME_ENDPOINT": "wss://example.invalid/realtime",
    "VOLC_REALTIME_MODEL": "1.2.1.1",
    "VOLC_REALTIME_SPEAKER": "zh_male_y",
}

#: 三种语音能力在自检里的展示名。
_SPEECH_LABELS = {"tts": "语音合成", "asr": "语音识别", "realtime": "实时语音"}


def test_self_check_reports_no_error_when_speech_credentials_are_complete():
    """凭据填齐了就不是配置错误 —— 哪怕代码还没接通。"""
    from app.services.provider_registry import registry_from_config, self_check

    report = self_check(registry_from_config(_SPEECH_ENV))

    assert not [i for i in report["issues"] if i["level"] == "error"]
    assert report["ok"] is True


def test_self_check_says_when_a_capability_is_not_implemented_yet():
    """凭据齐了 ≠ 现在能用：适配器还没实现时必须说出来。

    不吭声的后果是假绿灯 —— 用户看到三张全绿的卡片去上课，然后在第一次
    播放时吃 50201（未实现），而不是 40201（没配）。他接下来会去改 Key、
    换音色、重装依赖，唯独不会想到「这条路还没写」。

    这条路上现在没有真实实例了（P2 三个适配器都已落地），所以自带桩：
    机制留着是为了下一个能力（P6 的扩展音色之类）不再重演一次假绿灯。
    """
    from app.providers.asr.mock import MockASR
    from app.providers.tts.mock import MockRealtime, MockTTS
    from app.services.provider_registry import registry_from_config, self_check

    class PendingTTS(MockTTS):
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

    registry = registry_from_config(_SPEECH_ENV)
    registry.register(PendingTTS())
    registry.register(PendingASR())
    registry.register(PendingRealtime())

    report = self_check(registry)

    for kind, label in _SPEECH_LABELS.items():
        issue = next(i for i in report["issues"] if i["code"] == f"{kind}_pending")
        assert issue["level"] == "warning", "配置没写错，别升格成 error 把人赶去改配置"
        assert label in issue["message"]


def test_self_check_is_quiet_once_the_capability_really_works():
    """反向：适配器真的实现了就闭嘴（P2 之后这就是**默认状态**）。

    少了这条，上面那条可能只是因为「它总在报警」而通过 ——
    永远为真的警告和不报警一样没用。
    """
    from app.services.provider_registry import registry_from_config, self_check

    report = self_check(registry_from_config(_SPEECH_ENV))

    assert [i for i in report["issues"] if i["code"].endswith("_pending")] == []


def test_self_check_calls_a_half_configured_speech_provider_an_error():
    """钥匙给了但接入地址忘了填 —— 这是配置错误，不是「走离线」。

    两者的排查方向完全相反：一个去补字段，一个去确认「是不是本来就没打算配」。
    混成同一条 warning，用户会以为是正常状态，直到课堂演示时没有声音。
    """
    from app.services.provider_registry import registry_from_config, self_check

    report = self_check(registry_from_config({"VOLC_TTS_API_KEY": "k"}))  # 缺地址与音色

    issue = next(i for i in report["issues"] if i["code"] == "tts_not_configured")
    assert issue["level"] == "error"
    assert report["ok"] is False
    assert "接入地址" in issue["message"]
    # 没打算配的那两项仍然是 warning，不该被连带升格
    assert next(i for i in report["issues"] if i["code"] == "asr_offline")["level"] == "warning"


# --- 不泄密 ---


def test_self_check_never_leaks_the_key(app_factory):
    """自检结果要进日志、进 /api/health，绝不能带上 Key。"""
    from app.services.provider_registry import self_check

    secret = "sk-super-secret-value-12345"
    app_factory(
        seed=True,
        env={
            "LLM_PROVIDER": "deepseek",
            "LLM_API_KEY": secret,
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_MODEL": "deepseek-chat",
        },
    )

    report = self_check()

    assert secret not in repr(report)


def test_self_check_lists_every_kind_for_the_settings_page():
    """设置页要能列出「有哪些服务商可选」，全部四类都得在。"""
    from app.services.provider_registry import self_check

    report = self_check(_registry())

    assert set(report["providers"]) == {"llm", "tts", "asr", "realtime"}
    assert set(report["active"]) == {"llm", "tts", "asr", "realtime"}


# --- CLI ---


def test_providers_cli_runs_and_stays_gbk_safe(app):
    """`flask providers` 的输出必须能在 GBK 控制台上打出来。

    Windows 的默认代码页不是 UTF-8：一个 ✓ 就足以让整条命令以
    UnicodeEncodeError 收场。这类问题只有真跑一次才会暴露，
    所以这里连编码一起断言。
    """
    result = app.test_cli_runner().invoke(args=["providers"])

    assert result.exit_code == 0
    assert "[llm]" in result.output
    assert "未配置" in result.output
    result.output.encode("gbk")  # 打不出来就等于命令崩了


def test_providers_cli_explains_what_is_missing(app_factory):
    """命令的产物要能直接照着做：缺什么、什么时候会报错。"""
    application = app_factory(seed=True, env={"LLM_PROVIDER": "deepseek"})

    result = application.test_cli_runner().invoke(args=["providers"])

    assert result.exit_code == 0
    assert "40201" in result.output
    assert "API Key" in result.output
