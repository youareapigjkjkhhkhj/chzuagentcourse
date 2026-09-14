"""发言调度器：同一时刻只有一个说话者（§2.2）。

这是 P3 最要紧的一条约束 —— 两个 AI 同时出声，课堂当场崩塌（P3-A2 用脚本
断言 `speak` 事件的区间不重叠）。所以队列只有**一个出口**：`next()`。
谁都不能直接说话，只能入队；由 runtime 在合适的时机取下一个。

四条规则，逐条对着 §2.2 写：

1. **优先级**：学生提问(barge) > 教师答疑(answer) > 同学插话(interject)
   > 同学讨论(discussion) > 教师讲授(lecture)。
2. **抢占**：学生提问可抢占**除教师答疑外**的所有发言；被抢占的 Turn **丢弃，
   不补播** —— 补播会让课堂拖沓，而且那句话说出口的时机已经过去了。
3. **TTL**：任何 Turn 排队超过 20s 未播即丢弃。恢复播放时不该一次性蹦出
   五条过期发言（那是在补一段没人还记得的对话）。
4. **轮次**：`discussing` 的最大轮数与总时长按「讨论激烈程度」映射。

这一层是纯逻辑：不碰数据库，也不认识 WebSocket。`clock` 可注入，
所以「排队 21 秒后被丢掉」这类断言不需要真的等 21 秒。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from app.common.logging import get_logger

logger = get_logger("app.classroom.scheduler")

#: 五类发言的优先级。数字本身没有意义，比大小才有（`speak` 事件里会带上它）。
PRIORITY_LECTURE = 10
PRIORITY_DISCUSSION = 20
PRIORITY_INTERJECT = 30
PRIORITY_ANSWER = 40
PRIORITY_BARGE = 50

PRIORITIES: dict[str, int] = {
    "lecture": PRIORITY_LECTURE,
    "discussion": PRIORITY_DISCUSSION,
    "interject": PRIORITY_INTERJECT,
    "answer": PRIORITY_ANSWER,
    "barge": PRIORITY_BARGE,
}

#: 打断清不掉的两类。§2.2 的原话是「可抢占**除教师答疑外**的所有发言」；
#: `barge` 自己也在里面 —— 一个学生的提问不该把另一个刚被点名的提问顶掉。
PROTECTED_KINDS = ("answer", "barge")

#: 激烈程度 → 最大轮数 / 讨论总时长上限（秒）（§2.2）。
ROUNDS_BY_LEVEL: dict[str, int] = {"低": 1, "适中": 2, "高": 3}
SECONDS_BY_LEVEL: dict[str, float] = {"低": 60.0, "适中": 90.0, "高": 120.0}
DEFAULT_LEVEL = "适中"

#: 设置里那一档（`settings_service.INTENSITIES` 的 `low|medium|high`）
#: → 这一层的三档。两套词是历史：设置页是英文枚举（要进请求体、进日志），
#: 提示词与文档用的是中文档位。桥架在**消费端**（这里），因为生成时的档位
#: 是「这门课要多激烈」，而讨论轮数是课堂的事 —— 反过来桥就要让设置服务
#: 认识课堂的字段。
INTENSITY_LEVELS: dict[str, str] = {"low": "低", "medium": "适中", "high": "高"}

#: 队列长度上限。课堂里的队列正常只有一两项（讲稿是「说完一条再排下一条」），
#: 到几十项说明有人/有东西在灌 —— 满了就按优先级挤掉最不重要的那条。
MAX_PENDING = 50

#: 默认 TTL（秒）。可被 `CLASSROOM_TURN_TTL` 覆盖。
DEFAULT_TTL_SEC = 20.0


@dataclass
class Turn:
    """一次发言。`text` 是完整内容，`beat_ids` 是它覆盖的讲稿 beat。"""

    speaker_code: str
    text: str
    kind: str = "lecture"
    speaker_name: str = ""
    speaker_kind: str = "teacher"
    page_no: int = 0
    beat_ids: tuple[str, ...] = ()
    audio_url: str = ""
    #: 这段音频有多长（毫秒）。**有音频就必须带上它**：课堂的节奏（什么时候
    #: 换下一条发言、什么时候算说完）是按这个数计时的，而 runtime 拿不到
    #: 音频文件的时长 —— 讲稿走 `beat_ids` 查清单，答疑这种当场合成的没有
    #: beat 可查，只能由造 Turn 的那一步把时长一起递进来。
    duration_ms: int = 0
    message_type: str = "lecture"
    #: 这条发言是**回谁**说的（落库进 `messages.quote_msg_id`）。引导式答疑靠它
    #: 把「学生问 → 老师追问 → 学生答 → 老师收束」串成一条链，记录页据此画出
    #: 思辨轨迹（`scaffold.build_trails`）。讲稿、插话不带 —— 它们不是回复。
    quote_msg_id: str = ""
    #: 讲稿的时间戳（`ts`）—— 讲稿消息在时间线上的位置由 beat 决定，
    #: 不是「写库的那一刻」，所以它随 Turn 一起传。
    ts: str = ""
    #: 最早什么时候能开口（`clock()` 的刻度）。0 = 立刻。
    #:
    #: 讲稿是「一拍说完，隔一口气再说下一拍」，那口气就落在这儿（`runtime._gap_before`）。
    #: **答疑、插话、讨论都不带它**：学生问完，老师那句「我听听」本来就不该再等；
    #: 只有「上一拍讲完了自然地接下一拍」才需要留白。
    not_before: float = 0.0
    meta: dict = field(default_factory=dict)
    turn_id: str = ""
    priority: int = 0
    ttl_sec: float = DEFAULT_TTL_SEC
    queued_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.turn_id:
            self.turn_id = f"t_{uuid.uuid4().hex[:12]}"
        if not self.priority:
            self.priority = PRIORITIES.get(self.kind, PRIORITY_LECTURE)

    @property
    def protected(self) -> bool:
        return self.kind in PROTECTED_KINDS

    def to_dict(self) -> dict:
        """`speak` 事件的载荷（§4.2）。"""
        return {
            "turnId": self.turn_id,
            "speaker": {"code": self.speaker_code, "name": self.speaker_name or self.speaker_code},
            "speakerKind": self.speaker_kind,
            "text": self.text,
            "audioUrl": self.audio_url,
            "beats": list(self.beat_ids),
            "kind": self.kind,
            "priority": self.priority,
            "pageNo": self.page_no,
        }


class SpeechScheduler:
    """串行发言队列。**单写者**：只有 `next()` 能把排队的东西放出来。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_sec: float = DEFAULT_TTL_SEC,
        max_pending: int = MAX_PENDING,
    ) -> None:
        self._clock = clock
        self._ttl_sec = float(ttl_sec)
        self._max_pending = int(max_pending)
        self._pending: list[Turn] = []
        self._active: Turn | None = None

    # --- 读 ---

    @property
    def active(self) -> Turn | None:
        return self._active

    @property
    def pending(self) -> tuple[Turn, ...]:
        return tuple(self._pending)

    @property
    def speaking(self) -> bool:
        """正在说话。runtime 靠它判断「能不能开始下一段」。"""
        return self._active is not None

    def queue_summary(self) -> list[dict]:
        return [
            {"turnId": turn.turn_id, "speaker": turn.speaker_code, "kind": turn.kind}
            for turn in self._pending
        ]

    # --- 写 ---

    def enqueue(self, turn: Turn) -> Turn | None:
        """入队。队满且这条最不重要时返回 None（它被丢掉了）。"""
        if not turn.ttl_sec:
            turn.ttl_sec = self._ttl_sec
        turn.queued_at = self._clock()
        self._drop_expired()

        if len(self._pending) >= self._max_pending:
            weakest = min(self._pending, key=lambda item: (item.priority, item.queued_at))
            if weakest.priority >= turn.priority:
                logger.warning(
                    "课堂发言队列已满（%s），丢掉新来的 %s/%s",
                    self._max_pending,
                    turn.kind,
                    turn.speaker_code,
                )
                return None
            self._pending.remove(weakest)

        self._pending.append(turn)
        return turn

    def next(self) -> Turn | None:
        """取出下一条该说的发言，并把它置为 active。

        有 active 时返回 None —— 这就是「单写者」在代码里的样子：
        不是靠调用方自觉，而是这里根本不给第二条。
        """
        if self._active is not None:
            return None
        self._drop_expired()
        if not self._pending:
            return None
        # 高优先级先出；同级按入队先后（FIFO），保证讨论有来有回而不是抢话
        chosen = max(
            enumerate(self._pending), key=lambda item: (item[1].priority, -item[0])
        )[1]
        # 还不到开口的时候（`not_before`）：**留在队列里**，等下一拍再问
        # （`tick` 每 50ms 走一次）。取出来再放回去不行 —— 那会把入队顺序打乱，
        # 而同级发言的先后就是靠入队顺序定的（上面那句 FIFO）。
        if chosen.not_before and chosen.not_before > self._clock():
            return None
        self._pending.remove(chosen)
        self._active = chosen
        return chosen

    def begin(self, turn: Turn) -> Turn:
        """直接把一条发言置为 active（讲稿这类「不等队列」的路径用）。"""
        self._active = turn
        return turn

    def finish(self, turn_id: str = "") -> Turn | None:
        """当前发言结束。传了 `turn_id` 且对不上就什么都不做 ——

        迟到的 `speak_end` 不该把下一段已经开始的话掐掉。
        """
        if self._active is None:
            return None
        if turn_id and self._active.turn_id != turn_id:
            return None
        finished = self._active
        self._active = None
        return finished

    def interrupt(self, reason: str = "barge") -> dict:
        """打断：清掉排队的低优先级发言，必要时把正在说的也停下（§2.2）。

        返回 `{"dropped": [...], "preempted": Turn | None}`：
        `preempted` 非空时，调用方要发一条 `speak_end`（带 `preempted: true`）
        让前端立刻停声 —— 这正是 P3-A6 量的「≤1s 内停口」。
        """
        dropped = [turn for turn in self._pending if not turn.protected]
        self._pending = [turn for turn in self._pending if turn.protected]

        preempted: Turn | None = None
        if self._active is not None and not self._active.protected:
            preempted = self._active
            self._active = None

        if dropped or preempted:
            logger.info(
                "课堂发言被打断（%s）：丢弃排队 %s 条，中断当前 %s",
                reason,
                len(dropped),
                preempted.turn_id if preempted else "无",
            )
        return {"dropped": dropped, "preempted": preempted}

    def clear(self) -> None:
        """整堂课的发言清空（结束课堂、跳出课堂时用）。"""
        self._pending.clear()
        self._active = None

    def _drop_expired(self) -> list[Turn]:
        """丢掉排队超时的（§2.2 的 TTL）。"""
        if not self._pending:
            return []
        now = self._clock()
        alive: list[Turn] = []
        expired: list[Turn] = []
        for turn in self._pending:
            if turn.ttl_sec and now - turn.queued_at > turn.ttl_sec:
                expired.append(turn)
            else:
                alive.append(turn)
        if expired:
            self._pending = alive
            logger.info("课堂发言排队超时，丢弃 %s 条：%s", len(expired), [t.turn_id for t in expired])
        return expired


def normalize_level(value: str) -> str:
    """任何一档激烈程度 → 这里的三档。

    收三种写法：`低/适中/高`（认得的直接过）、`low/medium/high`（设置页那一套）、
    其余（空、拼错、别的语言）一律按「适中」—— 一个读不出来的档位不该让
    章末讨论开不起来。
    """
    raw = str(value or "").strip()
    if raw in ROUNDS_BY_LEVEL:
        return raw
    return INTENSITY_LEVELS.get(raw.lower(), DEFAULT_LEVEL)


def rounds_for(level: str) -> int:
    """激烈程度 → 讨论最多几轮。不认识的程度按「适中」。"""
    return ROUNDS_BY_LEVEL.get(str(level or "").strip(), ROUNDS_BY_LEVEL[DEFAULT_LEVEL])


def seconds_for(level: str) -> float:
    """激烈程度 → 讨论总时长上限（秒）。"""
    return SECONDS_BY_LEVEL.get(str(level or "").strip(), SECONDS_BY_LEVEL[DEFAULT_LEVEL])


__all__ = [
    "DEFAULT_LEVEL",
    "DEFAULT_TTL_SEC",
    "INTENSITY_LEVELS",
    "MAX_PENDING",
    "PRIORITIES",
    "PRIORITY_ANSWER",
    "PRIORITY_BARGE",
    "PRIORITY_DISCUSSION",
    "PRIORITY_INTERJECT",
    "PRIORITY_LECTURE",
    "PROTECTED_KINDS",
    "ROUNDS_BY_LEVEL",
    "SECONDS_BY_LEVEL",
    "SpeechScheduler",
    "Turn",
    "normalize_level",
    "rounds_for",
    "seconds_for",
]
