"""Provider 抽象层（P0 §6）。

三条硬约束：
1. 业务代码只依赖本模块的接口，**不 import 任何厂商 SDK**（AGENTS.md §14.2）。
   厂商细节全部关在 app/providers/<kind>/ 里，换一家只改一个文件。
2. 返回值一律是不可变 dataclass —— 调用方改不到 Provider 的内部状态，
   也不会因为拿到同一个对象引用而互相踩。
3. 失败按类型分流：未配置 40201 / 超时 50401 / 上游失败 50201。
   上层用 `except` 捕获，不做字符串匹配。

凭据一律装进 `Secret`：它存在的唯一理由是让 repr / 日志打不出原文。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable, Iterator, Mapping, Sequence

from app.common.errors import AppError, UpstreamError

# --- 错误 ---


class ProviderError(UpstreamError):
    """Provider 调用失败的通用形态（50201）。"""

    code = 50201
    http_status = 502


class ProviderNotConfiguredError(ProviderError):
    """能力被调用，但凭据 / 接入地址还没配（40201，P0-B3）。

    刻意用 4xxxx 而不是 5xxxx：这是「去设置页补一下就好」的配置问题，
    不是服务端故障 —— 前端据此弹引导，而不是弹「服务器错误」。
    """

    code = 40201
    http_status = 400

    def to_envelope(self):
        """40201 的 data 不套 details（P0 §4.2 把形状钉死了）：

            data: {ok: false, error: "missing_api_key"}

        前端靠这三个字决定「弹引导去设置页」，所以多包一层就等于让它
        多写一行 `data.details.error`，也更容易写错。
        extra 的 provider / missing 是额外信息（前端可用来指名道姓），
        不影响契约里写明的 ok 与 error。
        """
        from app.common.response import fail_with_data

        return fail_with_data(self.code, dict(self.details or {}), self.message, self.http_status)


class ProviderTimeoutError(ProviderError):
    """上游超时（50401）。"""

    code = 50401
    http_status = 504


# --- 明文包装 ---


class Secret:
    """把明文 Key 包起来，防止 repr / 日志无意间打出原文。"""

    __slots__ = ("_value",)

    def __init__(self, value: str | None = None) -> None:
        self._value = str(value or "")

    def reveal(self) -> str:
        """取出明文。调用点越少越好 —— 理想情况下只有构造上游客户端那一处。

        顺手把它登记进日志的脱敏表：凭据真正被拿出来用，就意味着它马上
        会出现在 HTTP 头里，而上游的报错文案有可能把它原样抄回来
        （见 AGENTS.md §4.1：日志里不得出现 Key 原文，含异常栈）。
        """
        from app.common.logging import register_secret

        register_secret(self._value)
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "<Secret set>" if self._value else "<Secret empty>"

    __str__ = __repr__


# --- 结果类型 ---


@dataclass(frozen=True)
class LLMResult:
    """一次文本生成的完整结果。"""

    text: str
    model: str = ""
    provider: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    finish_reason: str = ""


@dataclass(frozen=True)
class ProbeResult:
    """探活结果。

    探活只回答「这套配置现在能不能用」，所以它**永不抛异常** ——
    把失败原因装进 error / error_code，让设置页原样显示。
    """

    ok: bool
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    error: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class Subtitle:
    """TTS 返回的字幕片段（用于讲稿与音频对齐）。"""

    text: str
    start_ms: int = 0
    end_ms: int = 0


@dataclass(frozen=True)
class TTSResult:
    """一次语音合成的结果。"""

    audio: bytes
    fmt: str = "mp3"
    duration_ms: int = 0
    provider: str = ""
    subtitles: Sequence[Subtitle] = field(default_factory=tuple)


@dataclass(frozen=True)
class Voice:
    """一个可选音色。"""

    id: str
    name: str = ""
    gender: str = ""
    style: str = ""
    provider: str = ""
    sample_url: str = ""


@dataclass(frozen=True)
class ASRSegment:
    """识别出的一个片段。final=False 是中间结果，前端可以边听边显示。"""

    text: str
    start_ms: int = 0
    end_ms: int = 0
    final: bool = False


@dataclass(frozen=True)
class ASRResult:
    """一段音频的完整识别结果。"""

    text: str = ""
    segments: Sequence[ASRSegment] = field(default_factory=tuple)
    duration_ms: int = 0
    provider: str = ""


# --- 基类 ---


class BaseProvider:
    """所有 Provider 的共同身份。

    刻意不是 ABC：它自己不声明任何能力，所以没有抽象方法 ——
    抽象性交给下面四类（LLMProvider / TTSProvider / ASRProvider / RealtimeProvider）。

    子类可以覆盖 `configured` 属性，让它由 `missing_config()` 推导 ——
    这样「缺什么」和「能不能用」永远只有一个事实来源。
    """

    kind: ClassVar[str] = ""
    #: 实例名（deepseek / volc_tts / mock …）。给个类级默认值，
    #: 这样不实例化也能问出「你是干什么的」。
    name: str = ""
    #: 这个适配器的能力是否已经实现。P0 只用它标注语音三件套的骨架 ——
    #: 凭据填齐了、代码还没写，这时报「已就绪」就是假绿灯：
    #: 用户会带着一个打勾的卡片去上课，然后发现没有声音。
    implemented: ClassVar[bool] = True

    def __init__(self, name: str = "", *, configured: bool = True, **options: Any) -> None:
        self.name = name or type(self).__name__
        self._configured = bool(configured)
        self.options = dict(options)

    @property
    def configured(self) -> bool:
        """凭据与接入地址是否齐备。不齐备时调用会报 40201。"""
        return self._configured

    def missing_config(self) -> list[str]:
        """还缺哪些配置项（给人看的名字，不是环境变量名）。用于 40201 文案。

        默认「什么都不缺」；自行判定的子类覆盖本方法即可。
        """
        return []

    def describe(self) -> dict:
        """给 /api/capabilities 与设置页用的自我描述。绝不含凭据。"""
        return {
            "name": self.name,
            "kind": self.kind,
            "configured": self.configured,
            "implemented": self.implemented,
        }

    def test(self) -> ProbeResult:
        """探活。默认答「这类能力还没实现探活」。

        设置页的「测试连接」按钮对四类能力是同一个按钮，而 P0 只要求
        文本模型真发一次请求（P0-A5）。默认实现放在基类而不是让调用方
        逐个 hasattr：没实现的能力要能**明确地**说不支持，
        而不是让接口层在 AttributeError 里猜。
        """
        return ProbeResult(
            ok=False,
            error="该能力暂不支持测试连接",
            error_code="probe_unsupported",
            provider=self.name,
        )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name} configured={self.configured}>"


class LLMProvider(BaseProvider, ABC):
    """文本生成。"""

    kind: ClassVar[str] = "llm"

    def __init__(
        self,
        name: str = "",
        *,
        configured: bool = True,
        default_model: str = "",
        **options: Any,
    ) -> None:
        super().__init__(name, configured=configured, **options)
        self.default_model = default_model

    def describe(self) -> dict:
        info = super().describe()
        info["model"] = self.default_model
        return info

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        **options: Any,
    ) -> LLMResult:
        """一次对话补全。json_schema 非空时要求返回可解析的 JSON。

        `timeout` 是**这一次调用**的秒数上限，None 表示用适配器自带的缺省值。
        它必须按请求下发到传输层（P1-F4）：生成管线并发写多页，各自计时，
        谁慢谁超时 —— 在外层起看门狗线程去掐，会留下永远等不到结果的线程。
        适配器若无法表达单次超时，可以忽略它（此时由自身的传输超时兜底）。
        """

    @abstractmethod
    def test(self) -> ProbeResult:
        """探活。永不抛异常。"""

    def chat_stream(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        **options: Any,
    ) -> Iterator[str]:
        """逐段产出文本。

        默认实现是「非流式降级」：上游不支持流式时，业务侧仍能拿到内容，
        只是首字节晚一点 —— 比直接报错好。
        """
        yield self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **options,
        ).text


class TTSProvider(BaseProvider, ABC):
    """语音合成。"""

    kind: ClassVar[str] = "tts"

    def __init__(
        self,
        name: str = "",
        *,
        configured: bool = True,
        default_voice: str = "",
        audio_format: str = "mp3",
        sample_rate: int = 24000,
        **options: Any,
    ) -> None:
        super().__init__(name, configured=configured, **options)
        self.default_voice = default_voice
        self.audio_format = audio_format
        self.sample_rate = sample_rate

    def describe(self) -> dict:
        info = super().describe()
        info["format"] = self.audio_format
        info["sampleRate"] = self.sample_rate
        return info

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> TTSResult:
        """整段合成。"""

    @abstractmethod
    def stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> Iterator[bytes]:
        """流式合成：边合成边出音频块，避免长讲稿等整段。"""

    @abstractmethod
    def list_voices(self) -> list[Voice]:
        """该服务商可用的音色。"""


class ASRProvider(BaseProvider, ABC):
    """语音识别。"""

    kind: ClassVar[str] = "asr"

    @abstractmethod
    def transcribe(
        self,
        audio: bytes,
        *,
        fmt: str = "wav",
        sample_rate: int = 16000,
        **options: Any,
    ) -> ASRResult:
        """整段识别。"""

    @abstractmethod
    def stream(
        self,
        chunks: Iterable[bytes],
        *,
        fmt: str = "pcm",
        sample_rate: int = 16000,
        **options: Any,
    ) -> Iterator[ASRSegment]:
        """流式识别：边收音频边出中间结果。"""


class RealtimeProvider(BaseProvider, ABC):
    """端到端实时语音（全双工）。

    注意：实时语音有自己的音色池，与 TTSProvider 的音色**不通用**
    （见 app/models/voice_profile.py 的说明）。
    """

    kind: ClassVar[str] = "realtime"

    @abstractmethod
    def start_session(self, **options: Any) -> Any:
        """建立一次会话。P2 实现。"""

    @abstractmethod
    def list_voices(self) -> list[Voice]:
        """该服务商可用的音色（来自实时语音专属音色池）。"""


def not_configured(provider: BaseProvider, what: str = "") -> ProviderNotConfiguredError:
    """统一的 40201 文案：说清是谁、缺什么、去哪儿补。

    `provider.name` 与缺项名都是配置项的名字，不含凭据本身 ——
    这句话会原样显示给用户，也会进日志，所以绝不能带上 Key。
    """
    missing = provider.missing_config()
    return ProviderNotConfiguredError(
        f"服务商 {provider.name} 未配置{what or '、'.join(missing) or 'API Key'}，"
        "请到「设置」页填写后再试",
        details={
            "ok": False,
            "error": "missing_api_key",
            "provider": provider.name,
            "missing": missing,
        },
    )


__all__ = [
    "ASRProvider",
    "ASRResult",
    "ASRSegment",
    "AppError",
    "BaseProvider",
    "LLMProvider",
    "LLMResult",
    "ProbeResult",
    "ProviderError",
    "ProviderNotConfiguredError",
    "ProviderTimeoutError",
    "RealtimeProvider",
    "Secret",
    "Subtitle",
    "TTSProvider",
    "TTSResult",
    "Voice",
    "not_configured",
]
