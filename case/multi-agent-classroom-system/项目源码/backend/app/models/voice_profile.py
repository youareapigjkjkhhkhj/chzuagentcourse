"""音色档案。

★ 关键约束（P2 材料核对结论）：火山引擎有**两个互不相通的音色池**
- 大模型 TTS 2.0（`*_uranus_bigtts`）：90+ 中文音色，用于讲稿朗读
- 端到端实时语音（`*_jupiter_bigtts`）：中文仅 4 个，用于学生对话
把 A 池的音色填进 B 池会直接 `ClientError:InvalidSpeaker`。
所以 `voice_type` 与 `provider` 必须成对使用，且**由配置注入**。

★ `voice_type` 存的是厂商音色 ID，但代码里不写任何字面量（AGENTS.md §4.1）：
种子数据从环境变量读取，没配就诚实留空，设置页显示「未配置音色 ID」。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import PkMixin, TimestampMixin

# provider 取值 → 对应哪条语音链路
VOICE_PROVIDERS = ("volc_tts", "volc_realtime", "browser")

GENDERS = ("male", "female", "neutral")


class VoiceProfile(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "voice_profiles"

    name = db.Column(db.String(64), nullable=False)
    provider = db.Column(db.String(32), nullable=False, default="volc_tts")
    # 厂商音色 ID；空串表示尚未配置（不是错误状态，是「等你填」）
    voice_type = db.Column(db.String(128), nullable=False, default="")
    gender = db.Column(db.String(16), nullable=False, default="neutral")
    style = db.Column(db.String(128))
    sample_url = db.Column(db.String(255))
    builtin = db.Column(db.Boolean, nullable=False, default=False)

    # 该音色的默认语速偏移（-50 ~ 100），用于让共用音色的角色听感可区分
    speech_rate = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.CheckConstraint(
            "provider IN ('volc_tts', 'volc_realtime', 'browser')",
            name="voice_provider_valid",
        ),
        db.CheckConstraint(
            "gender IN ('male', 'female', 'neutral')",
            name="voice_gender_valid",
        ),
    )

    @property
    def configured(self) -> bool:
        """厂商音色 ID 填了才算可用。浏览器合成不需要 ID。"""
        if self.provider == "browser":
            return True
        return bool(self.voice_type)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "voiceType": self.voice_type,
            "gender": self.gender,
            "style": self.style or "",
            "sampleUrl": self.sample_url or "",
            "builtin": bool(self.builtin),
            "speechRate": self.speech_rate,
            "configured": self.configured,
        }

    def __repr__(self) -> str:
        return f"<VoiceProfile {self.id} {self.name} provider={self.provider}>"
