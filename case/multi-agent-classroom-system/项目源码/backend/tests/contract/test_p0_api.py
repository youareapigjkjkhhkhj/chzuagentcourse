"""P0 接口契约测试（P0-B2）。

验收原文：**「契约测试 pytest tests/contract/test_p0_api.py 全绿，覆盖 §4 全部端点
（含 4xx/5xx 分支）」**。所以这个文件有两类断言：

1. **形状**：信封永远是 `{code, message, data, requestId}` 四键，字段名是 camelCase
   （P0-B1）。前端只写一套解包逻辑，靠的就是这一条。
2. **事实**：说「已配置」就得真能用，说「缺少 API Key」就得真缺 —— 40201 的
   `data` 要能直接告诉用户去哪儿补（P0-B3）。

不发任何真实网络请求：探活路径用打桩的 Provider 适配器，
其余分支（未配置、参数非法、找不到）本来就不该联网。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.contract

ENVELOPE_KEYS = {"code", "message", "data", "requestId"}


# --- 工具 ---


def envelope(response, expect_code: int | None = None) -> dict:
    """校验信封形状并返回 body。每个用例都过一遍，形状不会在某个分支上悄悄跑偏。"""
    body = response.get_json()
    assert body is not None, "响应不是 JSON"
    assert set(body) == ENVELOPE_KEYS, f"信封键不对：{sorted(body)}"
    assert isinstance(body["message"], str)
    assert isinstance(body["requestId"], str) and body["requestId"], "requestId 不能为空"
    if expect_code is not None:
        assert body["code"] == expect_code, body.get("message")
    return body


def data_of(response, expect_code: int = 0) -> dict:
    return envelope(response, expect_code)["data"]


def make_probe(monkeypatch, result):
    """把 LLM 适配器的 test() 换成假结果，避免契约测试真的联网。"""
    from app.providers.llm.openai_compatible import OpenAICompatibleLLM

    calls: list[str] = []

    def fake_test(self):
        calls.append(self.name)
        return result

    monkeypatch.setattr(OpenAICompatibleLLM, "test", fake_test)
    return calls


def configured_llm(app_factory):
    """一个「Key 已经填好」的 DeepSeek：后续探活类用例的前提。"""
    return app_factory(
        seed=True,
        env={
            "LLM_PROVIDER": "deepseek",
            "LLM_API_KEY": "sk-contract-test-key",
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_MODEL": "deepseek-chat",
        },
    )


#: 火山语音三件套凭据齐全的样子。P0 只交付骨架，所以这份配置下
#: 三个能力都仍然是「不可用」—— 这正是下面几条要测的。
SPEECH_ENV = {
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


# --- 信封（P0-B1）---


def test_request_id_is_echoed_back(client):
    """上游带了 X-Request-Id 就用它 —— 前后端能对着同一个 id 查日志。"""
    response = client.get("/api/health", headers={"X-Request-Id": "trace-me-123"})
    assert envelope(response)["requestId"] == "trace-me-123"


def test_unknown_route_still_uses_the_envelope(client):
    """404 也要是信封：前端不该为「路由写错了」单独写一套解析。"""
    response = client.get("/api/definitely-not-a-route")

    body = envelope(response, 40401)
    assert response.status_code == 404
    assert body["message"]


def test_method_not_allowed_uses_the_envelope(client):
    response = client.delete("/api/health")

    body = envelope(response, 40501)
    assert response.status_code == 405
    assert body["message"]


# --- 健康与能力（§4.1）---


def test_health_reports_ok_and_provider_readiness(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().get("/api/health")

    data = data_of(response)
    assert response.status_code == 200
    assert data["status"] == "ok"
    assert data["version"]
    assert data["db"] in {"ok", "ready"}
    assert set(data["providers"]) == {"llm", "tts", "asr", "realtime"}
    # 没配 Key 的能力要诚实说「未配置」，不能假装可用
    assert data["providers"]["tts"] == "unconfigured"


def test_health_never_leaks_the_key(app_factory):
    response = configured_llm(app_factory).test_client().get("/api/health")

    assert "sk-contract-test-key" not in response.get_data(as_text=True)


def test_health_points_at_the_configured_llm(app_factory):
    """P0-A6：启用了谁，/api/health 的 llm 就得指向谁。"""
    data = data_of(configured_llm(app_factory).test_client().get("/api/health"))

    assert data["providers"]["llm"] == "ready"
    assert data["llm"]["provider"] == "deepseek"
    assert data["llm"]["model"] == "deepseek-chat"


def test_health_is_not_ready_for_a_stub_adapter_even_with_real_credentials(app_factory):
    """P0 的语音适配器只有骨架：凭据齐了也必须报 unconfigured。

    这是本阶段最容易被真实 .env 骗过去的一格 —— 里面放的是真 Key，
    卡片会显示「已配置」，可调用时抛的是 50201（还没实现），不是 40201（没配）。
    报 ready 就等于把「P2 才交付」伪装成「已经好了」，
    而 P0 的验收要求恰好是这三个能力为 unconfigured。
    """
    app = app_factory(seed=True, env=SPEECH_ENV)

    data = data_of(app.test_client().get("/api/health"))

    assert data["providers"]["tts"] == "unconfigured"
    assert data["providers"]["asr"] == "unconfigured"
    assert data["providers"]["realtime"] == "unconfigured"
    # 但要能说清为什么 —— 否则运维只能看到一个没有理由的红灯
    codes = {issue["code"] for issue in data["issues"]}
    assert {"tts_pending", "asr_pending", "realtime_pending"} <= codes


def test_capabilities_keep_a_stub_adapter_off(app_factory):
    """前端据此置灰入口：不能点开一个点了必然报错的按钮。

    与 mock 的区别（§4.1：available 与 offline 是两个问题）：
    这里 offline 也是 False —— 它不是「离线替身顶着」，而是「谁都没顶」。
    """
    app = app_factory(seed=True, env=SPEECH_ENV)

    caps = data_of(app.test_client().get("/api/capabilities"))["capabilities"]

    for kind in ("tts", "asr", "realtime"):
        assert caps[kind]["available"] is False, kind
        assert caps[kind]["offline"] is False, kind
        assert caps[kind]["reason"], f"{kind} 不可用时必须说清为什么"


def test_capabilities_lists_four_kinds_with_availability(app_factory):
    """前端靠它决定「哪个入口该置灰」（§4.1）。"""
    app = app_factory(seed=True)

    data = data_of(app.test_client().get("/api/capabilities"))

    assert set(data["capabilities"]) >= {"llm", "tts", "asr", "realtime"}
    llm = data["capabilities"]["llm"]
    assert set(llm) >= {"available", "provider"}
    assert llm["available"] is False  # 没配 Key
    assert llm["reason"], "不可用时必须说清为什么，否则前端只能干置灰"


def test_capabilities_reports_generation_limits(app):
    data = data_of(app.test_client().get("/api/capabilities"))

    assert data["generation"]["minPageCount"] == 8
    assert data["generation"]["maxPageCount"] == 20
    assert data["generation"]["minClassmateCount"] == 0
    assert data["generation"]["maxClassmateCount"] == 5


# --- 服务商设置（§4.2）---


def test_providers_list_has_five_cards(app_factory):
    """P0-A3：原型上就是 5 张卡（DeepSeek / OpenAI / Qwen / Kimi / 自定义）。"""
    app = app_factory(seed=True)

    data = data_of(app.test_client().get("/api/settings/providers"))

    assert data["total"] == 5
    ids = [item["id"] for item in data["items"]]
    assert ids == ["deepseek", "openai", "qwen", "kimi", "custom"]


def test_provider_card_carries_what_the_ui_needs(app_factory):
    app = app_factory(seed=True)

    items = data_of(app.test_client().get("/api/settings/providers"))["items"]
    card = next(item for item in items if item["id"] == "deepseek")

    for key in ("id", "name", "kind", "configured", "enabled", "maskedKey", "latencyMs"):
        assert key in card, f"卡片缺少 {key}"
    assert card["configured"] is False
    assert card["enabled"] is True  # 种子默认启用 DeepSeek
    assert card["maskedKey"] == ""  # 没配就是空，不编造掩码


def test_card_is_configured_when_the_env_supplies_the_key(app_factory):
    """凭据来自 .env 时，卡片也必须显示「已配置」。

    部署方把 Key 写在 .env 里是正常用法（.env.example 就是这么写的）。
    如果卡片只认数据库那一行，就会出现「探活打勾、卡片却说未配置」——
    用户接着会去填一遍本来就已经配好的 Key。
    """
    app = app_factory(
        seed=True,
        env={
            "LLM_PROVIDER": "deepseek",
            "LLM_API_KEY": "sk-from-env-abcdefgh",
            "LLM_BASE_URL": "https://llm.example.invalid/v1",
            "LLM_MODEL": "deepseek-chat",
        },
    )

    items = data_of(app.test_client().get("/api/settings/providers"))["items"]
    card = next(item for item in items if item["id"] == "deepseek")

    assert card["configured"] is True
    # 但 .env 里的 Key 不能回显成掩码 —— 我们从没把它写进库，
    # 掩码是给「库里那把」看的
    assert card["maskedKey"] == ""


def test_card_says_which_field_is_still_missing(app_factory):
    """只填了 Key 的行仍是「未配置」，但要说清还差哪一栏。

    模型名与接入地址在设置页是可改的，所以在代码里给不了默认值
    （AGENTS.md §4.1 不许写死厂商端点）—— 用户只填 Key 是常见操作，
    卡片必须能把「还缺接入地址、模型名」说出来。
    """
    app = app_factory(seed=True)
    client = app.test_client()
    client.put("/api/settings/providers/openai", json={"apiKey": "sk-only-key-0001"})

    items = data_of(client.get("/api/settings/providers"))["items"]
    card = next(item for item in items if item["id"] == "openai")

    assert card["configured"] is False
    assert card["missing"], "卡片要说清缺什么，否则用户只能猜"
    assert card["maskedKey"].endswith("0001")


def test_card_distinguishes_credentials_from_a_missing_adapter(app_factory):
    """`configured`（凭据齐备）与 `available`（现在能用）是两件事。

    加一行没有适配器的服务商（P2 之前所有非内置语音服务商都是这样），
    卡片要能说清「凭据填了，但这条路还没有代码去走」——
    否则前端只能把它显示成一个含糊的「未配置」，用户会一直以为是自己没填对。
    """
    from app.extensions import db
    from app.models import Provider

    app = app_factory(seed=True)
    with app.app_context():
        row = Provider(id="azure_tts", name="Azure 语音", kind="tts")
        row.api_key = "azure-secret-value"
        db.session.add(row)
        db.session.commit()

    items = data_of(app.test_client().get("/api/settings/providers"))["items"]
    card = next(item for item in items if item["id"] == "azure_tts")

    assert card["configured"] is True, "库里确实填了 Key"
    assert card["available"] is False, "没有适配器就不该说「能用」"


def test_card_says_configured_but_not_available_for_a_stub_adapter(app_factory):
    """适配器在、凭据也在，但实现还没写 —— 卡片要同时说出这两件事。

    与上一条的区别：那条是「根本没有适配器」（查表就找不到），
    这条是「适配器是 P0 的骨架」。前端两种都要能显示成「还用不了」，
    但原因文案不同：一个是等实现，一个是等接上。
    """
    from app.extensions import db
    from app.models import Provider

    app = app_factory(seed=True, env=SPEECH_ENV)
    with app.app_context():
        row = Provider(id="volc_asr", name="火山语音识别", kind="asr")
        row.api_key = "volc-secret-value"
        db.session.add(row)
        db.session.commit()

    items = data_of(app.test_client().get("/api/settings/providers"))["items"]
    card = next(item for item in items if item["id"] == "volc_asr")

    assert card["configured"] is True
    assert card["available"] is False
    assert card["missing"] == [], "凭据是齐的，不该再让人去补字段"


def test_providers_list_never_returns_the_ciphertext(app_factory):
    """接口层连密文都不该出现 —— 密文同样是凭据（P0-C1）。"""
    app = app_factory(
        seed=True,
        env={"LLM_PROVIDER": "deepseek", "LLM_API_KEY": "sk-should-not-appear"},
    )

    raw = app.test_client().get("/api/settings/providers").get_data(as_text=True)

    assert "sk-should-not-appear" not in raw
    assert "api_key_enc" not in raw
    assert "apiKeyEnc" not in raw


def test_saving_a_key_masks_it(app_factory):
    """P0-A4：保存后接口只回掩码，形如 sk-****1234。"""
    app = app_factory(seed=True)
    client = app.test_client()

    body = data_of(
        client.put(
            "/api/settings/providers/deepseek",
            json={
                "apiKey": "sk-1234567890abcdef1234",
                "baseUrl": "https://api.deepseek.com/v1",
                "defaultModel": "deepseek-chat",
            },
        )
    )

    assert body["configured"] is True
    assert body["maskedKey"].startswith("sk-")
    assert body["maskedKey"].endswith("1234")
    assert "1234567890abcdef" not in str(body)
    # 列表接口读到的也是同一份事实
    item = next(
        i for i in data_of(client.get("/api/settings/providers"))["items"] if i["id"] == "deepseek"
    )
    assert item["configured"] is True
    assert item["maskedKey"] == body["maskedKey"]


def test_saving_a_key_is_persisted_encrypted(app_factory):
    """P0-A4 的「刷新页面仍在」= 真的落库了，而且落的是密文。"""
    app = app_factory(seed=True)
    app.test_client().put(
        "/api/settings/providers/deepseek", json={"apiKey": "sk-persist-me-9999"}
    )

    from app.extensions import db
    from app.models import Provider

    row = db.session.get(Provider, "deepseek")
    assert row.api_key_enc and "sk-persist-me-9999" not in row.api_key_enc
    assert row.reveal_api_key() == "sk-persist-me-9999"
    assert row.configured is True


def test_omitting_the_key_leaves_it_alone(app_factory):
    """前端表单回显的是掩码，不是明文 —— 所以「没填 Key」不等于「清空 Key」。

    否则用户在设置页只改一下模型名，Key 就被顺手抹掉了。
    """
    app = app_factory(seed=True)
    client = app.test_client()
    client.put("/api/settings/providers/deepseek", json={"apiKey": "sk-keep-me-4321"})

    body = data_of(client.put("/api/settings/providers/deepseek", json={"defaultModel": "v3"}))

    assert body["defaultModel"] == "v3"
    assert body["maskedKey"].endswith("4321"), "只改模型名，不该把 Key 抹掉"


def test_clearing_the_key_requires_an_explicit_flag(app_factory):
    app = app_factory(seed=True)
    client = app.test_client()
    client.put("/api/settings/providers/deepseek", json={"apiKey": "sk-clear-me-1111"})

    body = data_of(
        client.put("/api/settings/providers/deepseek", json={"clearApiKey": True})
    )

    assert body["configured"] is False
    assert body["maskedKey"] == ""


def test_saving_an_unknown_provider_is_404(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/providers/nope", json={"apiKey": "sk-x"})

    envelope(response, 40401)
    assert response.status_code == 404


def test_saving_a_private_base_url_is_rejected(app_factory):
    """自定义 base_url 是 SSRF 入口（AGENTS.md §4.1）—— 内网地址一律拒绝。"""
    app = app_factory(seed=True)

    response = app.test_client().put(
        "/api/settings/providers/custom",
        json={"baseUrl": "http://127.0.0.1:8080/v1", "apiKey": "sk-x"},
    )

    envelope(response, 40001)
    assert "内网" in response.get_json()["message"] or "地址" in response.get_json()["message"]


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "gopher://127.0.0.1:70/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/v1",
        "http://192.168.1.1/v1",
    ],
)
def test_ssrf_blocklist_covers_the_usual_targets(app_factory, bad_url):
    app = app_factory(seed=True)

    response = app.test_client().put(
        "/api/settings/providers/custom", json={"baseUrl": bad_url}
    )

    envelope(response, 40001)


def test_saving_a_malformed_base_url_is_rejected(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/providers/custom", json={"baseUrl": "不是地址"})

    envelope(response, 40001)


def test_saving_an_empty_body_is_rejected(app_factory):
    """空请求体是客户端 bug，不该被当成「什么都没改」蒙混过关。"""
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/providers/deepseek", json={})

    envelope(response, 40001)


# --- 测试连接（§4.2 / P0-A5）---


def test_probe_returns_real_shape_on_success(app_factory, monkeypatch):
    from app.providers.base import ProbeResult

    make_probe(monkeypatch, ProbeResult(ok=True, latency_ms=320, model="deepseek-chat"))

    response = configured_llm(app_factory).test_client().post("/api/settings/providers/deepseek/test")

    data = data_of(response)
    assert data["ok"] is True
    assert data["latencyMs"] == 320
    assert data["model"] == "deepseek-chat"


def test_probe_actually_calls_the_provider(app_factory, monkeypatch):
    """不能只是「返回了好看的 JSON」—— 得真去探了。"""
    from app.providers.base import ProbeResult

    calls = make_probe(monkeypatch, ProbeResult(ok=True, latency_ms=12))

    configured_llm(app_factory).test_client().post("/api/settings/providers/deepseek/test")

    assert calls == ["deepseek"]


def test_probe_reports_a_bad_key_instead_of_claiming_success(app_factory, monkeypatch):
    """P0-A5：填错 Key 要显示失败原因，绝不能只弹「操作成功」。"""
    from app.providers.base import ProbeResult

    make_probe(
        monkeypatch,
        ProbeResult(ok=False, error="HTTP 401：invalid api key", error_code="unauthorized"),
    )

    data = data_of(configured_llm(app_factory).test_client().post("/api/settings/providers/deepseek/test"))

    assert data["ok"] is False
    assert data["errorCode"] == "unauthorized"
    assert "401" in data["error"]


def test_probe_reports_a_timeout(app_factory, monkeypatch):
    from app.providers.base import ProbeResult

    make_probe(
        monkeypatch,
        ProbeResult(ok=False, error="上游在超时时间内没有响应", error_code="timeout"),
    )

    data = data_of(configured_llm(app_factory).test_client().post("/api/settings/providers/deepseek/test"))

    assert data["errorCode"] == "timeout"


def test_probe_on_an_unconfigured_provider_is_40201(app_factory):
    """P0-B3 的形状由契约钉死：data 直接是 {ok:false, error:"missing_api_key"}。"""
    app = app_factory(seed=True)

    response = app.test_client().post("/api/settings/providers/kimi/test")

    body = envelope(response, 40201)
    assert body["message"], "message 必须可读（P0-B3）"
    assert body["data"]["ok"] is False
    assert body["data"]["error"] == "missing_api_key"


def test_probe_on_an_unknown_provider_is_404(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().post("/api/settings/providers/nope/test")

    envelope(response, 40401)


def test_probe_result_is_remembered_for_the_card_list(app_factory, monkeypatch):
    """卡片上的「延迟 xxx ms」来自最近一次探活。"""
    from app.providers.base import ProbeResult

    make_probe(monkeypatch, ProbeResult(ok=True, latency_ms=456, model="deepseek-chat"))
    client = configured_llm(app_factory).test_client()
    client.post("/api/settings/providers/deepseek/test")

    card = next(
        i for i in data_of(client.get("/api/settings/providers"))["items"] if i["id"] == "deepseek"
    )
    assert card["latencyMs"] == 456


def test_card_latency_is_null_before_any_probe(app_factory):
    """没探过就说没探过 —— 编一个 0ms 出来会让用户以为测过了。"""
    app = app_factory(seed=True)

    card = next(
        i
        for i in data_of(app.test_client().get("/api/settings/providers"))["items"]
        if i["id"] == "deepseek"
    )
    assert card["latencyMs"] is None


# --- 启用服务商（P0-A6）---


def test_enable_makes_it_the_only_enabled_one(app_factory):
    app = app_factory(seed=True)
    client = app.test_client()

    data_of(client.post("/api/settings/providers/openai/enable"))

    items = data_of(client.get("/api/settings/providers"))["items"]
    enabled = [i["id"] for i in items if i["enabled"]]
    assert enabled == ["openai"]


def test_enable_moves_the_health_endpoint_over(app_factory):
    """P0-A6 的判定步骤就是看 /api/health。"""
    app = app_factory(seed=True)
    client = app.test_client()

    client.post("/api/settings/providers/openai/enable")

    assert data_of(client.get("/api/health"))["llm"]["provider"] == "openai"


def test_enable_survives_a_new_registry(app_factory):
    """设置是给「之后的所有课堂」用的，不能只活在进程内存里。"""
    app = app_factory(seed=True)
    client = app.test_client()
    client.post("/api/settings/providers/qwen/enable")

    from app.extensions import db
    from app.models import SettingsKV
    from app.models.settings_kv import KEY_ACTIVE_PROVIDER

    assert db.session.get(SettingsKV, KEY_ACTIVE_PROVIDER).value == "qwen"


def test_enable_an_unknown_provider_is_404(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().post("/api/settings/providers/nope/enable")

    envelope(response, 40401)


def test_enabling_a_provider_without_a_key_does_not_fake_success(app_factory):
    """允许先启用后填 Key，但接口不能因此谎报「已就绪」。"""
    app = app_factory(seed=True)
    client = app.test_client()

    body = data_of(client.post("/api/settings/providers/openai/enable"))

    assert body["enabled"] is True
    assert body["configured"] is False
    assert data_of(client.get("/api/health"))["providers"]["llm"] == "unconfigured"


# --- 语音设置（§4.2 / P0-A7）---


def test_voice_settings_have_defaults(app_factory):
    app = app_factory(seed=True)

    data = data_of(app.test_client().get("/api/settings/voice"))

    assert data["voices"], "至少要有 3 张音色卡"
    assert data["teacherVoiceId"] == "vp_teacher_shen"  # 原型默认选中沈老师
    assert data["speed"] == 1.0
    assert data["intonation"] == "natural"
    assert data["asrEnabled"] is True


def test_voice_settings_round_trip(app_factory):
    """P0-A7：选「顾老师」+ 语速 1.2 → 保存 → 刷新后回显一致。"""
    app = app_factory(seed=True)
    client = app.test_client()

    saved = data_of(
        client.put(
            "/api/settings/voice",
            json={"teacherVoiceId": "vp_teacher_gu", "speed": 1.2, "intonation": "expressive"},
        )
    )
    assert saved["teacherVoiceId"] == "vp_teacher_gu"

    reread = data_of(client.get("/api/settings/voice"))
    assert reread["teacherVoiceId"] == "vp_teacher_gu"
    assert reread["speed"] == 1.2
    assert reread["intonation"] == "expressive"


def test_voice_cards_expose_whether_the_vendor_id_is_filled(app_factory):
    """音色 ID 来自 .env；没配就要能显示「未配置音色 ID」而不是假装可用。"""
    app = app_factory(seed=True)

    data = data_of(app.test_client().get("/api/settings/voice"))

    assert all("configured" in voice for voice in data["voices"])
    assert all(voice["configured"] is False for voice in data["voices"])


def test_voice_id_becomes_configured_when_the_env_has_it(app_factory):
    app = app_factory(seed=True, env={"VOLC_TTS_VOICE_TEACHER": "zh_male_shen"})

    data = data_of(app.test_client().get("/api/settings/voice"))

    shen = next(v for v in data["voices"] if v["id"] == "vp_teacher_shen")
    assert shen["configured"] is True
    assert shen["voiceType"] == "zh_male_shen"


def test_voice_speed_out_of_range_is_rejected(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/voice", json={"speed": 9.0})

    envelope(response, 40001)


def test_unknown_voice_is_rejected(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/voice", json={"teacherVoiceId": "vp_nope"})

    envelope(response, 40001)


def test_unknown_intonation_is_rejected(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/voice", json={"intonation": "很激动"})

    envelope(response, 40001)


def test_voice_settings_reject_a_non_object_body(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().put(
        "/api/settings/voice", data="不是 JSON", content_type="application/json"
    )

    envelope(response, 40001)


def test_asr_switches_round_trip(app_factory):
    """ASR 开关也是 P0-A7 的一部分：关掉要能存住、刷新后还是关的。"""
    app = app_factory(seed=True)
    client = app.test_client()

    saved = data_of(
        client.put("/api/settings/voice", json={"asrEnabled": False, "asrBrowserLocal": False})
    )
    assert saved["asrEnabled"] is False
    assert saved["asrBrowserLocal"] is False

    reread = data_of(client.get("/api/settings/voice"))
    assert reread["asrEnabled"] is False
    assert reread["asrBrowserLocal"] is False


def test_asr_is_stored_under_its_own_key(app_factory):
    """ASR 开关不该跟音色混在一格里存。

    接口层把两者合成一个对象是给前端看的（§4.2 把 ASR 挂在 voice 端点下），
    但落库必须分开 —— P2 接语音识别时读的是 asr 这一格，
    混存意味着「改个音色顺手把学生的发言能力关了」这种 bug 要翻代码才发现。
    """
    app = app_factory(seed=True)
    client = app.test_client()

    from app.models.settings_kv import KEY_ASR, KEY_VOICE
    from app.services import settings_service

    client.put(
        "/api/settings/voice",
        json={"teacherVoiceId": "vp_teacher_gu", "speed": 1.2, "asrEnabled": False},
    )

    with app.app_context():
        voice = settings_service._read_json(KEY_VOICE)
        asr = settings_service._read_json(KEY_ASR)

    assert voice == {"teacherVoiceId": "vp_teacher_gu", "speed": 1.2, "intonation": "natural"}
    assert asr == {"asrEnabled": False, "asrBrowserLocal": True}


def test_voice_and_asr_do_not_clobber_each_other(app_factory):
    """两次请求各改一半 → 两半都要留住（拆分存储最容易踩的坑）。"""
    app = app_factory(seed=True)
    client = app.test_client()

    client.put("/api/settings/voice", json={"speed": 1.5})
    client.put("/api/settings/voice", json={"asrBrowserLocal": False})

    reread = data_of(client.get("/api/settings/voice"))
    assert reread["speed"] == 1.5
    assert reread["asrBrowserLocal"] is False


# --- 生成参数（§4.2 / P0-A7）---


def test_generation_defaults_match_the_prototype(app_factory):
    app = app_factory(seed=True)

    data = data_of(app.test_client().get("/api/settings/generation"))

    assert data["pageCount"] == 12
    assert data["classmateCount"] == 3
    assert data["intensity"] == "medium"
    assert data["scriptDetail"] == "detailed"
    assert data["autoIllustration"] is True
    assert data["quizPerChapter"] is True
    assert data["whiteboard"] is True


def test_generation_round_trip(app_factory):
    app = app_factory(seed=True)
    client = app.test_client()

    data_of(
        client.put(
            "/api/settings/generation",
            json={"pageCount": 18, "classmateCount": 5, "intensity": "high", "whiteboard": False},
        )
    )

    reread = data_of(client.get("/api/settings/generation"))
    assert reread["pageCount"] == 18
    assert reread["classmateCount"] == 5
    assert reread["intensity"] == "high"
    assert reread["whiteboard"] is False
    # 没提交的字段保持原值，不该被重置成默认值
    assert reread["scriptDetail"] == "detailed"


@pytest.mark.parametrize("page_count", [8, 20])
def test_page_count_boundaries_are_inclusive(app_factory, page_count):
    """规格是 8~20，两端都算合法。"""
    app = app_factory(seed=True)

    data = data_of(app.test_client().put("/api/settings/generation", json={"pageCount": page_count}))

    assert data["pageCount"] == page_count


@pytest.mark.parametrize("page_count", [7, 21, 0, -3])
def test_page_count_outside_the_range_is_rejected(app_factory, page_count):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/generation", json={"pageCount": page_count})

    body = envelope(response, 40001)
    assert "8" in body["message"] and "20" in body["message"], "错误里要说清合法范围"


@pytest.mark.parametrize("count", [0, 5])
def test_classmate_count_boundaries_are_inclusive(app_factory, count):
    app = app_factory(seed=True)

    data = data_of(
        app.test_client().put("/api/settings/generation", json={"classmateCount": count})
    )

    assert data["classmateCount"] == count


@pytest.mark.parametrize("count", [6, -1])
def test_classmate_count_outside_the_range_is_rejected(app_factory, count):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/generation", json={"classmateCount": count})

    body = envelope(response, 40001)
    assert "0" in body["message"] and "5" in body["message"]


def test_page_count_must_be_a_number(app_factory):
    app = app_factory(seed=True)

    response = app.test_client().put("/api/settings/generation", json={"pageCount": "十二"})

    envelope(response, 40001)


def test_generation_rejects_an_unknown_key(app_factory):
    """拼错的字段名必须报错，否则用户以为改生效了，其实没有。"""
    app = app_factory(seed=True)

    response = app.test_client().put(
        "/api/settings/generation", json={"pageCont": 15}  # 少一个 s
    )

    envelope(response, 40001)


def test_generation_fills_in_defaults_for_keys_that_are_missing(app_factory):
    """P0-C4：读缺失键要返回默认值，不能返回 null。

    典型场景是「库里存着老版本的设置，规格后来加了一个参数」——
    老行里没有那个键，读出来必须是默认值而不是 null，
    否则前端拿到 null 去算页数，会算出 NaN 页。
    """
    app = app_factory(seed=True)

    from app.common.dbw import db_write
    from app.extensions import db
    from app.models import SettingsKV
    from app.models.settings_kv import KEY_GENERATION

    def _write_partial() -> None:
        row = SettingsKV(key=KEY_GENERATION)
        db.session.add(row)
        row.value = {"pageCount": 15}  # 只有页数，其余键都缺

    db_write(_write_partial)

    data = data_of(app.test_client().get("/api/settings/generation"))
    assert data["pageCount"] == 15  # 存了的用它
    assert data["classmateCount"] == 3  # 没存的用默认值，而不是 null
    assert data["intensity"] == "medium"


# --- 内置角色（§4.2）---


def test_roles_list_has_a_teacher_and_three_students(app_factory):
    """§4.2 的角色表：沈老师(teacher) + 林晓 / 陈默 / 苏雨。

    P0-A8 说的「3 个角色」指 3 位 AI 同学 —— 两种读法在这里同时钉住。
    """
    app = app_factory(seed=True)

    data = data_of(app.test_client().get("/api/agents/roles"))

    codes = [item["code"] for item in data["items"]]
    assert codes == ["shen", "xiaoxiao", "chenmo", "suyu"]
    assert [i for i in data["items"] if i["role"] == "teacher"] == [data["items"][0]]
    assert len([i for i in data["items"] if i["role"] == "student"]) == 3


def test_role_carries_persona_and_voice(app_factory):
    app = app_factory(seed=True)

    items = data_of(app.test_client().get("/api/agents/roles"))["items"]
    shen = items[0]

    for key in ("id", "code", "name", "role", "avatarColor", "voiceProfileId", "persona"):
        assert key in shen
    assert shen["persona"]["tone"]
    assert shen["voiceProfileId"] == "vp_teacher_shen"


def test_roles_are_readable_without_seed_data(app_factory):
    """没灌种子时给空列表，而不是 500。"""
    app = app_factory()

    data = data_of(app.test_client().get("/api/agents/roles"))

    assert data["items"] == []
    assert data["total"] == 0
