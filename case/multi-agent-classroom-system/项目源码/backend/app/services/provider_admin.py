"""服务商设置的服务层（P0 §4.2 / F0-6 / F0-9）。

接口层只做「取参数 → 调这里 → 包信封」，所有规则都在这一层：
- 卡片列表：把 DB 行、注册表状态、最近一次探活延迟合成一张卡片
- 保存：字段校验 → Key 加密落库 → 重建注册表（不重建的话新 Key 要等重启才生效）
- 探活：调 Provider 的 test()，把结果记在缓存里给卡片用
- 启用：全局唯一 —— settings_kv 记一项，providers 表的 enabled 也跟着改

★ Key 只在这里进、绝不在这里出：`_card()` 只输出掩码。
"""

from __future__ import annotations

from typing import Any

from app.common.context import real_app
from app.common.dbw import db_write
from app.common.errors import NotFoundError, ValidationError
from app.common.logging import get_logger
from app.common.urls import ensure_safe_base_url
from app.extensions import db
from app.models import Provider
from app.models.provider import BUILTIN_PROVIDERS
from app.providers.base import ProbeResult, ProviderNotConfiguredError
from app.services import settings_service
from app.services.provider_registry import get_registry, refresh_registry

logger = get_logger("app.services.provider_admin")

#: 卡片的固定顺序就是内置顺序（原型上的排列），不在名单里的排后面。
_BUILTIN_ORDER = [spec["id"] for spec in BUILTIN_PROVIDERS]

#: 防滥用上限。SQLite 的 VARCHAR 长度是不强制的，没有上限就等于
#: 谁都能往 api_key_enc 里塞一兆字节。
MAX_KEY_LEN = 512
MAX_MODEL_LEN = 128

#: 最近一次探活结果缓存在 app.extensions 里（键）。放 app 上而不是模块级
#: 变量：测试里两个 app 不会互相看到对方的延迟，也不会在进程间共享陈旧值。
_PROBE_CACHE_KEY = "provider_probe_cache"


# --- 卡片列表 ---


def _probe_cache() -> dict:
    return real_app().extensions.setdefault(_PROBE_CACHE_KEY, {})


def _sort_key(provider_id: str) -> tuple[int, str]:
    if provider_id in _BUILTIN_ORDER:
        return (_BUILTIN_ORDER.index(provider_id), provider_id)
    return (len(_BUILTIN_ORDER), provider_id)


def _card(row: Provider) -> dict:
    """一张设置页卡片。★ 绝不含明文或密文 Key。

    两个状态位刻意分开，因为凭据齐备不等于现在能用：
    - `configured` 凭据齐备（库里填的，或 .env 里给的）
    - `available`  现在真的调得动 —— 要有适配器，且它已经实现了。
                  两种「有凭据却用不了」都要显示成不可用，而不是拿
                  「已配置」当「能用」：
                    · 没有适配器（P2 之前的第三方语音服务商）
                    · 适配器还是骨架（P0 的火山语音三件套）
    """
    registry = get_registry()
    latency = _probe_cache().get(row.id)
    card = row.to_dict()
    card["latencyMs"] = latency.latency_ms if isinstance(latency, ProbeResult) else None
    try:
        provider = registry.get(row.kind, row.id)
    except (NotFoundError, ValueError):
        # 没有适配器：凭据按库里那一行说，可用性明确为否
        card["available"] = False
        card["defaultModel"] = card.get("defaultModel") or ""
        return card
    # configured 以**注册表**为准而不是库里的行：.env 里配好 Key 也是配好了，
    # 只认库会让「探活打勾、卡片说未配置」，用户只好再填一遍本来就在的 Key。
    card["configured"] = bool(provider.configured)
    card["available"] = bool(provider.configured and provider.implemented)
    # 「还没实现」与「还没填」在界面上是两句话：前者要等 P2，后者要动手。
    # 只说 configured=False 会让用户一遍遍去检查自己填错了哪一栏。
    card["implemented"] = bool(provider.implemented)
    # 缺什么也要说出来：只填了 Key、没填接入地址的行同样是「未配置」，
    # 而「未配置」三个字没法告诉用户还差哪一栏
    card["missing"] = [] if provider.configured else list(provider.missing_config())
    if not card.get("defaultModel"):
        card["defaultModel"] = str(getattr(provider, "default_model", "") or "")
    return card


def list_cards() -> dict:
    rows = sorted(Provider.query.all(), key=lambda row: _sort_key(row.id))
    items = [_card(row) for row in rows]
    return {"items": items, "total": len(items)}


# --- 保存 ---


def _require_row(provider_id: str) -> Provider:
    row = db.session.get(Provider, provider_id)
    if row is None:
        raise NotFoundError(
            f"没有名为 {provider_id!r} 的服务商",
            details={"provider": provider_id, "available": _BUILTIN_ORDER},
        )
    return row


def save_provider(provider_id: str, payload: Any) -> dict:
    """保存 API Key / Base URL / 默认模型。

    Key 的语义（前端表单回显的是掩码，不是明文，所以这一点必须明确）：
      字段缺失        → 不动原来的 Key
      apiKey 空串     → 同样不动（用户只是没改这一栏）
      apiKey 非空     → 覆盖
      clearApiKey=true → 清空
    """
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象")
    if not payload:
        raise ValidationError("请求体为空，没有要修改的设置")

    row = _require_row(provider_id)
    fields = _validate_save_payload(payload)

    def _work() -> None:
        if "baseUrl" in fields:
            row.base_url = fields["baseUrl"]
        if "defaultModel" in fields:
            row.default_model = fields["defaultModel"]
        if fields.get("clear_key"):
            row.api_key = None
        elif fields.get("api_key"):
            row.api_key = fields["api_key"]  # setter 负责加密

    db_write(_work)
    _probe_cache().pop(provider_id, None)  # 改了配置，旧延迟不再代表现在
    refresh_registry()
    logger.info("服务商 %s 配置已更新（key=%s）", provider_id, "changed" if _key_touched(fields) else "unchanged")
    return _card(row)


def _key_touched(fields: dict) -> bool:
    return bool(fields.get("clear_key") or fields.get("api_key"))


def _validate_save_payload(payload: dict) -> dict:
    known = {"apiKey", "baseUrl", "defaultModel", "clearApiKey"}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise ValidationError(
            f"不认识的字段：{'、'.join(unknown)}；可选：{'、'.join(sorted(known))}"
        )

    fields: dict[str, Any] = {}

    if "baseUrl" in payload:
        raw = str(payload["baseUrl"] or "").strip()
        # 空串是「恢复默认」的合法写法（例如换成用 .env 里的地址）
        fields["baseUrl"] = ensure_safe_base_url(raw) if raw else ""

    if "defaultModel" in payload:
        model = str(payload["defaultModel"] or "").strip()
        if len(model) > MAX_MODEL_LEN:
            raise ValidationError(f"模型名过长（上限 {MAX_MODEL_LEN} 字符）")
        fields["defaultModel"] = model

    if "clearApiKey" in payload:
        if not isinstance(payload["clearApiKey"], bool):
            raise ValidationError("clearApiKey 必须是布尔值")
        fields["clear_key"] = payload["clearApiKey"]

    if "apiKey" in payload and payload["apiKey"] is not None:
        key = str(payload["apiKey"]).strip()
        if len(key) > MAX_KEY_LEN:
            raise ValidationError(f"API Key 过长（上限 {MAX_KEY_LEN} 字符）")
        # 空串 = 没改（见 save_provider 的说明），不写进 fields
        if key:
            fields["api_key"] = key
    elif "apiKey" in payload:
        # 显式 null 也当作没改：前端的「未填写」就是这个形状
        pass

    return fields


# --- 探活 ---


def probe_provider(provider_id: str) -> ProbeResult:
    """测试连接。返回 ProbeResult（永不抛异常，失败原因装在里面）。

    唯一会抛的情况是「这个服务商压根不存在 / 不归注册表管」——
    那是调用方把 id 写错了，属于 40401。
    """
    row = _require_row(provider_id)
    registry = get_registry()

    try:
        provider = registry.get(row.kind, row.id)
    except (NotFoundError, ValueError) as exc:
        raise NotFoundError(
            f"服务商 {provider_id} 没有可用的适配器（kind={row.kind}）",
            details={"provider": provider_id, "kind": row.kind},
        ) from exc

    if not provider.configured:
        # 未配置就别去连了 —— 上游一定会拒绝，还要白等一个 RTT。
        # P0-B3：这个分支必须是 40201，且说清缺什么。
        from app.providers.base import not_configured

        raise not_configured(provider)

    try:
        result = provider.test()
    except ProviderNotConfiguredError:
        raise
    except Exception as exc:
        # test() 按约定不该抛，但万一适配器写漏了，也不能把设置页搞崩
        logger.exception("探活 %s 时适配器抛出了未预期的异常", provider_id)
        result = ProbeResult(
            ok=False,
            error=f"探活失败：{type(exc).__name__}",
            error_code="probe_failed",
            provider=provider_id,
        )

    _probe_cache()[provider_id] = result
    return result


# --- 启用 ---


def enable_provider(provider_id: str) -> dict:
    """设为当前启用的服务商（全局唯一，P0-A6）。

    允许启用一个还没填 Key 的服务商：用户的自然顺序是「先启用，再去填 Key」，
    拦下来只会逼他倒着操作。填没填由卡片的 configured / health 如实反映。
    """
    row = _require_row(provider_id)

    def _work() -> None:
        # 两处都写：settings_kv 是运行期的事实来源（注册表读它），
        # providers.enabled 是给列表与查询看的冗余标记，两者必须一致。
        settings_service.set_active_provider(row.id)
        Provider.query.filter(Provider.id != row.id).update(
            {Provider.enabled: False}, synchronize_session=False
        )
        row.enabled = True

    db_write(_work)
    refresh_registry()
    logger.info("已启用服务商 %s", provider_id)
    return _card(row)


__all__ = [
    "MAX_KEY_LEN",
    "MAX_MODEL_LEN",
    "enable_provider",
    "list_cards",
    "probe_provider",
    "save_provider",
]
