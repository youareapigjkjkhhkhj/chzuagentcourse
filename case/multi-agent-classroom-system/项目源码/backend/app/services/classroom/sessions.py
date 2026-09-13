"""课堂会话的开、取、进、出、结束（F3-1 / P3-A1 / P3-F4 / P3-F5）。

七个服务模块里，只有这一层对外回答「有没有这堂课、谁看得见、还能不能进」。
它自己不推进时间线（那是 `runtime`），也不写事件（那是 `recorder`），
只做四件事：

1. **开一堂课。** 建行、按时间线定总时长、把开课的人记成参与者。
   `status` 留在 `idle`——「开始上课」与「开始讲」是两件事：前者是开一个教室，
   后者是老师开口。分开之后 P3-B4（`idle` 的会话答题/举手返回 40901）才有意义。
2. **可见性（P3-F4）。** 课堂记录只对**创建者与参与者**可见，其他人 404。
   用既有的 `owned_by` 口径（AGENTS §4.1：越权回 404 而不是 403，
   403 等于承认「这个 id 存在，只是不给你看」）。
3. **并发上限（P3-F5）。** 一个人同时开的课最多 `CLASSROOM_MAX_SESSIONS_PER_USER`
   （默认 2）。数的是**没结束的**：上完的课不该挡着下一堂。
4. **准入票据。** 票据写 `scope=session.id`（见 `voice/tickets.py`）：
   为 A 课签的票接不进 B 课。P3-F1 要的「伪造 `sessionId` 接不进他人课堂」
   由两道组成 —— 签票时按可见性挡一次，核销时按用途再挡一次。
   这里只签票，核销在 WS 路由（P3-3）—— 票据服务是同一个。
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from app.common.dbw import db_write
from app.common.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from app.common.identity import owned_by
from app.common.logging import get_logger
from app.common.timeutil import utcnow_iso
from app.extensions import db
from app.models import CLASSROOM_MODES, ClassroomSession, Course, SessionParticipant
from app.services.classroom import recorder, state
from app.services.classroom import timeline as timeline_module
from app.services.voice import tickets

logger = get_logger("app.classroom.sessions")

MODE_AUTO = "auto"
MODE_MANUAL = "manual"

#: 推送关掉时退到哪条路（P3-G3）：逐页手动翻页 + 文字消息，退了但能用。
FALLBACK_MANUAL = "manual"

#: 业务码。与语音的 `VOICE_DISABLED_CODE` 同一个数、同一个意思：这是**部署方
#: 的一个决定**（开关关着），不是服务端故障 —— 前端据此显示提示条并退到
#: 手动那条路，而不是弹一个「服务器错误」。
CLASSROOM_DISABLED_CODE = 40302


class ClassroomDisabledError(AppError):
    """课堂推送通道关着（`CLASSROOM_WS=false`，P3-G3）。

    `data` 的形状跟语音那条对齐（平铺的 `ok/error/fallback`，不套 details）：
    两个错误在前端是同一段代码处理的 —— 都是「这个能力没了，退到某条路上去」。
    """

    code = CLASSROOM_DISABLED_CODE
    http_status = 403

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "课堂推送通道已关闭（CLASSROOM_WS=false），本堂课按逐页手动翻页进行"
        )

    def to_envelope(self):
        from app.common.response import fail_with_data

        return fail_with_data(
            self.code,
            {"ok": False, "error": "ws_disabled", "fallback": FALLBACK_MANUAL},
            self.message,
            self.http_status,
        )


# --- 开关与上限（配置一处读，别处不再问 current_app）---


def ws_enabled() -> bool:
    """课堂推送通道开着没有（P3-G3）。关掉后课堂退化为逐页手动翻页。"""
    return bool(current_app.config.get("CLASSROOM_WS", True))


def require_ws() -> None:
    """推送通道关着就抛 `ClassroomDisabledError`（路由用它挡下握手）。"""
    if not ws_enabled():
        raise ClassroomDisabledError()


def max_per_user() -> int:
    """一个人最多同时开几堂课（P3-F5）。<=0 表示不限制。"""
    return int(current_app.config.get("CLASSROOM_MAX_SESSIONS_PER_USER") or 0)


def max_connections() -> int:
    """一堂课最多几条连接（P3-F5）。<=0 表示不限制。"""
    return int(current_app.config.get("CLASSROOM_MAX_CONNECTIONS") or 0)


def ws_ticket_ttl() -> int:
    return int(tickets.TICKET_TTL_SECONDS)


# --- 开课 ---


def start(
    course: Course,
    owner_id: str,
    *,
    mode: str = "",
    timeline: timeline_module.Timeline | None = None,
) -> ClassroomSession:
    """开一堂课：建行、定时间线、把开课的人记成参与者（F3-1）。

    Args:
        course: 要上的课。
        owner_id: 开课的人。
        mode: `auto`（时间线自己走）/ `manual`（逐页手翻）。认不出来的按 `auto`；
            **`CLASSROOM_WS=false` 时 `auto` 降级为 `manual`** —— 没有推送通道，
            时间线就没有推进的手段，那时候宣称自己是 auto 只是记了个假状态。
        timeline: 已建好的时间线。不传就现建（读 `status=ready` 的页与音频资产）。

    Raises:
        ValidationError: 这门课还没有可讲的页面。
        RateLimitError: 这个人已经开着上限那么多个课堂（P3-F5，42901）。
    """
    line = timeline if timeline is not None else timeline_module.build(course)
    if not line.pages:
        raise ValidationError(
            "这门课还没有可讲的页面，先把它生成完再开课",
            details={"courseId": course.id},
        )
    _enforce_user_limit(owner_id)

    first = line.pages[0]
    chosen = _effective_mode(mode)

    def _write() -> ClassroomSession:
        row = ClassroomSession(
            course_id=course.id,
            owner_id=owner_id or None,
            mode=chosen,
            status=state.IDLE,
            current_page_no=first.page_no,
            current_beat_idx=0,
            elapsed_ms=line.offset_of(first.page_no, 0),
            total_ms=line.total_ms,
            speed=1.0,
            started_at=utcnow_iso(),
        )
        db.session.add(row)
        db.session.flush()
        return row

    session = db_write(_write)
    # 开课的人自己也在课堂里 —— 记录页对参与者可见（P3-F4），
    # 不写这一行的话，创建者之外没人能回看，而创建者换个浏览器就不是创建者了。
    join(session, owner_id, name=name_of(owner_id))
    logger.info(
        "开课：session=%s course=%s mode=%s 共 %s 页 / %s ms",
        session.id,
        course.id,
        chosen,
        len(line.pages),
        line.total_ms,
    )
    return session


# --- 取 ---


def get(session_id: str) -> ClassroomSession | None:
    value = str(session_id or "")
    return db.session.get(ClassroomSession, value) if value else None


def require(session_id: str) -> ClassroomSession:
    """按 id 取，取不到抛 404。**不判可见性** —— 那是 `require_visible` 的事。"""
    session = get(session_id)
    if session is None:
        raise NotFoundError("课堂不存在或已删除", details={"sessionId": str(session_id or "")})
    return session


def timeline_of(session: ClassroomSession, *, course: Course | None = None) -> timeline_module.Timeline:
    """这堂课的时间线。**每次现建**，不缓存成会话状态：

    课是可以在课前被改的（P1 能重生成某一页），而时间线是「这门课现在长什么样」
    的纯函数。缓存它就要处理失效，而失效处理错了的表现是「按旧时长讲新课」——
    一个只有听完整堂课才会发现的问题。
    """
    row = course if course is not None else db.session.get(Course, session.course_id)
    if row is None:
        return timeline_module.Timeline(pages=(), total_ms=0)
    return timeline_module.build(row)


# --- 可见性（P3-F4）---


def visible_to(session: ClassroomSession, owner_id: str) -> bool:
    """创建者与参与者可见，其他人不可见。

    空归属人的两条豁免沿用 `owned_by` 的口径（两边都空算通过）：
    单机本地会话（P0~P4）没有登录，多拦一道只会拦掉合法访问；
    真正的隔离要等 P4 有账号体系。**参与者**那一半是 P3 新增的：
    旁听的人既不是创建者，也不该被自己的记录页挡在外面。
    """
    if _participant_of(session, owner_id) is not None:
        return True
    return owned_by(session, owner_id)


def require_visible(session: ClassroomSession, owner_id: str) -> ClassroomSession:
    """不可见就抛 404（P3-F4：不是 403，别用错误码的差别确认「这个 id 存在」）。"""
    if not visible_to(session, owner_id):
        raise NotFoundError("课堂不存在或已删除", details={"sessionId": session.id})
    return session


# --- 进出 ---


def join(session: ClassroomSession, user_id: str, *, name: str = "") -> dict:
    """一个人进课堂。身份按「是不是创建者」定 —— 让调用方自己传 role，
    迟早有一处传成 `owner`，而记录页的归属就跟着错。

    同一个人重复进来只更新一行（`recorder.join` 的既有语义）：
    「在线 5」数的是人，不是标签页。
    """
    owner = str(session.owner_id or "")
    role = "owner" if owner and owner == str(user_id or "") else "member"
    return recorder.join(session.id, user_id, role=role, name=name or name_of(user_id))


def leave(session: ClassroomSession, user_id: str) -> None:
    recorder.leave(session.id, user_id)


def ws_ticket(session: ClassroomSession, owner_id: str, *, ttl: int | None = None) -> dict[str, Any]:
    """给这个人签一张**只对这堂课有效**的接入票据（P3-F1）。

    签之前判可见性：不可见的人在这里就拿到 404，而不是先给他一张票、
    等握手时才失败 —— 那时客户端只能看到一次「连接失败」，说不出为什么。

    Raises:
        NotFoundError: 不是创建者也不是参与者（404，与 P3-F4 同一口径）。
        ConflictError: 课已经结束了，再接进来没有意义。
    """
    require_visible(session, owner_id)
    if str(session.status or "") == state.ENDED:
        raise ConflictError("这堂课已经结束了，不能再接入", details={"status": session.status})
    return tickets.issue(
        owner_id,
        ttl=ttl if ttl is not None else ws_ticket_ttl(),
        scope=session.id,
    )


# --- 结束与列表 ---


def end(session: ClassroomSession, *, reason: str = "") -> dict:
    """结束这堂课（`POST /sessions/{id}/end`）：转 `ended` 并落库，返回状态载荷。

    转状态走 `state.transition`——它是唯一写 `ended_at` 的地方，也是唯一
    会拒绝「从 `ended` 再转一次」的地方：重复调用下课接口是幂等的成功，
    不该把结束时刻改成第二次点击的时间。

    同时往事件留档里写一条 `state`：正在看的人由 WS 层（P3-3）用同一份载荷
    广播，而重连回来的人靠留档也能知道课已经下了 —— 两处用的是同一个 dict。
    """
    state.transition(session, state.ENDED, reason=reason or "课堂结束")
    _flush(session)
    payload = state.snapshot(session).to_dict()
    event = recorder.publish(session, "state", payload)
    logger.info("下课：session=%s reason=%s", session.id, reason or "课堂结束")
    return event


def active_of(owner_id: str) -> list[ClassroomSession]:
    """这个人手上还没结束的课堂，新的在前（P3-F5 数的是这个）。"""
    owner = str(owner_id or "")
    if not owner:
        return []
    return (
        ClassroomSession.query.filter(
            ClassroomSession.owner_id == owner,
            ClassroomSession.status != state.ENDED,
        )
        .order_by(ClassroomSession.started_at.desc(), ClassroomSession.id.desc())
        .all()
    )


def summary(session: ClassroomSession) -> dict:
    """`GET /sessions/{id}` 的载荷：会话状态 + 在线情况 + 课名。

    带上 `courseTitle` 是为了让记录页与顶栏不必为了一个标题再请求一次课——
    而那一次请求还要再判一次可见性。
    """
    course = db.session.get(Course, session.course_id)
    payload = session.to_dict()
    payload["courseTitle"] = course.title if course is not None else ""
    payload["presence"] = recorder.presence(session.id)
    return payload


def name_of(user_id: str) -> str:
    """一个用户的显示名。查不到、或没给 id，都给空串。

    只查一个人的这一条，走的是 `recorder.names_of` 的同一个实现 ——
    「名字怎么来的」只该有一处（那边一次 `IN` 查一批，这边只是它的单数形式）。
    """
    value = str(user_id or "")
    if not value:
        return ""
    return recorder.names_of([value]).get(value, "")


# --- 内部 ---


def _effective_mode(mode: str) -> str:
    chosen = str(mode or "").strip()
    if chosen not in CLASSROOM_MODES:
        chosen = MODE_AUTO
    if chosen == MODE_AUTO and not ws_enabled():
        logger.info("课堂推送已关闭（CLASSROOM_WS=false），这堂课按逐页手动翻页开")
        return MODE_MANUAL
    return chosen


def _enforce_user_limit(owner_id: str) -> None:
    limit = max_per_user()
    owner = str(owner_id or "")
    # 没有归属人就无从数起（单机本地会话的默认路径）——不拦，与 owned_by 同一口径
    if limit <= 0 or not owner:
        return
    running = active_of(owner)
    if len(running) >= limit:
        raise RateLimitError(
            f"你已经有 {len(running)} 堂课在上了，先结束其中一堂再开新的",
            details={
                "limit": limit,
                "sessions": [row.id for row in running],
            },
        )


def _participant_of(session: ClassroomSession, user_id: str) -> SessionParticipant | None:
    """这堂课里这个人那行（在线与否都算上过）。

    空 `user_id` 不参与匹配：它在库里是「没有归属」，不是「某个人」——
    按它查会匹配到所有 `user_id IS NULL` 的行。
    """
    value = str(user_id or "")
    if not value:
        return None
    return SessionParticipant.query.filter_by(session_id=session.id, user_id=value).first()


def _flush(_session: ClassroomSession) -> None:
    """把内存里改过的字段落库（`state.transition` 只改对象，不写库）。"""
    db_write(db.session.flush)


__all__ = [
    "CLASSROOM_DISABLED_CODE",
    "FALLBACK_MANUAL",
    "MODE_AUTO",
    "MODE_MANUAL",
    "ClassroomDisabledError",
    "active_of",
    "end",
    "get",
    "join",
    "leave",
    "max_connections",
    "max_per_user",
    "name_of",
    "require",
    "require_visible",
    "require_ws",
    "start",
    "summary",
    "timeline_of",
    "visible_to",
    "ws_enabled",
    "ws_ticket",
    "ws_ticket_ttl",
]
