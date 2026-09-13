"""课堂运行时的七张表（P3 §5）。

这一层与 P1 的生成域是两种东西：生成域写的是**课的形态**（页面、DSL、版本），
课堂域写的是**一堂课的经过**（谁在什么时候说了什么、举了几次手、答对没有）。
所以这里大量是「事件」而不是「状态」—— 唯一的状态是 `classroom_sessions`
上那一行，其余六张表都是它的日志。

三件事在这里定下来，后面几层都按它们写：

1. **`session_events` 是补发的唯一依据。** 断线重连时服务端要「把缺的事件补上」，
   靠的就是这张表按 `seq` 取（AGENTS §17）。`messages` / `board_strokes` 这些
   是**给人看的视图**，不是重放用的日志 —— 两边的写入时机不同，别拿它们互相顶替。
2. **`classroom_sessions` 一行就是这堂课的全部状态。** 进程重启后
   「刷新可恢复」（P3-A10）能不能成立，取决于状态是否都落在这一行里，
   而不是活在某个 Python 对象的字段上。
3. **外键一律 `ondelete="CASCADE"`，删课级联带走**（P3-C4）。与 P1-C3 同一条
   口径：级联靠 `PRAGMA foreign_keys=ON`，不靠 ORM 逐个删。
"""

from __future__ import annotations

from app.common.timeutil import utcnow_iso
from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin, enum_check

#: §2.1 的七个状态。改这里必须同步迁移（SQLite 的 CHECK 约束改不动）。
CLASSROOM_STATUSES = (
    "idle",
    "lecture",
    "discussing",
    "quiz_wait",
    "board_show",
    "paused",
    "ended",
)

#: `mode`：`auto` 是正常课堂（时间线自己往前走），`manual` 是逐页手翻。
#: 关闭 WS（`CLASSROOM_WS=false`，P3-G3）时开出来的就是 manual —— 没有推送就没有
#: 时间线，剩下的那条路要能走完，而不是白屏。
CLASSROOM_MODES = ("auto", "manual")

#: 参与者的两种身份。`owner` 是开课的人（记录页对他可见），`member` 是旁听/共学。
PARTICIPANT_ROLES = ("owner", "member")

#: 消息的三类说话人：老师、AI 同学、真人（我）。
SPEAKER_KINDS = ("teacher", "student_ai", "me", "system")

#: §5 的七种消息类型。`lecture` 是讲稿，其余是互动与系统提示。
MESSAGE_TYPES = ("lecture", "question", "supplement", "reflect", "answer", "comment", "system")

#: 举手队列的四态。`canceled` 与 `done` 分开：前者是学生自己撤回，
#: 后者是被点名并问完了 —— 记录页只把 `done` 算进「问过几次」。
HAND_STATUSES = ("waiting", "called", "done", "canceled")

#: 板书画笔的起笔人。
STROKE_AUTHORS = ("teacher", "me")


class ClassroomSession(PkMixin, TimestampMixin, db.Model):
    """一堂课的一行（§2.1 的状态机就停在这上面）。"""

    __tablename__ = "classroom_sessions"

    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    owner_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    mode = db.Column(db.String(16), nullable=False, default="auto")
    status = db.Column(db.String(16), nullable=False, default="idle")
    #: 时间线位置。页号 + 页内第几个 beat —— 「恢复到相同页号/beat 位置」
    #: （P3-A10）要的就是这两个数，误差 ≤1 beat 说的是 beat_idx。
    current_page_no = db.Column(db.Integer, nullable=False, default=1)
    current_beat_idx = db.Column(db.Integer, nullable=False, default=0)
    #: 已讲时长与总时长（都按 1.0x 计，前端按倍速自己换算显示）——
    #: 「07:32 / 25:00」那个进度条的两个数，都由服务端算（§6：前端不自己推进）。
    elapsed_ms = db.Column(db.Integer, nullable=False, default=0)
    total_ms = db.Column(db.Integer, nullable=False, default=0)
    speed = db.Column(db.Float, nullable=False, default=1.0)
    started_at = db.Column(db.String(32))
    ended_at = db.Column(db.String(32))
    #: 状态机自己那点东西（讨论轮次、被抢占的发言、当前说话者……）。
    #: 放 JSON 而不是再开表：它没有查询需求，只有「重启后接得上」这一个要求。
    state_json = db.Column(db.Text)

    state = JSONField("state_json")

    participants = db.relationship(
        "SessionParticipant",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events = db.relationship(
        "SessionEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    messages = db.relationship(
        "ClassroomMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    strokes = db.relationship(
        "BoardStroke",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        enum_check("status", CLASSROOM_STATUSES, "classroom_session_status_valid"),
        db.CheckConstraint(
            "mode IN ('auto', 'manual')", name="classroom_session_mode_valid"
        ),
        db.CheckConstraint("current_page_no > 0", name="classroom_session_page_positive"),
        db.CheckConstraint("current_beat_idx >= 0", name="classroom_session_beat_non_negative"),
        db.CheckConstraint("speed > 0", name="classroom_session_speed_positive"),
        # 列表与「这堂课还在不在跑」都按 (course, status) 查
        db.Index("ix_classroom_sessions_course_status", "course_id", "status"),
        db.Index("ix_classroom_sessions_owner_started", "owner_id", "started_at"),
    )

    @property
    def active(self) -> bool:
        """还在进行中（没结束）。"""
        return self.status not in {"ended"}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "courseId": self.course_id,
            "ownerId": self.owner_id,
            "mode": self.mode,
            "status": self.status,
            "pageNo": self.current_page_no,
            "beatIdx": self.current_beat_idx,
            "elapsedMs": self.elapsed_ms,
            "totalMs": self.total_ms,
            "speed": self.speed,
            "startedAt": self.started_at or "",
            "endedAt": self.ended_at or "",
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<ClassroomSession {self.id} course={self.course_id} status={self.status}>"


class SessionParticipant(PkMixin, TimestampMixin, db.Model):
    """谁在这堂课里（「在线 5」数的就是这里 `online=1` 的行）。"""

    __tablename__ = "session_participants"

    session_id = db.Column(
        db.String(32),
        db.ForeignKey("classroom_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: 同一个人可能开两个标签页，但这里只记一行（`user_id` 唯一）——
    #: 「在线 2」说的是两个人，不是两条连接（P3-A12 的两个标签页是同一人，
    #: 所以那条验收看的是连接数而不是这个数，见 classroom/roster.py）。
    role = db.Column(db.String(16), nullable=False, default="member")
    online = db.Column(db.Boolean, nullable=False, default=True)
    joined_at = db.Column(db.String(32), nullable=False, default=utcnow_iso)
    left_at = db.Column(db.String(32))

    session = db.relationship("ClassroomSession", back_populates="participants")

    __table_args__ = (
        enum_check("role", PARTICIPANT_ROLES, "participant_role_valid"),
        db.UniqueConstraint("session_id", "user_id", name="uq_participants_session_user"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "role": self.role,
            "online": bool(self.online),
            "joinedAt": self.joined_at,
            "leftAt": self.left_at or "",
        }

    def __repr__(self) -> str:
        return f"<Participant {self.session_id}/{self.user_id} online={self.online}>"


class SessionEvent(PkMixin, db.Model):
    """下行事件的留档（断线补发的唯一依据，AGENTS §17）。

    只增不改：`seq` 由 `sessions.next_seq()` 分配，同一会话内唯一（联合索引钉住）。
    没有 `updated_at`：事件写下来就不会变，多一列只会让人以为它可以改。
    """

    __tablename__ = "session_events"

    session_id = db.Column(
        db.String(32),
        db.ForeignKey("classroom_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(32), nullable=False)
    payload_json = db.Column(db.Text)
    created_at = db.Column(db.String(32), nullable=False, default=utcnow_iso)

    payload = JSONField("payload_json")

    session = db.relationship("ClassroomSession", back_populates="events")

    __table_args__ = (
        # 补发就是「给我 seq > N 的」，按它建唯一索引：既是查询索引，
        # 也顺手挡住「同一个 seq 写两次」——那种事一旦发生，客户端的去重
        # 就会把它当成重复事件丢掉，而丢的是**后写的那条**，很难查。
        db.UniqueConstraint("session_id", "seq", name="uq_session_events_session_seq"),
        db.Index("ix_session_events_session_type", "session_id", "type"),
    )

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "type": self.type,
            "payload": self.payload or {},
            "ts": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<SessionEvent {self.session_id}#{self.seq} {self.type}>"


class ClassroomMessage(PkMixin, TimestampMixin, db.Model):
    """消息流（讨论区那一栏，F3-4）。

    `ts` 与 `created_at` 是两回事：`ts` 是**这条消息在课堂时间线上的位置**
    （讲稿消息用的是 beat 的时刻，不是落库的时刻），`created_at` 是写库时间。
    记录页按 `ts` 排、按 `ts` 显示「07:32 沈老师：……」；`created_at` 只在排查
    「消息是什么时候进来的」时有用。两个都留着，别拿一个当另一个用。

    **`ts` 在同一会话内必须严格递增**（P3-C1），这是**写入方的责任**，不是
    `utcnow_iso()` 白送的：本机（Windows）`datetime.now()` 的粒度约 15.6ms，
    同一个滴答里写的两条消息会拿到一模一样的 ISO 串，`ORDER BY ts` 的先后
    就成了「数据库碰巧怎么返回」。讲稿与字幕常常就是同一批写下来的，
    所以 recorder 在写入前要拿会话里上一条的 `ts` 比一下，不前进就 +1µs。
    """

    __tablename__ = "messages"

    session_id = db.Column(
        db.String(32),
        db.ForeignKey("classroom_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    speaker_code = db.Column(db.String(32), nullable=False)
    speaker_kind = db.Column(db.String(16), nullable=False, default="teacher")
    type = db.Column(db.String(16), nullable=False, default="comment")
    text = db.Column(db.Text, nullable=False)
    page_no = db.Column(db.Integer)
    beat_id = db.Column(db.String(32))
    #: 有声音的发言才带它（讲稿与教师答疑）。相对路径，与音频资产同一口径（P2-C4）。
    audio_url = db.Column(db.String(255))
    #: 「引用/划重点」（F3-4）留的口子：P3 只做到「引用上一条」。
    quote_msg_id = db.Column(db.String(32))
    ts = db.Column(db.String(32), nullable=False, default=utcnow_iso)

    session = db.relationship("ClassroomSession", back_populates="messages")

    __table_args__ = (
        enum_check("speaker_kind", SPEAKER_KINDS, "message_speaker_kind_valid"),
        enum_check("type", MESSAGE_TYPES, "message_type_valid"),
        db.Index("ix_messages_session_ts", "session_id", "ts"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "speaker": self.speaker_code,
            "speakerKind": self.speaker_kind,
            "type": self.type,
            "text": self.text,
            "pageNo": self.page_no,
            "beatId": self.beat_id or "",
            "audioUrl": self.audio_url or "",
            "quoteMsgId": self.quote_msg_id or "",
            "ts": self.ts,
        }

    def __repr__(self) -> str:
        return f"<Message {self.id} {self.speaker_code}/{self.type}>"


class HandQueue(PkMixin, TimestampMixin, db.Model):
    """举手队列（F3-7）。一次举手一行，`called_at` 是被点名的时刻。

    没有 `name` 列：§5 里没有，而且它是 `users.name` 的副本 —— 用户改了名字，
    队列里那个旧名字就成了对不上的第二种事实。下行事件里的 `name` 由服务层
    现查（`roster`），这里只存「谁、什么时候、到哪一步了」。
    """

    __tablename__ = "hand_queue"

    session_id = db.Column(
        db.String(32),
        db.ForeignKey("classroom_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ts = db.Column(db.String(32), nullable=False, default=utcnow_iso)
    called_at = db.Column(db.String(32))
    status = db.Column(db.String(16), nullable=False, default="waiting")

    __table_args__ = (
        enum_check("status", HAND_STATUSES, "hand_status_valid"),
        db.Index("ix_hand_queue_session_status", "session_id", "status"),
    )

    def to_dict(self, name: str = "") -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "name": name,
            "ts": self.ts,
            "calledAt": self.called_at or "",
            "status": self.status,
        }

    def __repr__(self) -> str:
        return f"<Hand {self.id} {self.status}>"


class QuizAttempt(PkMixin, TimestampMixin, db.Model):
    """测验作答（F3-8）。P6.1 的学情聚合要从这张表算，所以一次作答一行，
    包括答错后重答的那一次 —— 「第一次答对率」与「最终答对率」是两个指标。"""

    __tablename__ = "quiz_attempts"

    session_id = db.Column(
        db.String(32),
        db.ForeignKey("classroom_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    page_no = db.Column(db.Integer, nullable=False)
    #: 题在页面 DSL 里的位置（`dsl.quiz.items[i].id` 之类）。
    #: 存下来才能在 P6 把「这道题大家错得多」对回题目本身。
    node_id = db.Column(db.String(64))
    #: 学生选的那一项 —— **整句选项文本**，不是 `A`/`B` 键。题面 DSL 里
    #: `quiz.options` 是四句话、`quiz.answer` 也是其中一句话（§ 技术实现方案 161），
    #: 判定就是拿两句话比。所以这一列要放得下一句话：16 个字符连一个中文选项
    #: 都装不完（示例课里最短那条是 17 个字），截断了就永远判不对。
    option = db.Column(db.String(255))
    correct = db.Column(db.Boolean, nullable=False, default=False)
    #: 学生从看到题到点提交用了多久（毫秒）。教学上有用，且它只能在这里采到。
    response_ms = db.Column(db.Integer)
    ts = db.Column(db.String(32), nullable=False, default=utcnow_iso)

    __table_args__ = (
        db.CheckConstraint("page_no > 0", name="quiz_attempt_page_positive"),
        db.Index("ix_quiz_attempts_session_page", "session_id", "page_no"),
        db.Index("ix_quiz_attempts_course_page", "course_id", "page_no"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "pageNo": self.page_no,
            "nodeId": self.node_id or "",
            "option": self.option or "",
            "correct": bool(self.correct),
            "responseMs": self.response_ms or 0,
            "ts": self.ts,
        }

    def __repr__(self) -> str:
        return f"<QuizAttempt {self.session_id}#{self.page_no} correct={self.correct}>"


class BoardStroke(PkMixin, TimestampMixin, db.Model):
    """板书画笔（§2.4）。一笔一行，按 `stroke_no` 排就是画它的顺序。

    `points_json` 存归一化坐标（0~1），不是像素：一块板书要在不同尺寸的窗口里
    「画」出来（老师在投影上、学生在手机上），存像素等于把它绑死在某个屏幕上。
    """

    __tablename__ = "board_strokes"

    session_id = db.Column(
        db.String(32),
        db.ForeignKey("classroom_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    page_no = db.Column(db.Integer, nullable=False)
    stroke_no = db.Column(db.Integer, nullable=False)
    tool = db.Column(db.String(16), nullable=False, default="polyline")
    color = db.Column(db.String(16), nullable=False, default="#1f2937")
    width = db.Column(db.Float, nullable=False, default=2.0)
    points_json = db.Column(db.Text)
    #: `tool=text` 时写什么字。§5 的表里没有这一列，但 §2.4 把 `text` 列为四种笔画
    #: 之一 —— 一列都不给，写字这一笔就只能把字符串塞进 `points_json` 里，
    #: 前端得靠「点的第三个元素是什么」来判断。加一列比那种约定便宜。
    text = db.Column(db.String(200))
    #: 这一笔在哪个 beat 出现（`boardPlan[i].atBeat`）。讲稿念到那儿，白板开始画。
    at_beat_id = db.Column(db.String(32))
    dur_ms = db.Column(db.Integer, nullable=False, default=800)
    author = db.Column(db.String(16), nullable=False, default="teacher")

    points = JSONField("points_json")

    session = db.relationship("ClassroomSession", back_populates="strokes")

    __table_args__ = (
        enum_check("author", STROKE_AUTHORS, "stroke_author_valid"),
        # `rect`/`ellipse` 是 §2.4 那四个之外的补充：板书画笔是**客户端也能发**的
        # （`board_sync` 上行），前端教具条里有「图形」。少一个值不是「严格」，
        # 是把一次合法输入变成 CHECK 违约的 500。工具条上有的都收。
        db.CheckConstraint(
            "tool IN ('polyline', 'curve', 'text', 'arrow', 'rect', 'ellipse')",
            name="stroke_tool_valid",
        ),
        db.CheckConstraint("page_no > 0", name="stroke_page_positive"),
        db.CheckConstraint("dur_ms >= 0", name="stroke_duration_non_negative"),
        # 取一页的板书 = (course, page) 全取按 stroke_no 排；换课换页都不用改查询
        db.Index("ix_board_strokes_course_page", "course_id", "page_no", "stroke_no"),
        db.Index("ix_board_strokes_session", "session_id", "page_no"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "pageNo": self.page_no,
            "strokeNo": self.stroke_no,
            "tool": self.tool,
            "color": self.color,
            "width": self.width,
            "points": self.points or [],
            "text": self.text or "",
            "atBeatId": self.at_beat_id or "",
            "durMs": self.dur_ms,
            "author": self.author,
        }

    def __repr__(self) -> str:
        return f"<Stroke {self.course_id}#{self.page_no}/{self.stroke_no} {self.tool}>"


__all__ = [
    "CLASSROOM_MODES",
    "CLASSROOM_STATUSES",
    "HAND_STATUSES",
    "MESSAGE_TYPES",
    "PARTICIPANT_ROLES",
    "SPEAKER_KINDS",
    "STROKE_AUTHORS",
    "BoardStroke",
    "ClassroomMessage",
    "ClassroomSession",
    "HandQueue",
    "QuizAttempt",
    "SessionEvent",
    "SessionParticipant",
]
