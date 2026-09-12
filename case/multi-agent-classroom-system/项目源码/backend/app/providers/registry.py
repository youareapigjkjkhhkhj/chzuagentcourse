"""Provider 注册表（P0 §6）。

两个入口，职责不同 —— 这个区分是整个设置页行为的地基：

- `get_llm(name)` / `get_tts(name)` **只做查找**：拿到就是拿到，
  哪怕是「一行凭据都没配」的空壳。设置页靠它列出所有服务商、
  逐个显示「已配置 / 未配置」、跑探活。
- `current_llm()` / `current_tts()` **只返回能用的**：选了服务商却没填 Key，
  直接抛 40201，而不是悄悄降级到 Mock。业务代码用这一组。

注册表本身不碰数据库、不碰 Flask —— 装配在 app/services/provider_registry.py。
这样它可以被单独构造与测试。
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, cast

from app.common.errors import NotFoundError
from app.providers.base import (
    ASRProvider,
    BaseProvider,
    LLMProvider,
    RealtimeProvider,
    TTSProvider,
    not_configured,
)

#: 四类能力。realtime 与 tts 是两条独立的通道（帧编码、音色池都不同）。
KINDS: tuple[str, ...] = ("llm", "tts", "asr", "realtime")

#: 全部离线可用的兜底服务商名。
MOCK_NAME = "mock"

_KIND_CLASS: dict[str, type[BaseProvider]] = {
    "llm": LLMProvider,
    "tts": TTSProvider,
    "asr": ASRProvider,
    "realtime": RealtimeProvider,
}


def join_names(names: Iterable[str]) -> str:
    """把一批候选服务商名拼成人话。空列表也要给个说法，不能留白。"""
    joined = "、".join(names)
    return joined or "（无）"


class ProviderRegistry:
    """按能力分组存放 Provider 实例。"""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        settings: Callable[[str], Any] | None = None,
        default_llm: str = "",
    ) -> None:
        #: 配置快照（LLM_PROVIDER / VOLC_*_API_KEY …）。注册表只读它，不写。
        self.config: Mapping[str, Any] = config or {}
        #: 读「用户在设置页选了什么」的回调。注入而不是自己查库 ——
        #: 注册表因此不依赖 Flask / 数据库，可以单独构造与测试。
        self._settings = settings
        #: providers 表里标记为启用的那家（由装配方查好传进来）。
        #: 它是「设置页从没被打开过」时的答案 —— 种子数据默认启用 DeepSeek，
        #: 否则首次启动会落到 mock，用户看到的是一片「未启用」。
        self._default_llm = default_llm
        self._groups: dict[str, dict[str, BaseProvider]] = {kind: {} for kind in KINDS}

    # --- 注册 ---

    def register(self, provider: BaseProvider) -> BaseProvider:
        """按 name 覆盖式注册。后注册的赢 —— 装配时用「DB 覆盖 .env」的语义。"""
        if provider.kind not in self._groups:
            raise ValueError(f"未知的 Provider 类型 {provider.kind!r}，可选：{list(KINDS)}")
        expected = _KIND_CLASS[provider.kind]
        if not isinstance(provider, expected):
            raise TypeError(f"{provider.name} 声明为 {provider.kind}，但类型不是 {expected.__name__}")
        self._groups[provider.kind][provider.name] = provider
        return provider

    # --- 查找（设置页 / 探活用；不检查 configured）---

    def get(self, kind: str, name: str) -> BaseProvider:
        group = self._groups.get(kind)
        if group is None:
            raise ValueError(f"未知的 Provider 类型 {kind!r}，可选：{list(KINDS)}")
        provider = group.get(name)
        if provider is None:
            raise NotFoundError(
                f"没有名为 {name!r} 的 {kind} 服务商；可选：{join_names(self.names(kind))}",
                details={"kind": kind, "requested": name, "available": self.names(kind)},
            )
        return provider

    # 下面八个方法是同一件事的两组包装：
    #   get_*     只查找，拿到就是拿到（设置页用）
    #   current_* 只返回能用的（业务用），没配好会抛 40201
    # 每组都只是 cast 一下的薄壳：register() 已经校验过类型，
    # 但「按字符串分组存」在类型上看不见，不收窄回来每个调用点都得自己 cast。
    # （不用 `type[T]` 参数做类型见证：mypy 会判 type-abstract，
    #   而这些接口本来就是抽象的。）

    def get_llm(self, name: str) -> LLMProvider:
        return cast(LLMProvider, self.get("llm", name))

    def get_tts(self, name: str) -> TTSProvider:
        return cast(TTSProvider, self.get("tts", name))

    def get_asr(self, name: str) -> ASRProvider:
        return cast(ASRProvider, self.get("asr", name))

    def get_realtime(self, name: str) -> RealtimeProvider:
        return cast(RealtimeProvider, self.get("realtime", name))

    def names(self, kind: str) -> list[str]:
        return sorted(self._groups[kind])

    def available(self) -> dict[str, dict[str, dict]]:
        """给 /api/capabilities 与设置页：{能力: {名字: 描述}}。"""
        return {
            kind: {name: provider.describe() for name, provider in sorted(group.items())}
            for kind, group in self._groups.items()
        }

    # --- 取当前可用（业务代码用这一组）---

    def current(self, kind: str, name: str | None = None) -> BaseProvider:
        """取一个**能直接用**的 Provider；不能直接用就抛 40201。"""
        resolved = (name or self.default_name(kind)).strip()
        provider = self.get(kind, resolved)
        if not provider.configured:
            raise not_configured(provider)
        return provider

    def read_setting(self, key: str) -> Any:
        """读一项设置。没注入回调（纯内存使用）时返回 None。"""
        if self._settings is None:
            return None
        return self._settings(key)

    def active_llm_name(self) -> str:
        """当前该用哪家文本模型。四级回落，每一级的理由：

        1. **设置页的选择**（settings_kv）—— 用户刚刚点下的决定。
           被它覆盖掉时用户会以为「我明明选了」，那才是真的坏。
        2. **.env 的 LLM_PROVIDER** —— 部署方的选择。没动过设置页时由它说了算。
        3. **providers 表里 enabled 的那行** —— 种子数据默认启用 DeepSeek。
           没有这一级，全新安装会落到 mock，设置页五张卡全是「未启用」，
           与原型不符，也让「点一下就能用」变成「得先找到哪个开关」。
        4. **mock** —— 谁都没配时的离线兜底（AGENTS.md §23）。
        """
        # 局部 import：注册表本体保持零依赖，而键名的出处仍然只有一处
        from app.models.settings_kv import KEY_ACTIVE_PROVIDER

        value = self.read_setting(KEY_ACTIVE_PROVIDER)
        if isinstance(value, str) and value.strip():
            return value.strip()

        configured = str(self.config.get("LLM_PROVIDER") or "").strip()
        if configured:
            return configured

        return self._default_llm.strip() or MOCK_NAME

    # current_* 必须走 current()：直接查表会绕过「没配好就报 40201」这道闸门，
    # 结果是业务侧拿到一个空壳 Provider，调用时才炸在上游。

    def current_llm(self, name: str | None = None) -> LLMProvider:
        return cast(LLMProvider, self.current("llm", name))

    def current_tts(self, name: str | None = None) -> TTSProvider:
        return cast(TTSProvider, self.current("tts", name))

    def current_asr(self, name: str | None = None) -> ASRProvider:
        return cast(ASRProvider, self.current("asr", name))

    def current_realtime(self, name: str | None = None) -> RealtimeProvider:
        return cast(RealtimeProvider, self.current("realtime", name))

    # --- 默认名字的解析规则 ---

    def default_name(self, kind: str) -> str:
        """没显式指定时用哪个 Provider。

        规则按能力而分，理由写在下面每个分支里 —— 这不是随手拍的。
        """
        if kind == "llm":
            # 文本生成是最贵、最可换的能力：用户的选择必须被尊重，
            # 缺 Key 就报 40201，绝不悄悄换一家。
            return self.active_llm_name()
        if kind == "tts":
            return "volc_tts" if self.config.get("VOLC_TTS_API_KEY") else MOCK_NAME
        if kind == "asr":
            return "volc_asr" if self.config.get("VOLC_ASR_API_KEY") else MOCK_NAME
        if kind == "realtime":
            return "volc_realtime" if self.config.get("VOLC_REALTIME_API_KEY") else MOCK_NAME
        raise ValueError(f"未知的 Provider 类型 {kind!r}，可选：{list(KINDS)}")

    # --- 调试 ---

    def __repr__(self) -> str:
        counts = ", ".join(f"{kind}={len(group)}" for kind, group in self._groups.items())
        return f"<ProviderRegistry {counts}>"


__all__ = ["KINDS", "MOCK_NAME", "ProviderRegistry", "join_names"]
