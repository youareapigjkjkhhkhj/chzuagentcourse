"""音频资产（P2 §5）。

一行 = 「某个 beat 的这段文字，用这个音色、这个语速，已经合成过一个文件」。
它**不是**讲稿的一部分，而是**一份缓存索引**：讲稿在 `course_pages.dsl_json` 里，
这里只记「合过没有、合成了哪个文件、还作不作数」。

由此推出三条设计口径：

1. **`text_hash` 是失效判据**（P2 §5）。讲稿改了但音频还是旧的那一条，比没有音频更糟 ——
   学生会听到与字幕对不上的声音。所以行里存的是「合成时那段文字的哈希」，
   与当前文字不一致即 `stale`，必须重合成而不是继续用。
2. **`file_path` 存相对路径**（P2-C4）。绝对路径一换机器就全指向不存在的地方，
   而且会把「谁的电脑、什么用户名」写进库里。文件名里的 `hash8` 让它天然唯一：
   同一个 beat 重新合成会**换一个新文件名**，不会覆盖正在播的那个文件。
3. **`voice_id` 是弱引用（不建外键）**，与 `model_calls` 同理：删掉一个音色不该连带
   删掉已经合好的音频行 —— 文件还在盘上，把音色加回来就能直接命中缓存。

`status` 只有三态，都描述**事实**而不是意图：
`ready` 文件在盘上可用；`stale` 文字变了、这份作废；`failed` 合成失败过（保留一行，
让界面能说出「这一句合成失败了」，而不是假装从没合过）。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import PkMixin, TimestampMixin

AUDIO_STATUSES = ("ready", "stale", "failed")

#: 相对 backend/ 的存放目录（P2 §5）。与 config 的 AUDIO_DIR 同源，
#: 但**这里只描述形状**：取绝对路径是 config 的事，模型不认识磁盘。
AUDIO_SUBDIR = "data/assets/audio"

#: P2-C4 的落库判据：必须在音频目录下、必须相对、且不许用 `..` 走出去。
#: 「不许以 / 开头」那种反向写法拦不住 Windows 的 `C:\…`，所以写成正向的。
#: 注：迁移里同一句话是**字面量**（迁移不引用模型，见 P1 那条迁移的说明），
#: 改这里要同步改 174f554d68d9。
_FILE_PATH_SQL = (
    f"file_path IS NULL OR "
    f"(file_path LIKE '{AUDIO_SUBDIR}/%' AND file_path NOT LIKE '%..%')"
)


class AudioAsset(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "audio_assets"

    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    page_no = db.Column(db.Integer, nullable=False)
    #: 讲稿里的一小句（`p{pageNo}-b{n}`，见 generation/schema.py 的 normalize_beats）
    beat_id = db.Column(db.String(32), nullable=False)
    #: 合成时那段文字的 SHA-256（十六进制）。变了就是 stale，见模块 docstring
    text_hash = db.Column(db.String(64), nullable=False, default="")
    #: 弱引用 voice_profiles.id —— 不是外键，理由见模块 docstring
    voice_id = db.Column(db.String(32), nullable=False, default="")
    #: 合成参数一并入键：同一个音色换个语速就是另一份文件，不能互相顶替
    speed = db.Column(db.Integer, nullable=False, default=0)
    tone = db.Column(db.String(32), nullable=False, default="")
    #: 相对 backend/ 的路径，形如 data/assets/audio/{course_id}/{beat_id}_{hash8}.mp3
    file_path = db.Column(db.String(255))
    duration_ms = db.Column(db.Integer, nullable=False, default=0)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(16), nullable=False, default="ready")

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('ready', 'stale', 'failed')", name="audio_asset_status_valid"
        ),
        db.CheckConstraint("page_no > 0", name="audio_asset_page_no_positive"),
        db.CheckConstraint(
            "speed >= -50 AND speed <= 100", name="audio_asset_speed_in_range"
        ),
        db.CheckConstraint("duration_ms >= 0", name="audio_asset_duration_non_negative"),
        db.CheckConstraint("size_bytes >= 0", name="audio_asset_size_non_negative"),
        # P2-C4：绝对路径换机器就废，还会把「谁的电脑」写进库
        db.CheckConstraint(_FILE_PATH_SQL, name="audio_asset_file_path_relative"),
        # 「同一门课的同一个 beat、同一套参数」只该有一份音频（P2 §5）
        db.UniqueConstraint(
            "course_id",
            "beat_id",
            "voice_id",
            "speed",
            "tone",
            name="uq_audio_assets_beat_voice",
        ),
        # 按页作废（P1 重写一页 → 该页 beat 全 stale）走这条
        db.Index("ix_audio_assets_course_page", "course_id", "page_no"),
    )

    @property
    def hash8(self) -> str:
        """文件名里的 8 位哈希。文字没变时重算也是同一个名字 —— 这正是缓存的意义。"""
        return (self.text_hash or "")[:8]

    @property
    def available(self) -> bool:
        """能直接拿去播吗。`stale`/`failed` 都算不能 —— 前者内容对不上，后者文件不在。"""
        return self.status == "ready" and bool(self.file_path)

    def to_dict(self) -> dict:
        """只报存储事实，不含 url —— 拼路由是 API 层的事，模型不认识 HTTP。"""
        return {
            "id": self.id,
            "courseId": self.course_id,
            "pageNo": self.page_no,
            "beatId": self.beat_id,
            "voiceId": self.voice_id,
            "speed": self.speed,
            "tone": self.tone,
            "textHash": self.text_hash,
            "filePath": self.file_path or "",
            "durationMs": self.duration_ms,
            "sizeBytes": self.size_bytes,
            "status": self.status,
            "available": self.available,
        }

    def __repr__(self) -> str:
        return f"<AudioAsset {self.beat_id} voice={self.voice_id} status={self.status}>"


__all__ = ["AUDIO_STATUSES", "AUDIO_SUBDIR", "AudioAsset"]
