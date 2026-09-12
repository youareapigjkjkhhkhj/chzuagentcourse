"""用户。

P0 只区分角色，不做登录鉴权（课堂演示是单机场景）。
真正的多用户隔离在 P4 之后按需展开 —— 但 owner_id 现在就落好，
避免以后加权限时发现数据无法归属。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import PkMixin, TimestampMixin

USER_ROLES = ("teacher", "student", "admin")


class User(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    name = db.Column(db.String(64), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="teacher")
    avatar_color = db.Column(db.String(16))

    __table_args__ = (
        db.CheckConstraint(
            "role IN ('teacher', 'student', 'admin')",
            name="user_role_valid",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "avatarColor": self.avatar_color,
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<User {self.id} {self.name} ({self.role})>"
