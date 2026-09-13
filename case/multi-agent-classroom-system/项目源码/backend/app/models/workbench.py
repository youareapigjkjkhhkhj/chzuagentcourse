"""工作台对话域的三张表（P4 §4）。

生成域写「课的形态」，课堂域写「一堂课的经过」，这里写的是**做课的过程** ——
用户跟 Agent 说了什么、Agent 回了什么、其中调了哪些 Skill 改了哪几页。

两件事在这里定下来：

1. **`seq` 是回退的界**（F4-11 / P4-A12）。会话里的消息按 `seq` 单调递增，回退就是
   「以第 N 条为界」，而不是「撤销某一次操作」—— 后者要维护一整套反向操作，
   而我们要的只是「回到那时候的上下文」。界画在消息上，页面内容的回退交给页面
   自己的版本号（`course_page_versions` 已经是一串 append-only 的版本）。
2. **Skill 调用单独一张表**（F4-12 / P4-A10）。它必须**可见**：每条消息旁边那张
   操作卡读的就是这张表 —— 「Agent 改了什么」不能只活在它的回复文字里。
"""

from __future__ import annotations

from app.common.timeutil import utcnow_iso
from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin, enum_check

#: 会话的两态。`archived` 是「用户自己收起了这条会话」，不影响历史消息。
CHAT_SESSION_STATUSES = ("active", "archived")

#: 消息的三种角色，与所有对话模型同义。`system` 是产品自己写进上下文的那几条
#: （比如「这门课现在有 8 页」），用户看不到、但回退时要一起算。
CHAT_MESSAGE_ROLES = ("user", "assistant", "system")

#: 一次 Skill 调用的三态。`running` 会先落库再执行 —— 前端的操作卡在
#: `agent.skill` 事件到达时就转圈，那时结果还没有（§3.3）。
SKILL_STATUSES = ("running", "ok", "failed")

#: §F4-12 的七个内置技能。前端 `GET /skills` 的清单与模型可调用的清单都从这儿来，
#: 两处各写一份的话，迟早会出现「提示里说能做、实际做不了」。
SKILL_NAMES = (
    "revise_outline",
    "rewrite_page",
    "add_quiz",
    "add_page",
    "remove_page",
    "change_tone",
    "summarize_material",
)


class ChatSession(PkMixin, TimestampMixin, db.Model):
    """一门课的工作台会话（一个用户对一门课通常只有一条，但不强求）。"""

    __tablename__ = "chat_sessions"

    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    owner_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title = db.Column(db.String(120), nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="active")
    #: 「最近一次说话」的时间。工作台列表按它排序 —— `updated_at` 会在
    #: 改标题这种小事上跳，而这里要的是「用户最后一次真的动了它」。
    last_active_at = db.Column(db.String(32), nullable=False, default=utcnow_iso)

    messages = db.relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        enum_check("status", CHAT_SESSION_STATUSES, "chat_session_status_valid"),
        db.Index("ix_chat_sessions_course_status", "course_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "courseId": self.course_id,
            "title": self.title,
            "status": self.status,
            "lastActiveAt": self.last_active_at,
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<ChatSession {self.id} course={self.course_id}>"


class ChatMessage(PkMixin, TimestampMixin, db.Model):
    """一条对话消息。`seq` 从 1 开始、会话内单调，回退的界就是它。"""

    __tablename__ = "chat_messages"

    session_id = db.Column(
        db.String(32), db.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    #: 这条消息里调过的 Skill 摘要（名字与状态），给消息流一次渲染用；
    #: 展开的细节在 `skill_invocations` 那张表里。
    skill_calls_json = db.Column(db.Text)
    #: 这条消息「在说哪一页」。有它，回退之后重建上下文时才知道用户当时
    #: 是在看着第 5 页说「把这一段改一下」。
    ref_page_no = db.Column(db.Integer, nullable=True)
    tokens = db.Column(db.Integer, nullable=False, default=0)

    skill_calls = JSONField("skill_calls_json")

    session = db.relationship("ChatSession", back_populates="messages")
    invocations = db.relationship(
        "SkillInvocation",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        enum_check("role", CHAT_MESSAGE_ROLES, "chat_message_role_valid"),
        db.UniqueConstraint("session_id", "seq", name="uq_chat_messages_session_seq"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "seq": self.seq,
            "role": self.role,
            "content": self.content,
            "skillCalls": self.skill_calls or [],
            "refPageNo": self.ref_page_no,
            "tokens": self.tokens,
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<ChatMessage {self.session_id}#{self.seq} {self.role}>"


class SkillInvocation(PkMixin, TimestampMixin, db.Model):
    """一次 Skill 调用（F4-12 / P4-A10 的操作卡）。

    落库的时机是「决定要调它」而不是「它跑完了」：操作卡在前端先转圈、
    再填结果，这张表要跟得上那两步 —— 所以有 `status` 与 `duration_ms`。
    """

    __tablename__ = "skill_invocations"

    session_id = db.Column(
        db.String(32), db.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id = db.Column(
        db.String(32), db.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=True
    )
    skill = db.Column(db.String(40), nullable=False)
    args_json = db.Column(db.Text)
    result_json = db.Column(db.Text)
    status = db.Column(db.String(16), nullable=False, default="running")
    duration_ms = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.String(512), nullable=False, default="")

    args = JSONField("args_json")
    result = JSONField("result_json")

    message = db.relationship("ChatMessage", back_populates="invocations")

    __table_args__ = (
        enum_check("status", SKILL_STATUSES, "skill_status_valid"),
        db.Index("ix_skill_invocations_session", "session_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "messageId": self.message_id,
            "skill": self.skill,
            "args": self.args or {},
            "result": self.result,
            "status": self.status,
            "durationMs": self.duration_ms,
            "error": self.error,
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<SkillInvocation {self.skill} {self.status}>"
