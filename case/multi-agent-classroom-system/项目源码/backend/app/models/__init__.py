"""SQLAlchemy 模型。

create_app 会 import 本模块，确保 db.create_all() 与 Alembic autogenerate
能看到全部表（漏 import 会导致「表莫名消失」）。
"""

from app.models.agent_role import AGENT_ROLES, AgentRole
from app.models.base import JSONField, PkMixin, TimestampMixin, new_id
from app.models.course import (
    COURSE_STATUSES,
    PAGE_KINDS,
    PAGE_STATUSES,
    Course,
    CoursePage,
)
from app.models.generation import (
    JOB_STATUSES,
    STEP_STATUSES,
    STEP_TYPES,
    GenEvent,
    GenJob,
    GenStep,
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
from app.models.telemetry import MODEL_CALL_KINDS, AuditLog, ModelCall
from app.models.user import USER_ROLES, User
from app.models.voice_profile import GENDERS, VOICE_PROVIDERS, VoiceProfile

__all__ = [
    "AGENT_ROLES",
    "BUILTIN_PROVIDERS",
    "COURSE_STATUSES",
    "GENDERS",
    "JOB_STATUSES",
    "KEY_ACTIVE_PROVIDER",
    "KEY_ASR",
    "KEY_GENERATION",
    "KEY_VOICE",
    "MODEL_CALL_KINDS",
    "PAGE_KINDS",
    "PAGE_STATUSES",
    "PAGE_VERSION_REASONS",
    "PROVIDER_KINDS",
    "STEP_STATUSES",
    "STEP_TYPES",
    "USER_ROLES",
    "VOICE_PROVIDERS",
    "AgentRole",
    "AuditLog",
    "Course",
    "CoursePage",
    "CoursePageVersion",
    "GenEvent",
    "GenJob",
    "GenStep",
    "JSONField",
    "ModelCall",
    "PkMixin",
    "Provider",
    "SettingsKV",
    "TimestampMixin",
    "User",
    "VoiceProfile",
    "new_id",
]
