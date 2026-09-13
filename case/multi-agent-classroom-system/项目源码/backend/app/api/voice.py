"""语音接口（P2 §4）。

接口层只做三件事：取参数 → 调 service → 包信封（P0 §4）。

**为什么课程级的三个路由也在这个文件里**（`/api/courses/{id}/narrate`、
`audio-manifest`、`audio/{beat_id}`）：它们全是语音功能的出入口，而语音有
一条别处没有的规矩 —— **任何失败都要带 `fallback`**（P2-B2）。这条规矩靠
蓝图级的 `errorhandler` 兜住（见文件末尾），蓝图因此必须把这些路由圈进来；
散在 courses.py 里就得在那边再挂一次同样的处理，两边迟早分叉。路径前缀照
`技术实现方案 §4` 的模块划分写在路由上（`voice | /api/voice`），
读路由表时仍是一眼可见。

`/api/voice/tts` 与 `/api/voice/voices/{id}/preview` 是**同一条链路**：
同一个音色、按「文本 + 合成规格」的哈希缓存、返回一个可直接播的 URL。
差别只在调用者的意图，账本上分得开（`ref` 前缀），所以实现只写一遍。
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from flask import Blueprint, request, send_file
from werkzeug.exceptions import NotFound

from app.api import json_body
from app.common.errors import AppError, StateError, ValidationError
from app.common.identity import current_owner_id
from app.common.logging import get_logger
from app.common.response import ok
from app.services.courses import library
from app.services.voice import assets, jobs, tickets
from app.services.voice import policy as voice_policy
from app.services.voice import prefs as voice_prefs
from app.services.voice import usage as voice_usage

logger = get_logger("app.api.voice")

bp = Blueprint("voice", __name__)

#: 单句合成的文本上限（字）。一个 beat 的讲稿就在 300 字上下 ——
#: 再长的东西该走整课预合成（`narrate`），那条路会落进 `audio_assets` 并有进度，
#: 而单句合成是一句一文件地进试听缓存目录，不该被拿来批量刷。
MAX_TTS_CHARS = 300

#: `/api/voice/asr` 收的格式。**在接口层拦，不留给 Provider**：上游那一句
#: 「只接受 pcm / wav」是厂商的实现细节，而离线替身什么格式都收 ——
#: 同一个 webm 文件在真机上报错、在演示环境里返回一段文本，是最坏的一种分叉。
#: 拦在这里，两种部署给出的答复就一模一样。
UPLOAD_FORMATS = ("pcm", "wav")

#: 音频后缀 → MIME。浏览器按它选解码器，给错就是「有声音文件但播不出来」。
MIMETYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    # 裸流浏览器播不了，老实地按二进制给：那是「前端要自己解码」的意思，
    # 不是「可以当音频播」。
    "pcm": "application/octet-stream",
}


# --- 音色 ---


@bp.get("/api/voice/voices")
def list_voices():
    """可用音色列表（每个音色带 `usable`，前端据此决定试听按钮亮不亮）。

    请求示例：
        GET /api/voice/voices

    与 `GET /api/settings/voice` 的区别：那个是**设置页**（音色卡、语速、开关），
    这个是**语音功能**要的视图 —— 多一个 `usable`（配置齐了**且**服务商可用），
    前端据此决定「试听」按钮亮不亮。`current` 是当前选中的那一个。
    """
    provider = voice_prefs.tts_provider_or_none()
    current = voice_prefs.current_prefs().voice_id
    items = [_voice_row(profile, provider) for profile in _profiles()]
    return ok(
        {
            "items": items,
            "total": len(items),
            "current": current,
            "provider": provider.name if provider is not None else "",
            "enabled": voice_policy.voice_enabled(),
            "usable": provider is not None,
        }
    )


@bp.post("/api/voice/voices/<voice_id>/preview")
def preview_voice(voice_id: str):
    """试听一个音色：合成示例句（或给定的句子），返回可直接播的 URL。

    请求示例：
        POST /api/voice/voices/vp_teacher_shen/preview
        {"text": "同学们好", "force": false}

    重复点击不重复计费：命中缓存时 `cached` 为 true，界面据此提示
    「这段是缓存」而不是又花了钱（P2-A5）。
    """
    profile = assets.voice_or_404(voice_id)
    body = json_body(required=False)
    return ok(
        assets.preview(
            profile,
            provider=voice_prefs.tts_provider(),
            text=str(body.get("text") or ""),
            force=_flag(body.get("force")),
        )
    )


@bp.get("/api/voice/voices/<voice_id>/preview")
def play_preview(voice_id: str):
    """试听音频本体（POST 合成了什么，这里就播什么）。

    请求示例：
        GET /api/voice/voices/vp_teacher_shen/preview?v=a1b2c3d4
    """
    return _send_audio(assets.preview_file(voice_id, str(request.args.get("v") or "")))


# --- 单句合成 ---


@bp.post("/api/voice/tts")
def synthesize_text():
    """单句合成（P2-A1）。

    请求示例：
        POST /api/voice/tts
        {"text": "学习率决定了每一步走多远", "voiceId": "vp_teacher_shen",
         "speed": 1.0, "tone": "expressive"}

    返回 `{url, durationMs, cached, voiceId}`：`url` 指到上面的试听路由，
    前端拿到就能塞进 `<audio>`。

    `speed` / `tone` 原样进合成、也进缓存键：响应里回显它们，是为了让调用方
    确认「我要的那一版」就是「拿回来的这一版」—— 这两个参数错了不会报错，
    只会听到一个不对的声音。
    """
    body = json_body()
    text = str(body.get("text") or "").strip()
    if not text:
        raise ValidationError("text 不能为空")
    if len(text) > MAX_TTS_CHARS:
        raise ValidationError(f"单句合成最多 {MAX_TTS_CHARS} 字；整段讲稿请用整课预合成")

    voice_id = str(body.get("voiceId") or "").strip()
    if not voice_id:
        voice_id = _default_voice_id()
    if not voice_id:
        raise ValidationError("请求里没有 voiceId，且当前没有选中的音色，请先在设置页选一个")
    profile = assets.voice_or_404(voice_id)

    speed = _float_of(body.get("speed"))
    tone = voice_prefs.tone_of(str(body.get("tone") or ""))
    return ok(
        assets.preview(
            profile,
            provider=voice_prefs.tts_provider(),
            text=text,
            speed=speed,
            tone=tone,
            force=_flag(body.get("force")),
            ref="tts",
        )
        | {"speed": speed, "tone": tone}
    )


# --- 整课预合成 ---


@bp.post("/api/courses/<course_id>/narrate")
def narrate_course(course_id: str):
    """整课预合成：入队后台任务，立刻返回。

    请求示例：
        POST /api/courses/c_01H…/narrate?force=1&pageNo=7

    返回的是当前清单（`readyCount / beatCount` **就是**进度）加一个 `started`：
    合成是幂等的，所以「已经合成了几句」不需要另记一个计数器，
    客户端按同一个响应就能画进度条。重复提交不排队（`started: false`）。

    `VOICE_ENABLED=false` 时什么都不做，响应里 `enabled: false` 且带
    `fallback: "text"` —— 部署把这个功能关掉了，这不是错误（P2-G3）。
    """
    course = library.course_or_404(course_id, current_owner_id())
    body = json_body(required=False)
    payload = _narrate_payload(course)

    if not voice_policy.voice_enabled():
        return ok({**payload, "started": False, "running": False})

    started = jobs.submit(
        course.id,
        force=_flag(body.get("force")) or _flag(request.args.get("force")),
        page_no=_int_of(body.get("pageNo") or request.args.get("pageNo")),
    )
    return ok({**payload, "started": started, "running": started or jobs.is_running(course.id)})


@bp.get("/api/courses/<course_id>/audio-manifest")
def audio_manifest(course_id: str):
    """音频清单（P2-B3）—— 前端播放器的唯一输入。

    请求示例：
        GET /api/courses/c_01H…/audio-manifest

    每个 beat 五个契约字段（`pageNo / beatId / textHash / url / durationMs`）
    加播放器要的 `text / estSec / status / subtitles`。没有声音时 `url` 是空串，
    前端据此显示「未合成」，而不是一个点了没反应的播放键。
    """
    course = library.course_or_404(course_id, current_owner_id())
    return ok(_narrate_payload(course) | {"running": jobs.is_running(course.id)})


@bp.get("/api/courses/<course_id>/audio/<beat_id>")
def play_beat(course_id: str, beat_id: str):
    """一个 beat 的音频文件（清单里 `url` 指的就是这里）。

    请求示例：
        GET /api/courses/c_01H…/audio/p3-b1?v=a1b2c3d4

    `?v=` 是内容哈希：重合成之后 URL 会变，浏览器因此不会拿旧缓存接着播
    （讲稿改了声音却没改，是学生能直接听出来的那种错）。文件不在时 404 ——
    清单里那一句的 `url` 本来就是空串。
    """
    course = library.course_or_404(course_id, current_owner_id())
    asset = assets.find_asset(
        course.id, beat_id, settings=voice_prefs.narration_settings(course)
    )
    if asset is None or not asset.available:
        raise NotFound()
    return _send_audio(assets.physical_path(asset.file_path))


# --- 识别与用量 ---


@bp.post("/api/voice/asr")
def transcribe_audio():
    """上传一段音频，返回识别文本（P2 兜底路径 / F2-7）。

    请求示例：
        POST /api/voice/asr   （multipart：file=@ask.wav，fmt=wav）

    接受 `pcm` 与 `wav`：**浏览器的 `MediaRecorder` 出的是 webm/opus，
    上游不认**，所以前端要么录 PCM（`AudioWorklet`），要么走实时语音那条路。
    给 webm 会返回 40001 并说清原因 —— 比传上去然后收到一段乱码文本好。
    """
    if not voice_prefs.asr_enabled():
        raise StateError(
            "语音发言已在设置里关闭，请用文字提问",
            details={"ok": False, "error": "asr_disabled", "fallback": voice_policy.FALLBACK_TEXT},
        )
    audio, fmt, sample_rate = _read_upload()
    provider = voice_prefs.asr_provider()
    started = perf_counter()
    try:
        result = provider.transcribe(audio, fmt=fmt, sample_rate=sample_rate)
    except Exception as exc:
        # 账本留一行（P5-C2）：识别失败也是「调了一次上游」，
        # 而它在用量表里没有位置（没有用量可记）。
        voice_usage.record_failure(
            "asr",
            provider=provider.name,
            model=voice_usage.model_of(provider),
            error_code=type(exc).__name__,
            ref_type="session",
            ref_id="asr",
            latency_ms=_elapsed_ms(started),
        )
        raise
    latency_ms = _elapsed_ms(started)
    # 时长只有上游给了才记账：自己按字节数估一个秒数，那笔账和账单对不上。
    # 没给时长时走 `record_call`：用量表不写（没有可计费的量），但账本要留一行 ——
    # 「这次识别调用了上游」是事实，P5-C2 要的正是它。
    if result.duration_ms:
        voice_usage.record(
            "asr",
            provider=result.provider or provider.name,
            model=voice_usage.model_of(provider),
            units=round(result.duration_ms / 1000),
            ref_type="session",
            ref_id="asr",
            latency_ms=latency_ms,
        )
    else:
        voice_usage.record_call(
            "asr",
            provider=result.provider or provider.name,
            model=voice_usage.model_of(provider),
            ref_type="session",
            ref_id="asr",
            latency_ms=latency_ms,
        )
    return ok(
        {
            "text": result.text,
            # 整段上传没有「中间结果」这一说：拿到就是定稿
            "final": True,
            "durationMs": int(result.duration_ms or 0),
            "provider": result.provider or provider.name,
            "segments": [
                {
                    "text": item.text,
                    "startMs": int(item.start_ms),
                    "endMs": int(item.end_ms),
                    "final": bool(item.final),
                }
                for item in (result.segments or ())
            ],
        }
    )


@bp.get("/api/voice/usage")
def get_usage():
    """用量与估算费用（P2-A11 / F2-10）。

    请求示例：
        GET /api/voice/usage?refType=course&refId=c_01H…

    金额是**估算**（价目表在配置里，没配就是 0 且 `priced` 为 false）——
    界面据此说「未配置单价」，而不是显示一个 `¥0.00` 让人以为这节课不要钱。
    """
    ref_type = str(request.args.get("refType") or "").strip()
    ref_id = str(request.args.get("refId") or "").strip()
    return ok(
        voice_usage.summary(ref_type=ref_type or None, ref_id=ref_id or None)
        | {"enabled": voice_policy.voice_enabled()}
    )


# --- WebSocket ---


@bp.post("/api/voice/ticket")
def issue_ticket():
    """签发一张实时语音的会话票据（P2-F4）。

    请求示例：
        POST /api/voice/ticket
        → {"ticket": "…", "ttlSec": 60}

    建连之前先来这一趟，WS 那条路才认。**这不是鉴权**（本项目还没有账号体系，
    owner 来自请求头），它挡的是「不经过 HTTP 就直接开语音桶」：语音开关、
    上游配置、归属人三件事在这里判一次，WS 那边就不必再判 —— 也就不会
    出现「接口层说关着、WS 说能用」这种两边不一致的状态。

    `VOICE_ENABLED=false` → 40302；上游没配好 → 40201：两个都带 `fallback`，
    前端拿到的答复与调其它语音接口时完全一致。凭据（`X-Api-Key` 那几样）
    只存在于服务端，票据里只有一串随机数，不含任何凭据信息。
    """
    if not voice_policy.voice_enabled():
        raise voice_policy.disabled()
    # 上游没配好就别发票据：那张票拿去也建不起会话，而「建不起来」这件事
    # 在这里说比在 WS 握手里说要清楚得多（那里只能回一个连接失败）
    voice_prefs.realtime_provider()
    return ok(tickets.issue(current_owner_id(), ttl=tickets.TICKET_TTL_SECONDS))


@bp.route("/ws/voice/realtime", websocket=True)
def realtime_voice():
    """实时语音的双向通道（P2-B1 / §4.2）。

    请求示例：
        GET /ws/voice/realtime?ticket=<POST /api/voice/ticket 拿到的>
        （浏览器里是 `new WebSocket(`ws://${location.host}/ws/voice/realtime?ticket=…`)`）

    上行走 `start / audio / barge_in / stop`，下行走
    `ready / asr / reply / audio / barge_in_ack / error / done`：
    **前端不该出现任何上游事件名**，翻译在 `services/voice/realtime.py`。

    这条路由只做四件事：核销票据、接上 socket、把两端接起来、收工时收摊。
    所有协议语义都在 `RealtimeChannel` 里 —— 因为 Flask 的测试客户端
    做不了 WebSocket 升级，契约测试（P2-B1 的全序列）只能打在那一层上，
    逻辑留在这里就等于没测到。

    票据要在 `accept()` **之前**核销：核销失败时我们抛出去，走的是普通的
    错误信封（HTTP 401），浏览器连 101 都拿不到 —— 那才是「握手被拒绝」。
    先 accept 再拒绝的话，客户端看到的是一条连上了又立刻断掉的 socket，
    前端只能报一句「连接失败」，说不出是为什么。
    """
    from simple_websocket import ConnectionClosed, Server

    from app.services.voice.realtime import RealtimeChannel

    owner_id = tickets.consume(str(request.args.get("ticket") or ""))

    try:
        socket = Server.accept(request.environ)
    except ConnectionClosed:  # pragma: no cover - 握手失败，客户端已经走了
        return ""

    transport = _SocketTransport(socket)
    channel = RealtimeChannel(
        voice_prefs.realtime_provider(),
        emit=transport.send,
        # 课程 id 在 `start` 里才到（见 realtime.py 的 `_resolve_course`）
        resolve_course=_course_of,
        session_id=str(request.args.get("sessionId") or ""),
        # 票据上的归属人，不是请求头：并发上限（P2-F5）认的是「谁开的会话」，
        # 而请求头谁都能改
        owner_id=owner_id,
    )
    # run() 自己会 close（正常结束、断开、出错三条路都走它的 finally）
    channel.run(transport)
    return ""


class _SocketTransport:
    """`simple_websocket.Server` → 语义层的 `Transport`。

    唯一的工作是把「对端断开」翻成我们自己的 `ChannelClosed`：语义层不该
    import 任何 WebSocket 库的类型，否则契约测试就得连带跑一个真 WebSocket
    客户端，而测一条协议不该先起一个端口。
    """

    def __init__(self, socket) -> None:
        self._socket = socket

    def receive(self, timeout: float):
        return self._call("receive", timeout=timeout)

    def send(self, data: str | bytes) -> None:
        self._call("send", data)

    def _call(self, method: str, *args, **kwargs):
        """调底层 socket，把「对端断开」翻成 `ChannelClosed`。翻译只此一处。

        局部 import：既有「厂商库只在用得到时加载」的意思，
        也让本模块在没有装 WebSocket 支持时仍能被导入（路由不会被访问到）。
        """
        from simple_websocket import ConnectionClosed

        from app.services.voice.realtime import ChannelClosed

        try:
            return getattr(self._socket, method)(*args, **kwargs)
        except ConnectionClosed as exc:
            raise ChannelClosed(str(exc)) from exc


# --- 内部 ---


def _profiles():
    from app.models import VoiceProfile

    return list(VoiceProfile.query.order_by(VoiceProfile.id).all())


def _voice_row(profile, provider) -> dict:
    """一个音色在**语音功能**眼里的样子：多了 `usable`。

    `usable` 是「配置齐了**且**服务商可用」两件事的合取 —— 缺任何一半，
    试听按钮点下去都是 40201 或 40001，前端据此把它置灰。
    """
    row = profile.to_dict()
    row["usable"] = bool(profile.configured and provider is not None)
    return row


def _default_voice_id() -> str:
    profile = voice_prefs.voice_profile()
    return profile.id if profile is not None else ""


def _narrate_payload(course) -> dict:
    """清单 + 这次预合成用哪套参数。两个端点的共同主体。"""
    return assets.manifest(
        course,
        voice_prefs.narration_settings(course),
        provider=voice_prefs.tts_provider_or_none(),
    )


def _course_of(course_id: str):
    """`start.context.courseId` → 课程。查不到就当作没有上下文。

    这里**不报错**：学生说错一个 courseId 不该让整节课连不上实时语音，
    顶多是老师不知道现在上到第几页（P2-B2 的降级精神）。
    """
    from app.common.errors import NotFoundError

    course_id = str(course_id or "").strip()
    if not course_id:
        return None
    try:
        return library.course_or_404(course_id, current_owner_id())
    except NotFoundError:
        logger.debug("实时语音：上下文里的课程不存在 course=%s", course_id)
        return None


def _send_audio(path: Path | None):
    """把一个音频文件发给浏览器。路径已由 `assets` 判过界（不在音频根下的拿不到）。"""
    if path is None or not path.is_file():
        raise NotFound()
    return send_file(
        path,
        mimetype=MIMETYPES.get(path.suffix.lstrip(".").lower(), "application/octet-stream"),
        # 支持 Range：没有它，进度条拖不动
        conditional=True,
        max_age=3600,
    )


def _read_upload() -> tuple[bytes, str, int]:
    """取上传的音频 + 它的格式与采样率。

    `fmt` 的判定顺序：显式参数 → 文件名后缀 → content-type → 默认 wav。
    不做真正的内容嗅探：判错了也只会由 Provider 报一句「只接受 pcm / wav」，
    而在这里猜格式的误判率比明说出来更高。
    """
    upload = request.files.get("file")
    if upload is not None:
        audio = upload.read()
        name = str(upload.filename or "")
        declared = str(request.form.get("fmt") or request.args.get("fmt") or "")
        mime = str(upload.mimetype or "")
    else:
        audio = request.get_data(cache=False)
        name = ""
        declared = str(request.args.get("fmt") or "")
        mime = str(request.content_type or "")
    if not audio:
        raise ValidationError("没有收到音频数据")

    fmt = (declared or _suffix_of(name) or _suffix_of(mime) or "wav").strip().lower()
    if fmt not in UPLOAD_FORMATS:
        raise ValidationError(
            f"只接受 pcm / wav 音频，收到 {fmt!r}；"
            "浏览器的 MediaRecorder 默认录成 webm/opus，请改用 PCM 采集，或走实时语音那条路",
            details={"fmt": fmt, "accepted": list(UPLOAD_FORMATS)},
        )
    sample_rate = _int_of(request.form.get("sampleRate") or request.args.get("sampleRate")) or 16000
    return audio, fmt, sample_rate


def _suffix_of(value: str) -> str:
    """`ask.wav` / `audio/wav` / `audio/webm;codecs=opus` → 后缀。"""
    text = str(value or "").split(";")[0].strip().lower()
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text.rsplit(".", 1)[-1] if "." in text else text


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _float_of(value) -> float | None:
    """`speed` 归一到 [0.5, 2.0]。空值算「没给」，交给音色自己的语速。"""
    if value is None or value == "":
        return None
    try:
        speed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("speed 必须是 0.5 ~ 2.0 之间的数") from exc
    if speed <= 0:
        raise ValidationError("speed 必须是 0.5 ~ 2.0 之间的数")
    return max(0.5, min(2.0, speed))


def _int_of(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("参数必须是整数") from exc


def _elapsed_ms(started: float) -> int:
    """从 `started`（`perf_counter()` 的读数）到现在多少毫秒。

    记账要的是**这一次调用的耗时**，所以用的是单调时钟而不是 `time.time()`：
    后者在系统对时跳一下的时候会给出负数或者一个离谱的大数，
    而它会原样进 `model_calls.latency_ms`（`assets.py` 里那份是同名同姓的兄弟）。
    """
    return int((perf_counter() - started) * 1000)


@bp.errorhandler(AppError)
def _app_error(exc: AppError):
    """语音接口的错误一律带 `fallback`（P2-B2：「任何 error 都必须携带」）。

    挂在**蓝图**上而不是全局：`fallback` 是语音的概念（退到文字/浏览器），
    课程接口的 404、生成接口的 40001 带上它只会让前端多一个没意义的字段 ——
    而「让所有接口都多一个字段」正是那种一旦加上就再也拿不掉的东西。
    """
    return voice_policy.with_fallback(exc).to_envelope()


__all__ = ["bp"]
