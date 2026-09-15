"""课堂接口（P3 §4）：§4.1 的十条 HTTP + §4.2 的一条 WebSocket。

分开写不是分家：接口层只做三件事 —— 取参数、调 service、包信封，而 WS 那一条
比别的多一件（接上 socket、把两端接起来、收工时收摊）。

**HTTP 与 WS 共用同一份 service 函数**（`runtime.raise_hand` / `submit_quiz` /
`announce_*` 就是给两边用的），所以课堂上有人用 WS、有人走 HTTP，看到的都是
同一条事件流：两边都只 `publish`，投递由连接层按 `seq` 扫留档（§4.2 契约要点）。
反过来写两套逻辑，两套迟早会对同一次举手给出不同的位置。

**归属一律走 `current_owner_id()`，可见性一律 404**（AGENTS §4.1）：课堂不存在、
已删除、不是创建者也不是参与者，给的都是同一句话。403 等于承认「这个 id 存在，
只是不给你看」，那就是一个能枚举别人课堂的信息口子。

**票据为什么走 URL 而不是等 `hello.token`**：两条入口都认（见
`services/classroom/channel.py` 的 `_enter`），但前端该走 URL 这一条 ——
票据不对、这堂课不给他看，这两件事在**握手之前**就判得出来，客户端拿到的是
一个能显示的错误信封（HTTP 401/404），而不是一条连上了又立刻断掉的 socket。
P2 的路由踩过这个坑（见 `app/api/voice.py` 的 `realtime_voice`），这里照旧。
`hello.token` 留着，是因为 §4.2 的协议里它就是 `hello` 的字段。
"""

from __future__ import annotations

from contextlib import suppress

from flask import Blueprint, request

from app.api import json_body
from app.common.errors import ValidationError
from app.common.identity import current_owner_id
from app.common.logging import get_logger
from app.common.response import ok
from app.services.classroom import board, record, recorder, runtime, sessions
from app.services.courses import library as course_library
from app.services.voice import tickets

logger = get_logger("app.api.classroom")

#: 消息分页默认一页多少条。讨论区一屏十来条，50 够翻好几屏，
#: 也不至于让第一次进来的那一条响应塞进几百 KB。
DEFAULT_PAGE_SIZE = 50

bp = Blueprint("classroom", __name__)


# --- §4.1 HTTP ---


@bp.post("/api/classroom/sessions")
def start_session():
    """开始上课（F3-1）：建会话、定时间线，并**顺手签一张接入票据**。

    请求示例：
        POST /api/classroom/sessions
        {"courseId": "c_01H…", "mode": "auto"}

    返回 `{sessionId, wsToken, mode, status, timeline}`。票据与建会话在同一个
    响应里给，是为了让前端紧接着那一步 `new WebSocket(…?ticket=…)` 不用再多
    一次往返 —— 票据只有 60 秒（`tickets.TICKET_TTL_SECONDS`），往返越多越容易
    在手滑的网络上过期。

    `mode` 回的是**服务端实际用的那个**，不是请求里那个：`CLASSROOM_WS=false`
    时 `auto` 会降级成 `manual`（`sessions.start` 里判的），前端据此决定要不要
    显示「手动翻页」那条提示 —— 拿请求里那个值去显示，就会在推送关掉的部署里
    骗自己「自动上课中」。
    """
    payload = json_body()
    course_id = str(payload.get("courseId") or "").strip()
    if not course_id:
        raise ValidationError("courseId 不能为空")
    owner = current_owner_id()
    course = course_library.course_or_404(course_id, owner)

    session = sessions.start(course, owner, mode=str(payload.get("mode") or ""))
    ticket = sessions.ws_ticket(session, owner)
    return ok(
        {
            "sessionId": session.id,
            "wsToken": ticket["ticket"],
            "mode": session.mode,
            "status": session.status,
            "timeline": sessions.timeline_of(session, course=course).to_dict(),
        },
        http_status=201,
    )


@bp.get("/api/classroom/sessions")
def list_sessions():
    """我正在上的课（P3-F5：撞上限时**得有个地方把占着名额的那堂关掉**）。

    请求示例：
        GET /api/classroom/sessions

    每人同时在上的课有上限（`CLASSROOM_MAX_SESSIONS_PER_USER`，默认 2）。撞上时
    `POST /sessions` 回 42901，`details.sessions` 里只有一串会话 id —— 那是给程序
    看的：人对着一串 id 既认不出是哪门课，界面上也没地方点「结束」，于是那句话
    就成了一句没法照做的提示。

    返回 `{items, limit}`：这个人还没结束的课，新的在前，每条与 `GET /sessions/{id}`
    同一个形状（课名、讲到第几页、状态、谁在线都在里面），前端据此列出
    「进入 / 结束」。**下课仍然只走 `POST /sessions/{id}/end`** —— 这一条只回答
    「有哪些」，不另开第二种下课方式（两条路迟早对同一次下课给出不同结果）。
    """
    owner = current_owner_id()
    items = [sessions.summary(row) for row in sessions.active_of(owner)]
    return ok({"items": items, "limit": sessions.max_per_user()})


@bp.get("/api/classroom/sessions/<session_id>")
def get_session(session_id: str):
    """会话状态：页号、beat 索引、状态、在线情况（F3-1 刷新恢复靠它）。

    请求示例：
        GET /api/classroom/sessions/cs_01H…

    刷新页面后前端先问这一条：现在讲到哪、谁还在线。**它不等于 WS 的 `state`
    事件** —— `state` 是变化时推的，这一条是「此刻是什么」，两者读的是同一个
    `state.snapshot`。
    """
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    return ok(sessions.summary(session))


@bp.post("/api/classroom/sessions/<session_id>/ticket")
def renew_ticket(session_id: str):
    """重签一张接入票据（F3-13 / P3-A10 刷新恢复 / P3-A11 断线重连）。

    请求示例：
        POST /api/classroom/sessions/cs_01H…/ticket

    返回 `{wsToken, ttlSec}`。**票据是一次性的**（`tickets.consume` 取走就没了），
    所以「刷新页面」与「断线重连」这两件事都必然要再签一张：前者手上那张已经
    随页面一起没了，后者那张在断开前已经用掉了。少了这一条，前端只剩
    「重新 `POST /sessions` 开一堂新课」这一条路 —— 那会把同一门课开成一串
    互不相关的会话，而课上到一半的位置、板书、举手队列全都在旧会话里。

    **对已结束的课返回 40901**（`sessions.ws_ticket` 判的），与课堂上其余
    「已经结束了」的答复同一句 —— **不是重新开一堂课**：那样同一门课会开成
    一串互不相干的会话，课上到一半的位置、板书、举手队列全留在旧的那一堂里。
    下课之后要接着看，走的是记录页（P3-6，`GET /record`）。
    """
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    ticket = sessions.ws_ticket(session, current_owner_id())
    return ok({"wsToken": ticket["ticket"], "ttlSec": sessions.ws_ticket_ttl()})


@bp.post("/api/classroom/sessions/<session_id>/end")
def end_session(session_id: str):
    """下课（F3-1）：转 `ended` 并落库，正在看的人由 WS 层广播同一条事件。

    请求示例：
        POST /api/classroom/sessions/cs_01H…
        {"reason": "讲完了"}

    **重复调用是幂等的成功**：`state.transition` 对「已经在 `ended`」直接返回，
    不会把结束时刻改成第二次点的时间（用户手滑点两下不该改历史）。
    返回 `{session, event}` —— `event` 就是 WS 上那条 `state`，两边一模一样。
    """
    payload = json_body(required=False)
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    event = sessions.end(session, reason=str(payload.get("reason") or ""))
    return ok({"session": sessions.summary(session), "event": event})


@bp.get("/api/classroom/sessions/<session_id>/record")
def get_record(session_id: str):
    """课堂记录（F3-11 / P3-A14）：完整字幕、消息、板书快照、测验作答。

    请求示例：
        GET /api/classroom/sessions/cs_01H…/record

    读的是 `messages` / `board_strokes` / `quiz_attempts`，**不读事件留档**
    （留档有上限，见 `services/classroom/record.py` 的模块注释）。正在上的课也能
    看，拿到的是「到此刻为止」。
    """
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    return ok(record.build(session))


@bp.get("/api/classroom/sessions/<session_id>/messages")
def list_messages(session_id: str):
    """消息分页（F3-4）：讨论区往上翻用它。

    请求示例：
        GET /api/classroom/sessions/cs_01H…/messages?before=<上一条的 ts>&size=50

    `before` 传一个 `ts` 表示「给我比它更早的」；返回按时间正序，`hasMore`
    说还有没有更早的。**新连接的历史走这一条**，WS 不给新连接重放
    （§4.2 契约要点：新连接从此刻起收）。
    """
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    items, has_more = recorder.messages(
        session.id,
        before=str(request.args.get("before") or "").strip(),
        size=_int_arg("size", DEFAULT_PAGE_SIZE),
    )
    return ok({"items": items, "hasMore": has_more, "total": recorder.message_count(session.id)})


@bp.post("/api/classroom/sessions/<session_id>/raise-hand")
def raise_hand(session_id: str):
    """举手 / 撤回 / 点名（F3-7 / P3-A5）：入队并广播 `hand_queue`。

    请求示例：
        POST /api/classroom/sessions/cs_01H…/raise-hand
        {"action": "raise"}

    `action` 取 `raise | lower | call`，默认 `raise`。三条动作与 WS 上行的
    `hand` 是**同一批函数**（`runtime.raise_hand` / `lower_hand` / `call_student`）：
    同一个班里有人的浏览器只能走 HTTP（推送关掉、或者那条 socket 刚断），
    两条路对同一次举手必须给出同一个位次。

    返回 `{hand, position}`：`position` 是「第 N 位」（从 1 起，0 表示不在队里）。
    课没开始（`idle`）时返回 40901（P3-B4）。
    """
    payload = json_body(required=False)
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    action = str(payload.get("action") or "raise").strip() or "raise"
    owner = current_owner_id()
    if action == "lower":
        return ok(runtime.lower_hand(session, owner))
    if action == "call":
        return ok({"called": runtime.call_student(session)})
    return ok(runtime.raise_hand(session, owner))


@bp.post("/api/classroom/sessions/<session_id>/quiz-submit")
def quiz_submit(session_id: str):
    """提交测验答案（F3-8 / P3-A7）：判定、落库，并把 `quiz_result` 广播出去。

    请求示例：
        POST /api/classroom/sessions/cs_01H…/quiz-submit
        {"option": "B", "responseMs": 4200}

    返回 `quiz_result` 的载荷：`{pageNo, correct, option, answer, explain, branch,
    feedback}`（`feedback` 见 P6.1 的三档分支）。答完课回到 `lecture` 但**位置不动**
    —— 由客户端再报一次 `beat_done` 继续。

    **反馈那一句在这条路上是静默的**：发言队列在每条连接的运行时里，HTTP 够不着
    （`runtime._deliver_feedback` 的说明）。要让它出声，作答走 WS 上行
    `quiz_answer` —— 判定完全相同，只是那一句能进队说出来。

    答案与解析**只在判定之后**给：题目下发时 `quiz` 事件里没有这两个字段
    （见 `runtime.quiz_question`），否则前端看一眼 network 就有答案了。
    """
    payload = json_body()
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    event = runtime.submit_quiz(
        session,
        option=str(payload.get("option") or ""),
        response_ms=_int_of(payload.get("responseMs")),
    )
    return ok(event)


@bp.get("/api/classroom/sessions/<session_id>/board/<int:page_no>")
def get_board(session_id: str, page_no: int):
    """这一页的板书笔画（F3-9 / P3-A8）：与课上白板看到的是同一份。

    请求示例：
        GET /api/classroom/sessions/cs_01H…/board/7

    归一化坐标（0~1）按 `strokeNo` 排序 —— 排出来就是画它的顺序，重放直接照着
    刷一遍。没有板书的页返回空数组，不是 404：**「这页没有板书」与「这页不存在」
    是两件事**，而后者由会话本身的可见性管。
    """
    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    return ok({"pageNo": page_no, "strokes": board.strokes_of(session, page_no)})


# --- P6.1 学情总览 ---


@bp.get("/api/classroom/sessions/<session_id>/mastery")
def get_mastery(session_id: str):
    """学情总览（P6.1）：按章掌握度 + 错题列表 + 复习页记录。

    请求示例：
        GET /api/classroom/sessions/cs_01H…/mastery

    返回 `{chapters, wrongQuestions, reviewPages}`：
    - `chapters`：每章的总题数、正确数、掌握度百分比
    - `wrongQuestions`：错题列表（含概念标签与响应时间）
    - `reviewPages`：动态插入的复习页（同章连错触发）

    还在上的课也能看，拿到的是「到此刻为止」。
    """
    from app.models.mastery import ReviewPage, get_chapter_mastery, get_wrong_questions

    session = sessions.require_visible(sessions.require(session_id), current_owner_id())
    chapters = get_chapter_mastery(session.course_id)
    wrong = get_wrong_questions(session.course_id)
    reviews = (
        ReviewPage.query.filter_by(session_id=session.id)
        .order_by(ReviewPage.created_at.asc())
        .all()
    )
    return ok({
        "chapters": chapters,
        "wrongQuestions": wrong,
        "reviewPages": [row.to_dict() for row in reviews],
    })


# --- §4.2 WebSocket ---


@bp.route("/ws/classroom/<session_id>", websocket=True)
def classroom_socket(session_id: str):
    """课堂的双向通道（P3-3 / §4.2 / F3-14）。

    请求示例：
        GET /ws/classroom/cs_01H…?ticket=<POST /api/classroom/sessions 拿到的 wsToken>
        （浏览器里是 `new WebSocket(`ws://${location.host}/ws/classroom/${id}?ticket=…`)`）

    上行走 `hello / play / pause / seek / beat_done / ask / chat / hand /
    quiz_answer / board_sync / speed`，下行走 `state / speak / speak_end / subtitle /
    message / hand_queue / board / quiz / quiz_result / presence`，
    外加两条**每连接私有**的帧：`error` 与 `ping`（§4.2 的契约要点）。
    所有协议语义都在 `ClassroomChannel` 里 —— 因为 Flask 的测试客户端做不了
    WebSocket 升级，契约测试（P3-B1）只能打在那一层上，逻辑留在这里等于没测到。

    这条路由只做四件事：校开关、核销票据、接上 socket、交给连接层跑到底。
    校可见性在**核销票据之后**（只有拿到归属人才知道该拿谁去比）：
    拿着一张为别人签的票来接这堂课 → 404，与课堂记录页同一个口径（P3-F4）。

    票据要在 `accept()` **之前**核销：核销失败时我们抛出去，走的是普通的错误
    信封，浏览器连 101 都拿不到 —— 那才是「握手被拒绝」。
    """
    from simple_websocket import ConnectionClosed, Server

    from app.services.classroom.channel import ClassroomChannel

    # P3-G3：关掉推送通道不等于课堂不能用，退到「逐页手动翻页 + 文字消息」。
    # `fallback` 说清退到哪条路 —— 与语音的 `VOICE_ENABLED=false` 同一口径。
    sessions.require_ws()

    session = sessions.require(session_id)
    owner_id = _entry_owner(session)

    try:
        socket = Server.accept(request.environ)
    except ConnectionClosed:  # pragma: no cover - 握手失败，客户端已经走了
        return ""

    transport = _SocketTransport(socket)
    channel = ClassroomChannel(session, owner_id=owner_id)
    # run() 自己会 close（判死、断开、下课三条路都走它的 finally）
    channel.run(transport)
    return ""


class _SocketTransport:
    """`simple_websocket.Server` → 连接层的 `Transport`。

    唯一的工作是把「对端断开」翻成 `ChannelClosed`：连接层不该 import 任何
    WebSocket 库的类型，否则契约测试就得连带跑一个真 WebSocket 客户端，
    而测一条协议不该先起一个端口。（P2 的 `_SocketTransport` 是同一个东西，
    它翻成的是语音通道的 `ChannelClosed` —— 两条通道各有各的语义层，
    共用一个转发器只会让一边改了异常类型、另一边静默失效。）
    """

    def __init__(self, socket) -> None:
        self._socket = socket

    def receive(self, timeout: float):
        return self._call("receive", timeout=timeout)

    def send(self, data: str | bytes) -> None:
        self._call("send", data)

    def close(self, code: int, reason: str) -> None:
        """按关闭码收工。**已经关过就当没发生** —— `simple_websocket` 的
        `close()` 在连接已经断开时会抛 `ConnectionClosed`，而收摊这条路
        （判死、断开、下课前后的任意一条）本来就可能走到一条死连接上。"""
        from simple_websocket import ConnectionClosed

        with suppress(ConnectionClosed):
            self._socket.close(reason=int(code), message=str(reason or ""))

    def _call(self, method: str, *args, **kwargs):
        """调底层 socket，把「对端断开」翻成 `ChannelClosed`。翻译只此一处。

        局部 import：既有「厂商库只在用得到时加载」的意思，
        也让本模块在没有装 WebSocket 支持时仍能被导入（路由不会被访问到）。
        """
        from simple_websocket import ConnectionClosed

        from app.services.classroom.channel import ChannelClosed

        try:
            return getattr(self._socket, method)(*args, **kwargs)
        except ConnectionClosed as exc:
            raise ChannelClosed(str(exc)) from exc


# --- 内部 ---


def _int_arg(name: str, default: int) -> int:
    """取一个整数查询参数。给了但不合法要报 40001，而不是悄悄用默认值 ——
    「我明明传了 size=100，怎么还是 50 条」是比报错更难查的一类问题。
    （与 `app/api/courses.py` 的同名工具同一口径：两边各自小到不值得抽公共层，
    但必须给同一种答复。）"""
    raw = request.args.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ValidationError(f"{name} 必须是一个整数") from exc


def _int_of(value) -> int:
    """请求体里的整数。`responseMs` 这类**采样值**传坏了就用 0：它不影响判定，
    为它把一次答题挡回去不值得（判定要看的是 `option`）。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _entry_owner(session) -> str | None:
    """核销接入票据，返回它写的归属人（P3-F1）。**没带票返回 None。**

    `None` 与空串是两件事：空串是「票据写的这个人没有归属」（还没跑种子的
    库里就是这样），`None` 是「压根没带票」—— 后者由连接层用 `hello.token`
    认人，认不出来就 4403。

    **不拿请求头兜底**：`X-Owner-Id` 谁都能改，用它兜底等于把 P3-F1 要挡的
    那条路（伪造一个 id 接进别人的课堂）重新打开。
    """
    raw = str(request.args.get("ticket") or request.args.get("token") or "").strip()
    if not raw:
        return None
    owner_id = tickets.consume(
        raw, scope=session.id, fallback=sessions.FALLBACK_MANUAL
    )
    sessions.require_visible(session, owner_id)
    return owner_id


__all__ = ["bp"]
