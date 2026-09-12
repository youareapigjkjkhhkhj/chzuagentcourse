"""全局设置键值表。

存当前启用的服务商、生成参数、ASR 开关等零散配置。
值统一是 JSON 字符串，读的时候按需转成 dict/list/bool/str。

为什么不拆成强类型列：这些设置在 P0~P6 会不断增加，
每加一个就写一次迁移不划算，而且它们从不参与查询与关联。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, TimestampMixin

# 已知的设置键（避免各处硬编码字符串拼错）
KEY_ACTIVE_PROVIDER = "active_provider"
KEY_VOICE = "voice"
KEY_GENERATION = "generation"
KEY_ASR = "asr"


class SettingsKV(TimestampMixin, db.Model):
    __tablename__ = "settings_kv"

    key = db.Column(db.String(64), primary_key=True)
    value_json = db.Column(db.Text)

    value = JSONField("value_json")

    def __repr__(self) -> str:
        return f"<SettingsKV {self.key}>"
