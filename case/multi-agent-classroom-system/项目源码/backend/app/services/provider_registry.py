"""Provider 注册表的应用级装配（P0 §6）。

职责边界：
- app/providers/registry.py —— 纯内存查找表，不碰 Flask、不碰数据库
- 本模块                   —— 把「配置 + providers 表的行」装配成那个表

三条约束：
1. **懒加载**：create_app 不碰数据库。迁移还没跑时服务也要能起来。
2. **每 app 一份**：缓存在 app.extensions，测试里两个 app 不会互相串。
3. **容错**：表不存在、密文解不开（换过 FERNET_KEY），都只降级不崩溃 ——
   一个坏掉的凭据不该让整个服务起不来。

取值优先级（每个字段独立判断）：
    providers 表（设置页写的） > .env（部署缺省） > 该能力无可用 Provider
表里空着的字段用 .env 补，否则会出现「.env 全配好了、表里也有一行但字段是空的」
→ 报 40201 的诡异状态。

注意 .env 的 LLM_API_KEY 只补给 `.env` 里选中的那一家（LLM_PROVIDER），
免得把 DeepSeek 的 Key 顺手发给 OpenAI 的端点。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from flask import Flask, current_app

from app.common.context import real_app
from app.common.errors import NotFoundError
from app.common.logging import get_logger
from app.extensions import db
from app.models import Provider
from app.providers.asr.mock import MockASR
from app.providers.llm.mock import MockLLM
from app.providers.llm.openai_compatible import OpenAICompatibleLLM
from app.providers.registry import KINDS, MOCK_NAME, ProviderRegistry, join_names
from app.providers.tts.mock import MockRealtime, MockTTS

logger = get_logger("app.services.providers")

#: 缓存在 app.extensions 里的键。
EXTENSION_KEY = "provider_registry"


# --- 对外入口 ---


def get_registry() -> ProviderRegistry:
    """取当前 app 的注册表，没有就装配一份。"""
    app = real_app()
    registry = app.extensions.get(EXTENSION_KEY)
    if registry is None:
        registry = _build(app)
        app.extensions[EXTENSION_KEY] = registry
    return registry


def refresh_registry() -> ProviderRegistry:
    """设置页改完服务商后调用：重新装配，让新配置立刻生效。"""
    app = real_app()
    registry = _build(app)
    app.extensions[EXTENSION_KEY] = registry
    logger.info("Provider 注册表已重建：%s", registry)
    return registry


def registry_from_config(cfg: Mapping[str, Any]) -> ProviderRegistry:
    """只按配置装配，**不读数据库** —— 启动自检用。

    启动那一刻数据库可能还没迁移好，而自检不该因此失败；
    运行期的完整状态（含设置页写进 providers 表的东西）以 get_registry() 为准。
    """
    registry = ProviderRegistry(config=cfg, settings=lambda _key: None)
    _register_mocks(registry)
    _build_llm(registry, dict(cfg), rows=[])
    _build_speech(registry, dict(cfg))
    return registry


# --- 启动自检（F0-8）---


def self_check(registry: ProviderRegistry | None = None) -> dict:
    """离线自检：只回答「配置自不自洽」，不发任何网络请求。

    为什么不在启动时探活：那会让启动依赖网络 —— 断网时服务起不来，
    是最难排查的故障。真连不连得上，由设置页的「测试连接」按钮负责说。
    """
    registry = registry or get_registry()
    issues: list[dict] = []

    active_llm = registry.active_llm_name()
    provider, issue = _resolve(registry, "llm", active_llm, "文本生成")
    if issue is not None:
        issues.append(issue)
    elif not provider.configured:
        missing = "、".join(provider.missing_config()) or "凭据"
        issues.append(
            _issue(
                "error",
                "llm_not_configured",
                f"文本生成当前指向 {active_llm}，但它还缺{missing}；现在生成课程会返回 40201",
            )
        )

    # 语音三项要区分三种「用不了」，混为一谈会误导人到反方向去排查：
    #   选了离线替身 → warning。按设计就该这样（P1 之前没有语音），
    #                  但得说清「没有真实声音」，别等课堂演示才发现
    #   选了真服务商但缺字段 → error。用户是想用真语音的，缺一个字段就
    #                  会在调用时吃 40201，这属于配置错误
    #   字段齐了但适配器还没实现 → warning。P0 的三个语音适配器就是这种
    #                  （见各文件里的 implemented = False）。这不是配置写错，
    #                  所以不是 error；但也绝不能一声不吭地显示成「已就绪」——
    #                  用户会拿着全绿的设置页上课，然后在第一次播放时吃 50201
    # 顺序即优先级：缺字段是用户现在就能动手修的事，先说它。
    for kind in SPEECH_KINDS:
        label = LABELS[kind]
        name = registry.default_name(kind)
        provider, issue = _resolve(registry, kind, name, label)
        if issue is not None:
            issues.append(issue)
        elif name == MOCK_NAME:
            issues.append(
                _issue(
                    "warning",
                    f"{kind}_offline",
                    f"{label}未配置，将使用离线替身（{MOCK_NAME}，没有真实声音）",
                )
            )
        elif not provider.configured:
            missing = "、".join(provider.missing_config()) or "凭据"
            issues.append(
                _issue(
                    "error",
                    f"{kind}_not_configured",
                    f"{label}当前指向 {name}，但它还缺{missing}；调用时会返回 40201",
                )
            )
        elif not provider.implemented:
            issues.append(
                _issue(
                    "warning",
                    f"{kind}_pending",
                    f"{label}已填凭据，但适配器要到 P2 阶段才接通（当前是骨架）；"
                    "现在调用会返回 50201",
                )
            )

    return {
        "ok": not any(issue["level"] == "error" for issue in issues),
        "active": {
            "llm": active_llm,
            "tts": registry.default_name("tts"),
            "asr": registry.default_name("asr"),
            "realtime": registry.default_name("realtime"),
        },
        "providers": registry.available(),
        "issues": issues,
    }


def _resolve(registry: ProviderRegistry, kind: str, name: str, label: str):
    """取一个 Provider；取不到就返回一条 issue，而**不是抛异常**。

    自检自己崩掉，比自检不存在还糟：用户会以为「应用都起不来了」，
    而真正的问题只是某个名字写错了。
    """
    try:
        return registry.get(kind, name), None
    except NotFoundError:
        return None, _issue(
            "error",
            f"{kind}_unknown",
            f"{label}指向了不存在的服务商 {name}；可选：{join_names(registry.names(kind))}",
        )


def _issue(level: str, code: str, message: str) -> dict:
    return {"level": level, "code": code, "message": message}


# --- 能力清单（§4.1，供前端决定哪个入口该置灰）---


#: 各能力的展示名。自检与能力清单共用一份 ——
#: 同一件事在「启动日志」和「能力接口」里叫两个名字，排障时要多绕一圈。
LABELS = {
    "llm": "文本生成",
    "tts": "语音合成",
    "asr": "语音识别",
    "realtime": "实时语音",
}

#: 三种语音能力。顺序即自检日志里的出现顺序。
SPEECH_KINDS = ("tts", "asr", "realtime")


#: 「离线替身」的消息。用它就意味着结果不是真的（没有声音 / 内容只是示例）。
_OFFLINE_REASONS = {
    "llm": "未配置文本模型，将使用离线示例内容",
    "tts": "未配置语音合成，课堂将没有声音",
    "asr": "未配置语音识别，学生无法用语音发言",
    "realtime": "未配置实时语音，AI 同学将使用文字降级链路",
}


def capabilities() -> dict:
    """四类能力「现在能不能用」。

    `available` 与 `offline` 分开，是因为前端要问两个不同的问题：
    - 这个入口能不能点？（available —— 点了不会报 40201）
    - 点下去是不是真的？（offline —— 有没有声音、内容是不是真生成的）

    available 要凭据齐**且**适配器已实现：P0 的语音骨架满足前者不满足后者，
    点下去会吃 50201。offline 此时也是 False —— 它不是「离线替身顶着」，
    而是「谁都没顶」，两者的提示文案完全不同。
    """
    from app.services import settings_service

    report = self_check()
    result: dict[str, dict] = {}
    for kind in KINDS:
        name = report["active"][kind]
        # 自检刚跑过，正常情况这里必然取得到；取不到也只是「这个能力不可用」，
        # 不该让整个 /api/capabilities 变成 5xx —— 那正是前端最需要它的时候。
        provider, _ = _resolve(get_registry(), kind, name, LABELS[kind])

        available = bool(provider is not None and provider.configured and provider.implemented)
        offline = name == MOCK_NAME
        reason = ""
        if not available:
            reason = next(
                (issue["message"] for issue in report["issues"] if issue["code"].startswith(kind)),
                f"{kind} 当前不可用",
            )
        elif offline:
            reason = _OFFLINE_REASONS.get(kind, "")

        result[kind] = {
            "available": available,
            "offline": offline,
            "provider": name,
            "reason": reason,
        }
        if kind == "llm" and provider is not None:
            result[kind]["model"] = str(getattr(provider, "default_model", "") or "")

    return {
        "env": current_app.config.get("ENV_NAME"),
        "version": current_app.config.get("VERSION") or _app_version(),
        "capabilities": result,
        "providers": report["providers"],
        "generation": settings_service.generation_limits(),
    }


def _app_version() -> str:
    from app import __version__

    return __version__


def register_cli(app: Flask) -> None:
    """`flask providers` —— 在终端里看一眼「现在到底配成什么样了」。"""

    @app.cli.command("providers")
    def providers_command() -> None:
        """列出所有服务商与配置状态，并给出可执行的修复建议。"""
        import click

        report = self_check()
        for kind, group in report["providers"].items():
            click.echo(f"[{kind}]")
            for name, info in group.items():
                # 只用中文与 ASCII 打标记：Windows 控制台默认 GBK，
                # 打 ✓ / ✗ 会直接 UnicodeEncodeError 把命令崩掉
                mark = "已配置" if info["configured"] else "未配置"
                extra = f"  model={info['model']}" if info.get("model") else ""
                click.echo(f"  [{mark}] {name}{extra}")
        if report["issues"]:
            click.echo("\n提示：")
            for issue in report["issues"]:
                click.echo(f"  - {issue['message']}")


# --- 装配 ---


def _register_mocks(registry: ProviderRegistry) -> None:
    """Mock 永远在 —— 保证「没网没密钥也能跑通全流程」（AGENTS.md §23）。

    注册在最前，后面的真实 Provider 用同名覆盖它。
    """
    registry.register(MockLLM())
    registry.register(MockTTS())
    registry.register(MockASR())
    registry.register(MockRealtime())


def _build(app: Flask, *, with_database: bool = True) -> ProviderRegistry:
    rows = _provider_rows() if with_database else []
    cfg = dict(app.config)
    registry = ProviderRegistry(
        config=cfg,
        settings=_read_setting,
        # 设置页从未被打开过时，由「种子里标记启用的那一行」决定默认服务商
        default_llm=_enabled_llm_id(rows),
    )
    _register_mocks(registry)
    _build_llm(registry, cfg, rows=rows)
    _build_speech(registry, cfg)
    return registry


def _enabled_llm_id(rows: Sequence[Provider]) -> str:
    """providers 表里 enabled 且是 LLM 的那一行。多行时取 id 最小的，保证可复现。"""
    enabled = sorted(row.id for row in rows if row.kind == "llm" and row.enabled)
    return enabled[0] if enabled else ""


def _build_llm(registry: ProviderRegistry, cfg: dict, *, rows: Sequence[Provider]) -> None:
    active = str(cfg.get("LLM_PROVIDER") or "").strip()
    seen: set[str] = set()

    for row in rows:
        if row.kind != "llm":
            continue
        seen.add(row.id)
        registry.register(OpenAICompatibleLLM(name=row.id, **_llm_fields(cfg, row.id, row)))

    if active and active != MOCK_NAME and active not in seen:
        # 表里还没有这一行（首次启动 / 没跑迁移）：直接用 .env 建起来。
        # 「只配 .env 就能用」这条路不能被数据库拖住。
        registry.register(OpenAICompatibleLLM(name=active, **_llm_fields(cfg, active, None)))


def _build_speech(registry: ProviderRegistry, cfg: dict) -> None:
    """语音三件套：P0 只有骨架，注册进来是为了让设置页能显示「未配置」。"""
    from app.providers.asr.volc_asr import VolcASR
    from app.providers.tts.volc_realtime import VolcRealtime
    from app.providers.tts.volc_tts import VolcTTS

    registry.register(
        VolcTTS(
            api_key=str(cfg.get("VOLC_TTS_API_KEY") or ""),
            endpoint=str(cfg.get("VOLC_TTS_ENDPOINT") or ""),
            resource_id=str(cfg.get("VOLC_TTS_RESOURCE_ID") or ""),
            speaker=str(cfg.get("VOLC_TTS_SPEAKER") or ""),
            audio_format=str(cfg.get("VOLC_TTS_AUDIO_FORMAT") or "mp3"),
            sample_rate=int(cfg.get("VOLC_TTS_SAMPLE_RATE") or 24000),
            speech_rate=int(cfg.get("VOLC_TTS_SPEECH_RATE") or 0),
            enable_subtitle=bool(cfg.get("VOLC_TTS_ENABLE_SUBTITLE")),
        )
    )
    registry.register(
        VolcRealtime(
            api_key=str(cfg.get("VOLC_REALTIME_API_KEY") or ""),
            endpoint=str(cfg.get("VOLC_REALTIME_ENDPOINT") or ""),
            model=str(cfg.get("VOLC_REALTIME_MODEL") or ""),
            speaker=str(cfg.get("VOLC_REALTIME_SPEAKER") or ""),
            qpm_limit=int(cfg.get("VOLC_REALTIME_QPM_LIMIT") or 60),
        )
    )
    registry.register(
        VolcASR(
            api_key=str(cfg.get("VOLC_ASR_API_KEY") or ""),
            endpoint=str(cfg.get("VOLC_ASR_ENDPOINT") or ""),
            resource_id=str(cfg.get("VOLC_ASR_RESOURCE_ID") or ""),
            packet_ms=int(cfg.get("VOLC_ASR_PACKET_MS") or 200),
        )
    )


def _llm_fields(cfg: dict, name: str, row: Provider | None) -> dict[str, Any]:
    """算出构造 LLM Provider 需要的字段。表优先，.env 补缺。"""
    active = str(cfg.get("LLM_PROVIDER") or "").strip()
    is_active = name == active

    def pick(attr: str, env_key: str) -> str:
        if row is not None:
            value = getattr(row, attr, None)
            if value:
                return str(value)
        return str(cfg.get(env_key) or "") if is_active else ""

    api_key = _safe_reveal(row) if row is not None else ""
    if not api_key and is_active:
        api_key = str(cfg.get("LLM_API_KEY") or "")

    return {
        "api_key": api_key,
        "base_url": pick("base_url", "LLM_BASE_URL"),
        "default_model": pick("default_model", "LLM_MODEL"),
        "timeout": float(cfg.get("LLM_TIMEOUT") or 120.0),
        "max_retries": int(cfg.get("LLM_MAX_RETRIES") or 0),
    }


# --- 容错读取 ---


def _read_setting(key: str) -> Any:
    """读一行 settings_kv。表不存在或值损坏时返回 None（回落 .env）。"""
    from app.models import SettingsKV

    try:
        row = db.session.get(SettingsKV, key)
    except Exception as exc:
        db.session.rollback()
        logger.warning("读取设置 %s 失败：%s", key, type(exc).__name__)
        return None
    return row.value if row is not None else None


def _provider_rows() -> list[Provider]:
    """读 providers 表。表还没建（没跑迁移）时返回空列表，不抛异常。"""
    try:
        return list(db.session.query(Provider).all())
    except Exception as exc:
        db.session.rollback()
        logger.warning("读取 providers 表失败，本次只注册离线 Provider：%s", type(exc).__name__)
        return []


def _safe_reveal(row: Provider) -> str:
    """解不开密文就当作没配 —— 换过 FERNET_KEY 时就是这个情形。"""
    try:
        return row.reveal_api_key()
    except Exception as exc:
        logger.warning(
            "Provider %s 的凭据无法解密（换过 FERNET_KEY？）：%s", row.id, type(exc).__name__
        )
        return ""


__all__ = [
    "EXTENSION_KEY",
    "capabilities",
    "get_registry",
    "refresh_registry",
    "register_cli",
    "registry_from_config",
    "self_check",
]
