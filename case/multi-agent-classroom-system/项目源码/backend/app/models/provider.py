"""服务商（LLM / TTS / ASR）。

安全（AGENTS.md §4.1）：
- API Key 只以密文形式落 `api_key_enc`；
- 明文只能通过 `reveal_api_key()` 显式取出（供 providers 层调用上游），
  对外展示一律走 `masked_key`；
- 接口层不得序列化 `api_key_enc`，`to_dict()` 里只有掩码。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event

from app.common.crypto import decrypt, encrypt, mask
from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

PROVIDER_KINDS = ("llm", "tts", "asr")

# 内置服务商（P0-F6：DeepSeek 已启用 / OpenAI / Qwen / Kimi + 自定义）
# 注意：base_url 与 default_model 是「出厂建议值」，用户可在设置页改写；
# 这里留空则设置页显示占位符 —— 不在代码里写死厂商端点（AGENTS.md §4.1）。
BUILTIN_PROVIDERS: tuple[dict[str, Any], ...] = (
    {"id": "deepseek", "name": "DeepSeek", "kind": "llm", "enabled": 1},
    {"id": "openai", "name": "OpenAI", "kind": "llm", "enabled": 0},
    {"id": "qwen", "name": "Qwen", "kind": "llm", "enabled": 0},
    {"id": "kimi", "name": "Kimi", "kind": "llm", "enabled": 0},
    # 第 5 张卡：自定义。它也是「任何 OpenAI 兼容端点」的入口 ——
    # base_url 必填，所以这一行在填好地址之前不可用。
    {"id": "custom", "name": "自定义", "kind": "llm", "enabled": 0},
)


class Provider(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "providers"

    name = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(16), nullable=False, default="llm")
    base_url = db.Column(db.String(255))
    api_key_enc = db.Column(db.Text)
    default_model = db.Column(db.String(128))
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    # 是否已配置可用凭据。由 api_key_enc 在写入前后自动同步（见下方事件）。
    configured = db.Column(db.Boolean, nullable=False, default=False)
    extra_json = db.Column(db.Text)

    extra = JSONField("extra_json")

    __table_args__ = (
        db.CheckConstraint("kind IN ('llm', 'tts', 'asr')", name="provider_kind_valid"),
    )

    # --- 凭据 ---

    @property
    def api_key(self):
        """读不到明文 —— 想拿明文必须显式调用 reveal_api_key()。

        这样 `provider.api_key` 出现在接口序列化代码里会立刻报错，
        而不是悄悄把 Key 发给浏览器。
        """
        raise AttributeError(
            "Provider.api_key 只写不读；对外展示用 masked_key，调用上游用 reveal_api_key()"
        )

    @api_key.setter
    def api_key(self, value: str | None) -> None:
        """传明文即加密落库；传 None/空串表示清除。"""
        if value is None or str(value).strip() == "":
            self.api_key_enc = None
        else:
            self.api_key_enc = encrypt(str(value).strip())

    def reveal_api_key(self) -> str:
        """取出明文 Key。仅限 providers 层构造上游客户端时调用。"""
        if not self.api_key_enc:
            return ""
        return decrypt(self.api_key_enc)

    @property
    def masked_key(self) -> str:
        """设置页回显用：sk-****1234。"""
        if not self.api_key_enc:
            return ""
        try:
            return mask(decrypt(self.api_key_enc))
        except Exception:
            # 换了 FERNET_KEY 或密文损坏：当作未配置，不要让设置页整个打不开
            return ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "baseUrl": self.base_url or "",
            "defaultModel": self.default_model or "",
            "enabled": bool(self.enabled),
            "configured": bool(self.configured),
            "maskedKey": self.masked_key,
            "extra": self.extra or {},
            "updatedAt": self.updated_at,
        }

    def __repr__(self) -> str:
        return f"<Provider {self.id} {self.name} kind={self.kind} configured={self.configured}>"


@event.listens_for(Provider, "before_insert")
@event.listens_for(Provider, "before_update")
def _sync_configured_flag(_mapper, _connection, target: Provider) -> None:
    """把 configured 与真实凭据状态对齐。

    规格里 configured 是列（需要能按它筛列表），但它本质是派生值。
    用事件同步，避免出现「Key 已清空但卡片还显示已配置」。
    """
    target.configured = bool(target.api_key_enc)
