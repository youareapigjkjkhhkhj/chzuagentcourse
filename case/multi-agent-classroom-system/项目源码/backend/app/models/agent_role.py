"""课堂角色（主讲老师 + AI 同学）。

`persona_json` 承载角色的说话风格与行为倾向，P3 课堂运行时把它拼进提示词。
同学共用音色池里有限的音色时，靠 persona 里的语速/音高偏移拉开区分度。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

AGENT_ROLES = ("teacher", "student")


class AgentRole(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "agent_roles"

    code = db.Column(db.String(32), nullable=False, unique=True)
    name = db.Column(db.String(64), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="student")
    avatar_color = db.Column(db.String(16))
    persona_json = db.Column(db.Text)
    voice_profile_id = db.Column(
        db.String(32), db.ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True
    )
    builtin = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    persona = JSONField("persona_json")

    __table_args__ = (
        db.CheckConstraint("role IN ('teacher', 'student')", name="agent_role_valid"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "role": self.role,
            "avatarColor": self.avatar_color or "",
            "voiceProfileId": self.voice_profile_id,
            "builtin": bool(self.builtin),
            "persona": self.persona or {},
        }

    def __repr__(self) -> str:
        return f"<AgentRole {self.code} {self.name} ({self.role})>"
