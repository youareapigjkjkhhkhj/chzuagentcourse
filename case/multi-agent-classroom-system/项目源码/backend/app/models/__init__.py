"""SQLAlchemy 模型。

create_app 会 import 本模块，确保 db.create_all() 与 Alembic autogenerate
能看到全部表（漏 import 会导致「表莫名消失」）。
"""

from app.models.agent_role import AGENT_ROLES, AgentRole
from app.models.audio_asset import AUDIO_STATUSES, AUDIO_SUBDIR, AudioAsset
from app.models.base import JSONField, PkMixin, TimestampMixin, new_id
from app.models.budget import (
    BUDGET_SCOPES,
    DAILY_KINDS,
    Budget,
    DailyUsage,
)
from app.models.classroom import (
    CLASSROOM_MODES,
    CLASSROOM_STATUSES,
    HAND_STATUSES,
    MESSAGE_TYPES,
    PARTICIPANT_ROLES,
    SPEAKER_KINDS,
    STROKE_AUTHORS,
    BoardStroke,
    ClassroomMessage,
    ClassroomSession,
    HandQueue,
    QuizAttempt,
    SessionEvent,
    SessionParticipant,
)
from app.models.course import (
    COURSE_STATUSES,
    PAGE_KINDS,
    PAGE_STATUSES,
    Course,
    CoursePage,
)
from app.models.export import (
    EXPORT_FORMATS,
    EXPORT_SCOPES,
    EXPORT_STATUSES,
    EXPORT_SUBDIR,
    Export,
)
from app.models.generation import (
    JOB_STATUSES,
    STEP_STATUSES,
    STEP_TYPES,
    GenEvent,
    GenJob,
    GenStep,
)
from app.models.material import (
    MATERIAL_EXTS,
    MATERIAL_STATUSES,
    ChunkKeyword,
    CourseSource,
    Material,
    MaterialChunk,
    MaterialStats,
    PageSource,
)
from app.models.page_version import PAGE_VERSION_REASONS, CoursePageVersion
from app.models.provider import BUILTIN_PROVIDERS, PROVIDER_KINDS, Provider
from app.models.settings_kv import (
    KEY_ACTIVE_PROVIDER,
    KEY_ASR,
    KEY_GENERATION,
    KEY_VOICE,
    SettingsKV,
)
from app.models.telemetry import (
    CALL_REF_TYPES,
    CALL_UNIT_NAMES,
    MODEL_CALL_KINDS,
    AuditLog,
    ModelCall,
)
from app.models.usage_record import (
    REF_TYPES,
    UNIT_NAMES,
    USAGE_KINDS,
    UsageRecord,
)
from app.models.user import USER_ROLES, User
from app.models.voice_profile import GENDERS, VOICE_PROVIDERS, VoiceProfile
from app.models.workbench import (
    CHAT_MESSAGE_ROLES,
    CHAT_SESSION_STATUSES,
    SKILL_NAMES,
    SKILL_STATUSES,
    ChatMessage,
    ChatSession,
    SkillInvocation,
)

__all__ = [
    "AGENT_ROLES",
    "AUDIO_STATUSES",
    "AUDIO_SUBDIR",
    "BUDGET_SCOPES",
    "BUILTIN_PROVIDERS",
    "CALL_REF_TYPES",
    "CALL_UNIT_NAMES",
    "CHAT_MESSAGE_ROLES",
    "CHAT_SESSION_STATUSES",
    "CLASSROOM_MODES",
    "CLASSROOM_STATUSES",
    "COURSE_STATUSES",
    "DAILY_KINDS",
    "EXPORT_FORMATS",
    "EXPORT_SCOPES",
    "EXPORT_STATUSES",
    "EXPORT_SUBDIR",
    "GENDERS",
    "HAND_STATUSES",
    "JOB_STATUSES",
    "KEY_ACTIVE_PROVIDER",
    "KEY_ASR",
    "KEY_GENERATION",
    "KEY_VOICE",
    "MATERIAL_EXTS",
    "MATERIAL_STATUSES",
    "MESSAGE_TYPES",
    "MODEL_CALL_KINDS",
    "PAGE_KINDS",
    "PAGE_STATUSES",
    "PAGE_VERSION_REASONS",
    "PARTICIPANT_ROLES",
    "PROVIDER_KINDS",
    "REF_TYPES",
    "SKILL_NAMES",
    "SKILL_STATUSES",
    "SPEAKER_KINDS",
    "STEP_STATUSES",
    "STEP_TYPES",
    "STROKE_AUTHORS",
    "UNIT_NAMES",
    "USAGE_KINDS",
    "USER_ROLES",
    "VOICE_PROVIDERS",
    "AgentRole",
    "AudioAsset",
    "AuditLog",
    "BoardStroke",
    "Budget",
    "ChatMessage",
    "ChatSession",
    "ChunkKeyword",
    "ClassroomMessage",
    "ClassroomSession",
    "Course",
    "CoursePage",
    "CoursePageVersion",
    "CourseSource",
    "DailyUsage",
    "Export",
    "GenEvent",
    "GenJob",
    "GenStep",
    "HandQueue",
    "JSONField",
    "Material",
    "MaterialChunk",
    "MaterialStats",
    "ModelCall",
    "PageSource",
    "PkMixin",
    "Provider",
    "QuizAttempt",
    "SessionEvent",
    "SessionParticipant",
    "SettingsKV",
    "SkillInvocation",
    "TimestampMixin",
    "UsageRecord",
    "User",
    "VoiceProfile",
    "new_id",
]
