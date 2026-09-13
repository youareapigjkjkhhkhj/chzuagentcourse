"""P2 语音接口契约测试（§4.1 的七个端点 + P2-B2 的降级口径）。

这是 §4.1 那张表的一份账本：每个端点在这里至少出现一次，成功与失败两条路
都落到具体的业务码上。三件事是这个文件真正要守住的：

1. **P2-B2：任何错误都带 `fallback`**。前端不许自己猜「退到文字还是浏览器」——
   猜错的那一次，是学生在一节课中间看到一个红色弹窗。
2. **P2-B3：清单的字段与播放器一一对应**。少一个字段，前端就要多写一处
   判断，而那一处判断迟早会与后端分叉。
3. **P2-G3：关掉语音不是错误**。`VOICE_ENABLED=false` 之后课堂仍是一节
   可以读、可以打字提问的纯文字课堂，而不是满屏红色。

模型一律是离线替身（AGENTS §23）：没配 `VOLC_*` 时注册表的默认就是 Mock，
和真机上的差别只有「声音好不好听」。
"""

from __future__ import annotations

import io
import time

import pytest

from app.common.identity import OWNER_HEADER
from app.extensions import db
from tests.contract.test_p1_api import data_of, envelope

pytestmark = pytest.mark.contract

#: 顾老师的两个音色 ID 都留空 —— 用它验「音色没配好」那条路。
VOICE_ENV = {
    "VOLC_TTS_VOICE_TEACHER": "vendor-teacher",
    "VOLC_TTS_VOICE_HISTORY": "",
    "VOLC_TTS_VOICE_SCIENCE": "vendor-science",
}

DEMO_COURSE = "course_demo_ml"
SHEN, GU = "vp_teacher_shen", "vp_teacher_gu"


@pytest.fixture()
def seeded(app_factory):
    """一台刚部署好的机器：示例课程 + 三个音色（音色 ID 走配置注入）。"""
    return app_factory(seed=True, env=VOICE_ENV)


@pytest.fixture()
def client(seeded):
    """挂在**灌过种子的**那台机器上的客户端（覆盖 conftest 的同名夹具）。

    conftest 的 `client` 绑的是没灌种子的 `app`，而这里每个用例都要拿示例课程
    那一课的讲稿去合成 —— 挂错机器的话，所有失败都会长成「这门课不存在」。
    """
    return seeded.test_client()


@pytest.fixture(autouse=True)
def _reap_workers(seeded):
    """用例结束就关掉线程池（与 P1 契约测试同一个理由）。

    预合成是真的在后台线程里跑的，线程不关掉就可能跨到下一个用例去写一个
    已经删过表的库 —— 那种失败与断言想验的事毫无关系，却能让人查上半天。
    """
    from app.common import tasks

    yield
    tasks.shutdown_runner(seeded)


def _beats(client, course_id: str = DEMO_COURSE) -> dict:
    return data_of(client.get(f"/api/courses/{course_id}/audio-manifest"))


def _wait_for_audio(client, course_id: str = DEMO_COURSE, timeout: float = 20.0) -> dict:
    """等整课预合成跑完（进度就是清单里的 `readyCount`，没有别的计数器）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        manifest = _beats(client, course_id)
        if manifest["beatCount"] and manifest["readyCount"] == manifest["beatCount"]:
            return manifest
        time.sleep(0.05)
    raise AssertionError("预合成没有在超时前跑完")


# --- 音色 ---


def test_list_voices(seeded, client):
    """`GET /api/voice/voices`：`usable` 是「配置齐了**且**服务商可用」。"""
    data = data_of(client.get("/api/voice/voices"))

    assert data["total"] == 3
    assert data["current"] == SHEN
    assert data["provider"] == "mock", "没配 Key 时落到离线替身"
    assert data["enabled"] is True and data["usable"] is True
    usable = {item["id"]: item["usable"] for item in data["items"]}
    assert usable[SHEN] is True
    assert usable[GU] is False, "没配上游音色 ID 的音色不可用"


# --- 试听（P2-A5 / F2-11）---


def test_preview_synthesizes_then_hits_the_cache(seeded, client):
    """试听两次：第一次合成、第二次命中缓存 —— 重复点击不重复计费。"""
    first = data_of(client.post(f"/api/voice/voices/{SHEN}/preview"))
    second = data_of(client.post(f"/api/voice/voices/{SHEN}/preview"))

    assert first["cached"] is False and second["cached"] is True
    assert first["url"] == second["url"]
    assert first["durationMs"] > 0


def test_preview_audio_is_playable(seeded, client):
    """试听的 URL 要真的能取到音频，且 MIME 跟着**实际**格式走。

    Mock 出的是 wav、配置里写的是 mp3 —— 按配置给 MIME，浏览器会按 mp3 解
    一个 wav 文件：不报错，只是没有声音。
    """
    url = data_of(client.post(f"/api/voice/voices/{SHEN}/preview"))["url"]
    response = client.get(url)

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "audio/wav"
    assert response.data[:4] == b"RIFF", "拿到的确实是那个 WAV"


def test_preview_force_resynthesizes(seeded, client):
    """`force=1` 绕开缓存（改了音色参数、想立刻听到新版本时用）。"""
    client.post(f"/api/voice/voices/{SHEN}/preview")
    again = data_of(client.post(f"/api/voice/voices/{SHEN}/preview", json={"force": True}))

    assert again["cached"] is False


def test_preview_unconfigured_voice_is_rejected(seeded, client):
    """音色没配上游 ID：40001 说清原因，而不是合成出一段静音。"""
    body = envelope(client.post(f"/api/voice/voices/{GU}/preview"), expect_code=40001)

    assert "上游音色 ID" in body["message"]


def test_preview_unknown_voice_is_404(seeded, client):
    body = envelope(client.post("/api/voice/voices/vp_nobody/preview"), expect_code=40401)

    assert body["data"]["details"]["fallback"] == "text", "404 也要能降级（P2-B2）"


def test_preview_missing_audio_file_is_404(seeded, client):
    """还没合成过就去播：404 —— 而不是一个空的 200。"""
    envelope(client.get(f"/api/voice/voices/{SHEN}/preview?v=deadbeef"), expect_code=40401)


# --- 单句合成（P2-A1）---


def test_tts_returns_a_playable_url(seeded, client):
    """P2-A1：合成「学习率决定了每一步走多远」→ 得到可正常播放的音频。"""
    data = data_of(
        client.post(
            "/api/voice/tts",
            json={"text": "学习率决定了每一步走多远", "voiceId": SHEN, "speed": 1.0, "tone": "natural"},
        )
    )
    audio = client.get(data["url"])

    assert audio.status_code == 200
    assert len(audio.data) > 44, "WAV 头之后要有数据"
    assert data["durationMs"] > 0
    assert data["tone"] == "", "natural 档 = 不调整（与设置页同一个口径）"


def test_tts_uses_the_selected_voice_when_none_is_given(seeded, client):
    """没传 `voiceId` 时用设置页选中的那一个（F2-11「选中的音色全局生效」）。"""
    data = data_of(client.post("/api/voice/tts", json={"text": "同学们好"}))

    assert data["voiceId"] == SHEN


def test_tts_speed_and_tone_reach_the_synthesis(seeded, client):
    """`speed` / `tone` 必须真的进合成，也真的进缓存键。

    只回显不生效是最难发现的一种错：界面显示 1.5 倍速、听着还是原速。
    """
    from app.providers.tts.mock import MockTTS
    from app.services.provider_registry import get_registry

    spy = MockTTS()
    with seeded.app_context():
        get_registry().register(spy)

    data_of(client.post("/api/voice/tts", json={"text": "语速", "speed": 1.5, "tone": "expressive"}))

    call = [item for item in spy.calls if item["text"] == "语速"][-1]
    assert call["speed"] == 1.5
    assert call["tone"] == "expressive"


def test_tts_empty_text_is_rejected(seeded, client):
    envelope(client.post("/api/voice/tts", json={"text": "   "}), expect_code=40001)
    envelope(client.post("/api/voice/tts", json={}), expect_code=40001)


def test_tts_rejects_a_whole_lecture(seeded, client):
    """单句合成长度封顶：整段讲稿要走整课预合成（那条路有进度、有失效）。"""
    body = envelope(client.post("/api/voice/tts", json={"text": "字" * 301}), expect_code=40001)

    assert "整课预合成" in body["message"]


def test_tts_rejects_a_bad_speed(seeded, client):
    envelope(client.post("/api/voice/tts", json={"text": "你好", "speed": "快一点"}), expect_code=40001)


# --- 整课预合成 + 清单（P2-A2 / B3）---


def test_manifest_fields_match_the_player(seeded, client):
    """P2-B3：清单的字段与前端播放器一一对应。

    五个契约字段（`pageNo / beatId / textHash / url / durationMs`）一个都不能少，
    再加上播放器要的文本、时长基准与状态。
    """
    manifest = _beats(client)

    assert manifest["beatCount"] > 0, "示例课本来就该有讲稿"
    assert manifest["readyCount"] == 0, "还没合成过"
    assert manifest["reason"] == "", "什么都有，不该有降级理由"
    assert manifest["enabled"] is True and manifest["available"] is True
    for beat in manifest["beats"]:
        assert {"pageNo", "beatId", "textHash", "url", "durationMs"} <= set(beat)
        assert {"text", "estSec", "status", "subtitles"} <= set(beat)
        assert beat["status"] == "missing"
        assert beat["url"] == "", "没有声音时给空串，前端据此显示「未合成」"
        assert beat["text"], "讲稿文本要一起给：字幕与纯文字降级都靠它"


def test_narrate_runs_in_the_background_and_the_manifest_follows(seeded, client):
    """`narrate` 立刻返回、后台合成；进度就是清单里的 `readyCount`（P2-A2）。"""
    started = data_of(client.post(f"/api/courses/{DEMO_COURSE}/narrate"))

    assert started["started"] is True
    assert started["running"] is True
    assert started["beatCount"] > 0

    manifest = _wait_for_audio(client)
    assert manifest["readyCount"] == manifest["beatCount"]
    for beat in manifest["beats"]:
        assert beat["status"] == "ready"
        assert beat["url"].startswith(f"/api/courses/{DEMO_COURSE}/audio/{beat['beatId']}?v=")
        assert beat["durationMs"] > 0


def test_narrate_is_idempotent(seeded, client):
    """再点一次「全部合成」：已经有的不重新合成（幂等，不重复计费）。"""
    client.post(f"/api/courses/{DEMO_COURSE}/narrate")
    _wait_for_audio(client)

    from app.models import UsageRecord

    with seeded.app_context():
        before = UsageRecord.query.filter_by(kind="tts").count()

    again = data_of(client.post(f"/api/courses/{DEMO_COURSE}/narrate", json={"force": False}))
    _wait_for_audio(client)

    with seeded.app_context():
        after = UsageRecord.query.filter_by(kind="tts").count()
    assert again["enabled"] is True, "第二次请求照样是「可以合成」，只是没什么可合的"
    assert after == before, "全部命中缓存时不该再记账"


def test_beat_audio_is_served_and_versioned(seeded, client):
    """清单里的 URL 能取到音频，且带着内容哈希（`?v=`）。

    版本号是给**浏览器缓存**用的：重合成之后同一个 beat 的 URL 会变，否则
    学生听到的是缓存里上一版讲稿的声音。服务端这边不看它 —— 文件是不是这一版
    由清单里的 `textHash` 说了算（对不上时 `url` 就是空串）。
    """
    client.post(f"/api/courses/{DEMO_COURSE}/narrate")
    manifest = _wait_for_audio(client)
    first = manifest["beats"][0]

    response = client.get(first["url"])
    assert response.status_code == 200
    assert len(response.data) > 44
    assert first["url"].endswith(f"?v={first['textHash'][:8]}")

    # 换一个版本号取到的是同一个文件：服务端按 beat 取资产，不按 URL 里的哈希查
    same = client.get(f"/api/courses/{DEMO_COURSE}/audio/{first['beatId']}?v=00000000")
    assert same.status_code == 200 and same.data == response.data


def test_beat_audio_of_an_unknown_beat_is_404(seeded, client):
    envelope(client.get(f"/api/courses/{DEMO_COURSE}/audio/p99-b9"), expect_code=40401)


def test_narrate_unknown_course_is_404(seeded, client):
    envelope(client.post("/api/courses/course_nope/narrate"), expect_code=40401)
    envelope(client.get("/api/courses/course_nope/audio-manifest"), expect_code=40401)


def test_another_teachers_course_is_404(seeded, client):
    """越权与不存在同一个答复（AGENTS §4.1）：403 等于承认「这个 id 存在」。"""
    from app.models import User

    with seeded.app_context():
        other = User(name="另一位老师", role="teacher")
        db.session.add(other)
        db.session.commit()
        headers = {OWNER_HEADER: other.id}

    envelope(client.get(f"/api/courses/{DEMO_COURSE}/audio-manifest", headers=headers), expect_code=40401)
    envelope(client.post(f"/api/courses/{DEMO_COURSE}/narrate", headers=headers), expect_code=40401)


# --- 识别（P2 兜底路径 / F2-7）---


def test_asr_returns_text_and_segments(seeded, client):
    response = client.post(
        "/api/voice/asr",
        data={"file": (io.BytesIO(b"\x00\x01" * 8000), "ask.wav")},
        content_type="multipart/form-data",
    )
    data = data_of(response)

    assert data["text"], "离线替身也有确定文本，前端不必为它写特例分支"
    assert data["final"] is True
    assert data["durationMs"] > 0
    assert data["segments"] and data["segments"][0]["text"]


def test_asr_accepts_a_raw_body(seeded, client):
    """`MediaRecorder` 之外的路径：直接 `POST` 一段裸 PCM 也能识别。"""
    data = data_of(client.post("/api/voice/asr?fmt=pcm", data=b"\x00\x01" * 4000))

    assert data["text"]


def test_asr_rejects_browser_recordings_with_a_clear_message(seeded, client):
    """webm/opus 上游不认 —— 40001 说清原因，比传上去收到一段乱码好。

    这条要在**接口层**挡住（`UPLOAD_FORMATS`）：离线替身什么格式都收，
    否则同一段 webm 在真机上报错、在演示环境里回一句识别文本。
    """
    body = envelope(
        client.post(
            "/api/voice/asr",
            data={"file": (io.BytesIO(b"\x1a\x45\xdf\xa3"), "ask.webm")},
            content_type="multipart/form-data",
        ),
        expect_code=40001,
    )
    assert "webm" in body["message"] or "pcm" in body["message"]


def test_asr_without_audio_is_rejected(seeded, client):
    envelope(client.post("/api/voice/asr", data=b""), expect_code=40001)


def test_asr_can_be_switched_off(seeded, client):
    """设置页关掉「允许语音发言」：40902 + `fallback: text`，前端据此提示打字。"""
    from app.services import settings_service

    with seeded.app_context():
        settings_service.update_voice({"asrEnabled": False})

    body = envelope(client.post("/api/voice/asr", data=b"\x00\x01"), expect_code=40902)
    assert body["data"]["details"]["fallback"] == "text"


# --- 用量（P2-A11 / F2-10）---


def test_usage_records_tts_and_asr(seeded, client):
    # 一秒的 16k/16bit PCM：ASR 按秒计费，少于半秒会被记成 0 秒、直接不写账
    client.post("/api/voice/tts", json={"text": "记一笔账", "voiceId": SHEN})
    client.post("/api/voice/asr", data={"file": (io.BytesIO(b"\x00\x01" * 16000), "a.wav")})

    data = data_of(client.get("/api/voice/usage"))

    kinds = {item["kind"]: item for item in data["kinds"]}
    assert kinds["tts"]["units"] > 0 and kinds["tts"]["unitName"] == "chars"
    assert kinds["asr"]["units"] > 0 and kinds["asr"]["unitName"] == "seconds"
    assert kinds["realtime"]["units"] == 0
    assert data["priced"] is False, "没配价目表就别报一个 ¥0.00 说这节课不要钱"
    assert data["totalCost"] == 0.0


def test_usage_can_be_scoped_to_a_course(seeded, client):
    client.post(f"/api/courses/{DEMO_COURSE}/narrate")
    _wait_for_audio(client)

    scoped = data_of(client.get(f"/api/voice/usage?refType=course&refId={DEMO_COURSE}"))
    other = data_of(client.get("/api/voice/usage?refType=course&refId=course_demo_photosynthesis"))

    assert sum(item["units"] for item in scoped["kinds"]) > 0
    assert sum(item["units"] for item in other["kinds"]) == 0


# --- 降级（P2-B2 / P2-G3）---


def test_voice_disabled_is_not_an_error(seeded, client):
    """`VOICE_ENABLED=false`：清单照常给（全是文字），用户点的合成给 40302。

    这一条是「关掉语音之后还能上课」的全部含义：内容在，只是没有声音。
    """
    seeded.config["VOICE_ENABLED"] = False

    manifest = _beats(client)
    assert manifest["enabled"] is False
    assert manifest["available"] is False
    assert manifest["reason"] == "voice_disabled"
    assert manifest["fallback"] == "text"
    assert manifest["beats"], "讲稿还是要在"
    assert all(beat["url"] == "" for beat in manifest["beats"])

    body = envelope(client.post("/api/voice/tts", json={"text": "你好"}), expect_code=40302)
    assert body["data"]["fallback"] == "text"


def test_narrate_when_voice_is_disabled_does_nothing(seeded, client):
    seeded.config["VOICE_ENABLED"] = False

    data = data_of(client.post(f"/api/courses/{DEMO_COURSE}/narrate"))

    assert data["started"] is False and data["running"] is False
    assert data["enabled"] is False


def test_manifest_degrades_when_the_provider_is_missing(app_factory):
    """配了音色但服务商没配好：清单要给出来，并说清是**服务商**没配。

    与 `voice_not_configured`（没选音色）分开，是因为两者的修法完全不同：
    一个去设置页选音色，一个去填 Key。

    这条要单独起一台机器：默认服务商是「有 Key 才选 volc_tts，否则用离线替身」
    （见 `registry.default_name`），所以只有在一个**配了一半**的部署上，
    「选了真服务商但缺字段」这个状态才存在。
    """
    from app.providers.tts.mock import MockTTS
    from app.services.provider_registry import get_registry

    class Unconfigured(MockTTS):
        """占住真服务商的名字，但没配好 —— 与 `test_voice_prefs` 里那个同一个用法。"""

        name = "volc_tts"

        @property
        def configured(self) -> bool:
            return False

        def missing_config(self) -> list[str]:
            return ["API Key"]

    app = app_factory(seed=True, env={**VOICE_ENV, "VOLC_TTS_API_KEY": "half-configured"})
    with app.app_context():
        get_registry().register(Unconfigured())

    manifest = _beats(app.test_client())
    assert manifest["reason"] == "provider_not_configured"
    assert manifest["available"] is False
    assert manifest["fallback"] == "", "音色与服务商都是部署的事，与降级路径无关"


def test_the_mock_is_flagged_as_simulated(seeded, client):
    """离线替身要在清单里说出来：否则用户对着一段静音 WAV 找半天问题。"""
    assert _beats(client)["simulated"] is True


# --- 会话票据（P2-F4）---

#: 一个 WebSocket 升级请求该有的头。**少了它就进不了视图**：那条路由标着
#: `websocket=True`，Werkzeug 只把 `ws://` 的请求交给它，普通 GET 会拿到
#: 一个 `WebsocketMismatch`（400 / 40001「参数不合法」—— 在说「你少带了头」）。
WS_UPGRADE = {"Connection": "Upgrade", "Upgrade": "websocket"}


@pytest.fixture()
def no_socket(monkeypatch):
    """把握手换成「对端立刻走了」。

    真握手要 `Server.accept` 从 WSGI 环境里掏一个真 socket（`werkzeug.socket`），
    测试客户端没有 —— 走到那一步只会得到一个 50001。所以这里把它换成一个
    立刻 `ConnectionClosed` 的替身：路由认这个信号，当作「客户端走了」正常收摊。
    这样测到的是「有没有被票据挡在门外」，跳过的只是握手本身（那要真端口，归验收脚本）。
    """
    import simple_websocket

    def refuse(environ, *args, **kwargs):
        raise simple_websocket.ConnectionClosed(message="测试客户端没有真 socket")

    monkeypatch.setattr(simple_websocket.Server, "accept", refuse)


def test_a_ticket_is_issued_before_the_socket(seeded, client):
    """`POST /api/voice/ticket`：建连前先来这一趟，WS 那边才认（P2-F4）。"""
    data = data_of(client.post("/api/voice/ticket"))

    assert len(data["ticket"]) >= 32
    assert data["ttlSec"] == 60
    # 票据里不含任何凭据 —— 它只是一串随机数（AGENTS §4.1）
    assert "volc" not in data["ticket"].lower()


def test_the_handshake_is_refused_before_the_upgrade(seeded, client):
    """没带票据 / 票据不对：拒绝发生在**升级之前**，是一封普通的错误信封。

    而不是一条连上了又立刻断掉的 socket —— 后者前端只能说一句「连接失败」，
    说不出是为什么。`fallback` 照旧带着，与其它语音错误一个形状。

    （浏览器其实读不到这封信封：WS 握手失败在 JS 里只有一个 error 事件。
    它是服务端这侧的兜底；用户看到的说法来自 `POST /api/voice/ticket`。）
    """
    for query in ("", "?ticket=not-a-ticket"):
        body = envelope(
            client.get(f"/ws/voice/realtime{query}", headers=WS_UPGRADE),
            expect_code=40101,
        )
        assert body["data"]["details"]["fallback"] == "text"


def test_a_valid_ticket_opens_the_gate(seeded, client, no_socket):
    """票据有效时请求走到握手那一步 —— 门开了，剩下的不是这里能测的。"""
    ticket = data_of(client.post("/api/voice/ticket"))["ticket"]

    response = client.get(f"/ws/voice/realtime?ticket={ticket}", headers=WS_UPGRADE)

    assert response.status_code == 200


def test_a_ticket_can_only_be_spent_once(seeded, client, no_socket):
    """用过就作废：一张票只够开一条连接。"""
    ticket = data_of(client.post("/api/voice/ticket"))["ticket"]

    client.get(f"/ws/voice/realtime?ticket={ticket}", headers=WS_UPGRADE)
    envelope(
        client.get(f"/ws/voice/realtime?ticket={ticket}", headers=WS_UPGRADE),
        expect_code=40101,
    )


def test_tickets_are_refused_when_voice_is_disabled(seeded, client):
    """总开关关着时不发票据：那一趟 HTTP 是唯一会判开关的地方（P2-G3）。"""
    seeded.config["VOICE_ENABLED"] = False

    body = envelope(client.post("/api/voice/ticket"), expect_code=40302)
    assert body["data"]["fallback"] == "text"


def test_tickets_are_refused_when_the_provider_is_unconfigured(app_factory):
    """上游没配好也不发票据 —— 免得票据拿到手却建不起会话。

    与上面那条同理：能在 HTTP 这一层说清的事（缺哪个 Key，去设置页填），
    不要留到 WS 的握手里只说一句「连接失败」。
    """
    from app.providers.tts.mock import MockRealtime
    from app.services.provider_registry import get_registry

    class Unconfigured(MockRealtime):
        name = "volc_realtime"

        @property
        def configured(self) -> bool:
            return False

        def missing_config(self) -> list[str]:
            return ["API Key"]

    app = app_factory(seed=True, env={**VOICE_ENV, "VOLC_REALTIME_API_KEY": "half-configured"})
    with app.app_context():
        get_registry().register(Unconfigured())

    envelope(app.test_client().post("/api/voice/ticket"), expect_code=40201)
