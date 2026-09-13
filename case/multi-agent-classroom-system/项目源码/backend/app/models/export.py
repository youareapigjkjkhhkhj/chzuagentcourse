"""导出任务与产物（P5 §5 / F5-6）。

一行 = **一次导出**，而不是「一份产物」。同一个课程可以导出很多次（换格式、
关了水印再来一次、重试上次失败的），每次都该有自己的进度、错误与过期时间 ——
把它们压成「课程的一个附件」就没法回答「上次为什么失败」「这个产物什么时候到期」。

四条口径：

1. **`options_json` 原样留档。** 产物是「这一组选项跑出来的东西」，改了水印开关
   重导就是另一份产物。不记选项的话，看到一份没水印的 PDF 就说不清它是从哪来的。
2. **`file_path` 存相对路径**（与 `audio_assets` 同一条理由）：绝对路径一换机器
   就全指向不存在的地方，还会把「谁的电脑、什么用户名」写进库里。
   形如 `data/exports/{course_id}/{export_id}.{ext}`（P5-C1 的落库判据）。
3. **`expires_at` 是承诺，清理任务按它删**（P5-A6 / P5-C1）。过期即删文件与记录，
   **不留 `expired` 状态**：留一行「已过期」既不能下载也不能重下，只会让导出历史
   里堆一片点不动的条目。真要那份产物，重新导一次 —— 课程 DSL 还在库里。
4. **`session_id` 只对 `scope=record` 有意义**（F5-5 的课堂记录导出）。它是弱引用
   （不建外键）：课堂删了，那份导出过的记录文件仍是既成事实，不该连带消失。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

#: 产物格式。`md` 只用于课堂记录（F5-5），课件不走它
EXPORT_FORMATS = ("pptx", "html", "pdf", "md")

#: 导什么：整门课（课件）/ 一节课堂的记录
EXPORT_SCOPES = ("course", "record")

#: `queued` 排队中 / `running` 渲染中 / `done` 可下载 / `failed` 看 `error`
EXPORT_STATUSES = ("queued", "running", "done", "failed")

#: 相对 backend/ 的存放目录（P5-C1）。与 config 的 EXPORT_DIR 同源，
#: 但**这里只描述形状**：取绝对路径是 config 的事，模型不认识磁盘。
EXPORT_SUBDIR = "data/exports"

#: P5-C1 的落库判据：必须在导出目录下、必须相对、且不许用 `..` 走出去。
#: 「不许以 / 开头」那种反向写法拦不住 Windows 的 `C:\…`，所以写成正向的。
#: 注：迁移里同一句话是**字面量**（迁移不引用模型），改这里要同步改 P5 那条迁移。
_FILE_PATH_SQL = (
    f"file_path IS NULL OR "
    f"(file_path LIKE '{EXPORT_SUBDIR}/%' AND file_path NOT LIKE '%..%')"
)


class Export(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "exports"

    #: 课程一律 CASCADE：课删了，它的导出产物没有独立存在的意义。
    #: 与 `model_calls` 那种账本不同 —— 这里存的是**课程的派生物**，不是花过的钱。
    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    #: 弱引用 classroom_sessions.id，只有 scope=record 时非空，理由见模块 docstring
    session_id = db.Column(db.String(32))
    #: 弱引用 users.id（不建外键）：导出记录要能回答「谁在什么时候导的」，
    #: 而这一点在人注销之后仍然成立。owner_id 为空表示「无主」，此时只有本机可见。
    owner_id = db.Column(db.String(32), nullable=False, default="")
    format = db.Column(db.String(8), nullable=False)
    scope = db.Column(db.String(16), nullable=False, default="course")
    status = db.Column(db.String(16), nullable=False, default="queued")
    #: 0~100。渲染是「页」粒度的，所以进度按「画完几页 / 共几页」算 ——
    #: 比「大概快好了」这种假进度诚实得多。
    progress = db.Column(db.Integer, nullable=False, default=0)
    #: 相对 backend/ 的路径，形如 data/exports/{course_id}/{id}.pptx，见模块 docstring
    file_path = db.Column(db.String(512))
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    #: 渲染选项原样留档：{watermark, withNotes, withQuiz}，见模块 docstring 第 1 条
    options_json = db.Column(db.Text)
    #: 失败原因（给人看的一句话，不含密钥与材料正文）
    error = db.Column(db.String(512), nullable=False, default="")
    #: 到期时间（UTC ISO8601）。到点清理任务删文件与记录（P5-A6 / P5-C1）
    expires_at = db.Column(db.String(32), nullable=False, default="")
    finished_at = db.Column(db.String(32), nullable=False, default="")

    options = JSONField("options_json")

    __table_args__ = (
        db.CheckConstraint(
            "format IN ('pptx', 'html', 'pdf', 'md')", name="export_format_valid"
        ),
        db.CheckConstraint(
            "scope IN ('course', 'record')", name="export_scope_valid"
        ),
        db.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name="export_status_valid"
        ),
        db.CheckConstraint("progress >= 0 AND progress <= 100", name="export_progress_in_range"),
        db.CheckConstraint("size_bytes >= 0", name="export_size_non_negative"),
        db.CheckConstraint(_FILE_PATH_SQL, name="export_file_path_relative"),
        # 课程详情页的「导出历史」（GET /api/courses/{id}/exports）走这条
        db.Index("ix_exports_course_created", "course_id", "created_at"),
        # 清理任务按到期时间扫（P5-C1）
        db.Index("ix_exports_expires", "expires_at"),
        db.Index("ix_exports_owner_created", "owner_id", "created_at"),
    )

    @property
    def downloadable(self) -> bool:
        """能下载吗：渲染完了、文件在、还没过期。"""
        return self.status == "done" and bool(self.file_path)

    def to_dict(self) -> dict:
        """只报存储事实，不含 url —— 下载链接要用一次性 token 签，那是 API 层的事。"""
        return {
            "id": self.id,
            "courseId": self.course_id,
            "sessionId": self.session_id or "",
            "ownerId": self.owner_id,
            "format": self.format,
            "scope": self.scope,
            "status": self.status,
            "progress": self.progress,
            "filePath": self.file_path or "",
            "sizeBytes": self.size_bytes,
            "options": self.options or {},
            "error": self.error,
            "expiresAt": self.expires_at,
            "finishedAt": self.finished_at,
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<Export {self.format}/{self.scope} {self.status} course={self.course_id}>"


__all__ = [
    "EXPORT_FORMATS",
    "EXPORT_SCOPES",
    "EXPORT_STATUSES",
    "EXPORT_SUBDIR",
    "Export",
]
