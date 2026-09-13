"""课堂连接层：一条 WebSocket 连接 = 一个 `ClassroomChannel`（P3-3 / §4.2）。

运行时是「这条连接的语义层」，这一层是它的**传输与生命周期**。两者加起来
才等于 P2 里的一个 `RealtimeChannel`；分开是因为课堂多出两件事 ——
连接要长期活着（每 50ms 一拍地扫留档），而「谁还连着」这件事本身是业务
（在线数、并发上限、掉线清理）。

| 这一层做的 | 为什么只有它能做 |
|---|---|
| 每一拍 `runtime.tick()` → `take_pending()` → 逐条发 | 交付只有留档这一条路径（运行时模块 docstring 第 2 条）：在线投递与断线补发扫的是同一份数据 |
| `hello` 之前先认人（URL 票据，或 `hello.token`） | 越权要在**进课堂之前**挡住（P3-F1） |
| 心跳 `ping` 与判死 | 「对端还在不在」只有连接层有证据 |
| 掉线后对齐在线名单（`recorder.sync_presence`） | 谁掉线只有连接层知道（P3-B5：「不留幽灵在线」） |
| 单会话连接数上限 | 数的是**连接**，不是请求，也不是人（P3-F5） |

**为什么要能被单独测**：Flask 的测试客户端做不了 WebSocket 升级（P2 §4.2
的同一条限制）。所以这一层只认一个三方法的 `Transport` 协议，契约测试
（P3-B1）用一只假的浏览器驱动它；真路由那头只剩 `Server.accept()` 与转发。

**心跳用应用层的 `ping` 帧，不用 WebSocket 协议层的 ping。** 协议层的 ping
由浏览器网络栈自动回，前端一行代码都不用写 —— 听起来更好，但它回答不了
课堂要问的那个问题：**页面**还在不在。标签页被挂起（切后台、断点、笔记本
合盖）时协议层照样有来有回，而屏幕上那节课早就没人看了。
`ping`/`pong` 走我们自己的词（§4.2 的契约要点写着「心跳 ping/pong 每 20s；
60s 无响应则判定掉线」），前端必须答；答不上来就摘掉在线 —— 这一条
前端也解释得清（它能显示「你要掉线了」）。

`ping` 与 `error` 一样是**每连接私有帧**：不落库、不带 `seq`
（客户端拿最后一个 `seq` 去重连，而留档里没有的号会让它此后一直对不上账）。

**收摊是这个模块最容易写错的地方**，它要按顺序做四件事：
`runtime.close()`（发言队列、课堂里的人）→ 摘掉连接位 → 对齐在线名单 →
关 socket。中间任何一步失败都不能拦住后面的 —— 一条已经断掉的连接留在
登记表里，会让这堂课的名额永远少一个。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from flask import current_app

from app.common.errors import AppError
from app.common.logging import get_logger
from app.common.timeutil import utcnow_iso
from app.models import ClassroomSession
from app.services.classroom import recorder, sessions
from app.services.classroom.runtime import ClassroomRuntime, PeerGone
from app.services.voice import tickets

logger = get_logger("app.classroom.channel")

#: 一拍多久（秒）。与 P2 的语音通道同量级：两端各等一次，最坏 ~2×。
#: 它同时是事件端到端延迟的下限（P3-D1 要 P95 ≤ 500ms，这个数远在其下）。
POLL_SECONDS = 0.05

#: 一拍最多发几条第留档。留档积压时（断线很久再回来）分批发，`seq` 序不变。
FLUSH_LIMIT = 200

#: 下课收尾时最多再扫几轮留档。正常只有两三条（最后那个 beat、`speak_end`、
#: `state`），给到 10 轮是防「遇到一个不认识的持续产出」把连接卡死在这里。
DRAIN_ROUNDS = 10

#: 一拍里连着出错的次数上限。课堂不能卡在一句话上，但也不能一直卡着 ——
#: 到顶就收掉这条连接，让前端重连（重连那条路会重新建时间线）。
MAX_TICK_FAILURES = 5

#: 关闭码（WS 的 4000-4999 是私有区）。
CLOSE_NORMAL = 1000
#: 越权：握手之后才发现的（票据不是这堂课的、这堂课不该给他看）——P3-F1。
CLOSE_FORBIDDEN = 4403
#: 心跳判死（§4.2 / P3-B5）。
CLOSE_TIMEOUT = 4408
#: 这堂课的连接数到顶（P3-F5）。
CLOSE_TOO_MANY = 4429


class ChannelClosed(Exception):
    """浏览器那一端断了（关标签页、网线拔了、关连接帧）。"""


class Transport(Protocol):
    """通道面向的「另一头」：能收、能发、能被关掉。

    比 P2 的 `Transport` 多一个 `close(code, reason)`：课堂有几种**有理由的
    关闭**（4403 越权 / 4429 超员 / 4408 判死），而那句理由只有这一层说得出来。
    WS 路由用 `simple_websocket.Server` 实现它，测试用一只假的。
    """

    def receive(self, timeout: float) -> str | bytes | None:
        """收一条消息。到点没数据返回 None（**不抛异常**）。"""

    def send(self, data: str | bytes) -> None:
        """发一条消息。对端已断时抛 `ChannelClosed`。"""

    def close(self, code: int, reason: str) -> None:
        """按给定的关闭码收工。已经关过就当没发生（幂等）。"""


class ConnectionRegistry:
    """这台机器上还开着的课堂连接：`{会话 id: {连接 id: 用户 id}}`。

    课堂要回答两个问题 —— 「这堂课此刻还有谁连着」（P3-B5 的幽灵在线、
    P3-A12 的在线数）与「到没到上限」（P3-F5）—— 而库里的
    `session_participants` 两个都答不了：它是**人**的名单，而且写的是上一拍的
    结论，一个刚拔了网线的人在那里还是在线的。所以连接层自己记一份。

    `user_id` 可以是空串（没带票据进来的连接）。空串的连接算名额，但不进
    `alive()` —— 名单是用来对齐「人在不在」的，而它不知道那是谁。

    **存内存**：与票据、语音会话名额同一条限制（单进程）。多进程部署要换成
    共享存储；那时 `CLASSROOM_MAX_CONNECTIONS` 会先变成「每进程 50」，
    这条限制因此比其余几条更早暴露。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rooms: dict[str, dict[str, str]] = {}

    def attach(
        self, session_id: str, conn_id: str, user_id: str, *, limit: int = 0
    ) -> bool:
        """占一个连接位。满了返回 False（调用方据此以 4429 关掉）。

        已经在表里的连接重复占算成功 —— 「同一条连接又走了一遍 `run`」
        不是第二条连接（与 `voice/sessions.claim` 同一条口径）。
        """
        with self._lock:
            room = self._rooms.setdefault(str(session_id), {})
            if limit > 0 and conn_id not in room and len(room) >= limit:
                return False
            room[conn_id] = str(user_id or "")
            return True

    def detach(self, session_id: str, conn_id: str) -> None:
        """还连接位。没占过也当成功（收摊可能被走到两次）。"""
        with self._lock:
            room = self._rooms.get(str(session_id))
            if room is None:
                return
            room.pop(conn_id, None)
            if not room:
                self._rooms.pop(str(session_id), None)

    def alive(self, session_id: str) -> list[str]:
        """这堂课此刻连着的**人**（去掉空归属、不去重 —— 对齐名单只看成员）。"""
        with self._lock:
            return [user for user in self._rooms.get(str(session_id), {}).values() if user]

    def count(self, session_id: str) -> int:
        """这堂课此刻有**几条**连接（排障与测试用）。"""
        with self._lock:
            return len(self._rooms.get(str(session_id), {}))

    def clear(self) -> None:
        """清空（测试用：模块级状态不该跨用例残留）。"""
        with self._lock:
            self._rooms.clear()


#: 进程内的连接登记表。测试要传自己的那一份（见 `ClassroomChannel`）。
connections = ConnectionRegistry()


class ClassroomChannel:
    """一条课堂连接。`run()` 之前它什么都不知道，`hello` 之前它不知道**谁**。"""

    def __init__(
        self,
        session: ClassroomSession,
        *,
        owner_id: str | None = None,
        name: str = "",
        clock: Callable[[], float] = time.monotonic,
        registry: ConnectionRegistry | None = None,
        poll: float = POLL_SECONDS,
        heartbeat: float | None = None,
        timeout: float | None = None,
        max_connections: int | None = None,
    ) -> None:
        self.session = session
        #: 这条连接是为谁开的。`owner_id=None` 表示**还没认人**（URL 里没带票据，
        #: 由 `hello.token` 认，见 `_enter`）；空串是「票据写了这个人，只是这张票
        #: 没有归属」（还没跑种子的库里就是这样）。两者的区别只有一处要紧：
        #: 认人是按 `None` 判的，按空串判会让「没有归属」变成「认不出来」，
        #: 于是本地会话一连接就被自己的 4403 挡在门外。
        self._identified = owner_id is not None
        self.owner_id = str(owner_id or "")
        self._name = str(name or "")
        self._clock = clock
        self._registry = registry if registry is not None else connections
        self._conn_id = uuid.uuid4().hex
        config = current_app.config
        self._poll = float(poll)
        self._heartbeat = _config_number(config, "CLASSROOM_HEARTBEAT", 20.0, heartbeat)
        self._timeout = _config_number(config, "CLASSROOM_TIMEOUT", 60.0, timeout)
        self._max_connections = (
            sessions.max_connections() if max_connections is None else int(max_connections)
        )

        self._runtime: ClassroomRuntime | None = None
        self._transport: Transport | None = None
        self._entered = False
        self._claimed = False
        self._closed = False
        #: 最后一次收到上行（任何上行都算「还活着」，`pong` 只是最常见的那一种）
        self._last_seen = 0.0
        self._last_ping = 0.0
        self._failures = 0
        #: 最近一次给这条连接发出去的错误（路由与验收脚本要能回看）
        self.last_error = ""

    # --- 对外 ---

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def entered(self) -> bool:
        """`hello` 收下了没有。没收下就还没有运行时。"""
        return self._entered

    @property
    def runtime(self) -> ClassroomRuntime | None:
        return self._runtime

    def attach(self, transport: Transport) -> bool:
        """接上另一头，并占一个连接位。返回「接上了吗」。

        时间从**这一刻**起算：`_last_seen` 与 `_last_ping` 都落在这里，
        否则一条刚建好的连接会立刻被判死（它的两个时刻还是 0，而钟早就走远了）。

        拆出来是为了让测试能自己走 `step()`：`run()` 就是「attach 之后一直走」，
        而心跳与判死要验的正是「世界过去了多久」。
        """
        self._transport = transport
        now = self._clock()
        self._last_seen = now
        self._last_ping = now
        return self._claim()

    def run(self, transport: Transport) -> None:
        """轮到这条连接结束（对端断开、判死、下课，或内部出错）。

        **任何异常都在这里收口**：这是 WSGI 线程的最外层，让它冒出去只会变成
        一段与那条连接无关的堆栈，而连接本身还挂在登记表里。
        """
        if not self.attach(transport):
            return
        try:
            while self.step():
                pass
        except (ChannelClosed, PeerGone) as exc:
            logger.debug("课堂连接断开：session=%s %s", self.session.id, exc)
        except Exception:  # 底层 socket 抛什么都收在这儿
            logger.exception("课堂连接异常收尾：session=%s", self.session.id)
        finally:
            self.close(reason="transport_closed")

    def step(self) -> bool:
        """走一拍。`run()` 就是「一直走」，测试用它把时间捏在自己手里。

        顺序不是随手排的：**先判死再收包**，因为判死要发一条 `error` 再关连接，
        而收包之后判死会在「对端已经断了」的情况下多绕一圈（那一圈的
        `receive` 会直接抛 `ChannelClosed`，理由就变成了「断开」而不是「超时」）。
        """
        if self._closed:
            return False
        if self._expired():
            self._drop_for_timeout()
            return False
        self._advance()
        self._flush()
        self._maybe_ping()
        message = self._receive()
        if message is not None:
            self._last_seen = self._clock()
            self.handle(message)
        return self._keep_running()

    def handle(self, message: str | bytes | Mapping[str, Any]) -> None:
        """一条上行。**第一帧必须是 `hello`** —— 它同时是这个连接的入场券。

        在那之前这个连接不知道自己是「谁」，所以除了 `hello` 什么都做不了：
        早期的课堂协议里 `hello` 只用来定补发起点，于是「先进来再说」的
        连接可以随手报一个别人的 `pageNo`／举手／发言 —— 那些东西全都要
        一个身份才说得清是谁的（P3-F1）。
        """
        payload = message if isinstance(message, Mapping) else _parse(message)
        if payload is None:
            self._error("bad_message", "上行消息不是合法的 JSON 对象")
            return
        kind = str(payload.get("type") or "")
        if not self._entered:
            if kind != "hello":
                self._error("not_entered", "进课堂要先发一条 hello")
                return
            if not self._enter(payload):
                return
        if self._runtime is None:  # 已经收摊（判死、越权、下课）
            return
        self._runtime.handle(payload)

    def close(self, *, code: int = CLOSE_NORMAL, reason: str = "closed") -> None:
        """收摊。幂等 —— 判死、断开、下课三条路都会走到这里。"""
        if self._closed:
            return
        self._closed = True
        runtime, self._runtime = self._runtime, None
        if runtime is not None:
            try:
                runtime.close(reason=reason)
            except Exception:  # 收摊失败不该拦住后面的摘名单与关连接
                logger.exception("课堂运行时收摊失败：session=%s", self.session.id)
        self._registry.detach(self.session.id, self._conn_id)
        self._settle_presence()
        self._send_close(code, reason)
        logger.info(
            "课堂连接收摊：session=%s user=%s code=%s reason=%s",
            self.session.id,
            self.owner_id,
            code,
            reason,
        )

    # --- 入场 ---

    def _enter(self, payload: Mapping[str, Any]) -> bool:
        """认人 + 建运行时。判不过就 4403 关掉（P3-F1）。

        两条入口：URL 里带了票据的（路由已经核销并传下 `owner_id`）与只带
        `hello.token` 的（§4.2 第一帧的字段）。前者的错误在**握手之前**就说清了
        （HTTP 信封，浏览器连 101 都拿不到），后者只能握手之后再拒 ——
        4403 就是为这一条留的。
        """
        if not self._identified:
            token = str(payload.get("token") or "")
            try:
                owner = tickets.consume(
                    token, scope=self.session.id, fallback=sessions.FALLBACK_MANUAL
                )
                sessions.require_visible(self.session, owner)
            except AppError as exc:
                logger.warning(
                    "课堂接入被拒：session=%s code=%s %s", self.session.id, exc.code, exc.message
                )
                self._error(str(exc.code), exc.message, recoverable=False)
                self.close(code=CLOSE_FORBIDDEN, reason="forbidden")
                return False
            self._identified = True
            self.owner_id = owner
        self._name = self._name or sessions.name_of(self.owner_id)

        self._runtime = ClassroomRuntime(
            self.session,
            emit=self._private,
            clock=self._clock,
            user_id=self.owner_id,
            name=self._name,
        )
        self._entered = True
        return True

    def _private(self, data: str) -> None:
        """运行时发私有帧（`error`）的出口。

        对端没了就翻成 `PeerGone` 让它自己收尾 —— 与运行时的约定一致：
        一条已经断掉的连接不能被继续喂事件，而这件事只有出口看得见。
        """
        try:
            self._send(data)
        except Exception as exc:
            raise PeerGone(str(exc)) from exc

    # --- 一拍里的四件事 ---

    def _advance(self) -> None:
        """推进一次运行时。**这是唯一把排队发言放出来的地方**（单写者）。

        出错不抛穿：课堂不能卡在一句话上。但也不能一直卡着 —— 连着
        `MAX_TICK_FAILURES` 拍都出错就收掉这条连接，让前端重连
        （重连会重建时间线，比挂在一堂推不动的课上强）。
        """
        runtime = self._runtime
        if runtime is None or not runtime.alive:
            return
        try:
            runtime.tick()
        except Exception:
            self._failures += 1
            logger.exception(
                "课堂推进失败（第 %s 次）：session=%s", self._failures, self.session.id
            )
            if self._failures >= MAX_TICK_FAILURES:
                self._error("internal", "课堂推进不下去了，请刷新页面重新进入", recoverable=False)
                self.close(code=CLOSE_TIMEOUT, reason="tick_failed")
            return
        self._failures = 0

    def _flush(self) -> int:
        """把留档里这条连接还没收到的事件发出去（交付的唯一路径）。"""
        runtime = self._runtime
        if runtime is None:
            return 0
        events = runtime.take_pending(limit=FLUSH_LIMIT)
        for event in events:
            self._send_json(event)
        return len(events)

    def _maybe_ping(self) -> None:
        """到点打一次心跳。`pong`（或任何上行）回来就不会被判死。"""
        if self._heartbeat <= 0:
            return
        now = self._clock()
        if now - self._last_ping < self._heartbeat:
            return
        self._last_ping = now
        self._send_json({"type": "ping", "ts": utcnow_iso()})

    def _keep_running(self) -> bool:
        """下课了没有。下课要先把话说完再关 —— 顺序反了，前端最后看到的
        就是「连接断了」，而看不到那条 `state.status=ended`。"""
        runtime = self._runtime
        if runtime is None or not runtime.finished:
            return True
        for _ in range(DRAIN_ROUNDS):
            if self._flush() < FLUSH_LIMIT:
                break
        logger.info("课堂已结束，连接收工：session=%s user=%s", self.session.id, self.owner_id)
        self.close(reason="ended")
        return False

    def _receive(self) -> str | bytes | None:
        assert self._transport is not None  # run() 与 step() 的先后由 run 保证
        return self._transport.receive(timeout=self._poll)

    # --- 判死与收尾 ---

    def _expired(self) -> bool:
        """超时了没有（§4.2：60s 没动静就摘掉）。`<=0` 表示不判。"""
        if self._timeout <= 0 or self._transport is None:
            return False
        return (self._clock() - self._last_seen) > self._timeout

    def _drop_for_timeout(self) -> None:
        logger.info(
            "课堂连接心跳超时（%.0fs 没有上行）：session=%s user=%s",
            self._timeout,
            self.session.id,
            self.owner_id,
        )
        self._error("timeout", "连接已超时，请刷新页面重新进入课堂", recoverable=False)
        self.close(code=CLOSE_TIMEOUT, reason="timeout")

    def _claim(self) -> bool:
        """占一个连接位（P3-F5）。满了发一条 `error` 再以 4429 关掉。

        放在这里而不是路由里：名额只能在**已经握手之后**判得准 ——
        在那之前连接还没进登记表，而两条同时到达的连接需要一个原子的是非。
        """
        if self._registry.attach(
            self.session.id, self._conn_id, self.owner_id, limit=self._max_connections
        ):
            self._claimed = True
            return True
        logger.warning(
            "课堂连接数到顶（%s）：session=%s user=%s",
            self._max_connections,
            self.session.id,
            self.owner_id,
        )
        self._error(
            "too_many_connections",
            f"这堂课同时接入的人太多了（上限 {self._max_connections}），请稍后再试",
        )
        self.close(code=CLOSE_TOO_MANY, reason="too_many_connections")
        return False

    def _settle_presence(self) -> None:
        """把在线名单对齐到「还开着的连接」（P3-A12 / P3-B5）。

        `runtime.close()` 已经把这个人标成离线了，但「在线」数的是**人**：
        同一个人的另一个标签页还开着的时候，他还在这堂课里 —— 那一步是
        `runtime` 的既有语义（单条连接的收尾就是「我走了」），把它改掉会让
        「关掉唯一的那个标签页」也摘不掉人。所以纠正放在连接层：它还知道
        这堂课剩几条连接。
        """
        try:
            alive = self._registry.alive(self.session.id)
            if self.owner_id and self.owner_id in alive:
                sessions.join(self.session, self.owner_id, name=self._name)
                recorder.publish(
                    self.session, "presence", recorder.presence(self.session.id)
                )
                return
            if recorder.sync_presence(self.session.id, alive):
                recorder.publish(
                    self.session, "presence", recorder.presence(self.session.id)
                )
        except Exception:  # 对齐失败不该拦住关连接
            logger.exception("课堂：对齐在线名单失败 session=%s", self.session.id)

    def _send_close(self, code: int, reason: str) -> None:
        transport = self._transport
        if transport is None:
            return
        try:
            transport.close(code, reason)
        except Exception:
            logger.debug("课堂：关连接时对端已经不在了 session=%s", self.session.id)

    # --- 发帧 ---

    def _send_json(self, payload: Mapping[str, Any]) -> None:
        self._send(json.dumps(payload, ensure_ascii=False))

    def _send(self, data: str) -> None:
        assert self._transport is not None
        self._transport.send(data)

    def _error(self, code: str, message: str, *, recoverable: bool = True) -> None:
        """一条**只发给这条连接**的 `error` 帧（不落库、不带 `seq`）。

        发不出去就算了：调用它的三条路（未知上行、判死、超员）接下来都要
        收摊，而对端已经走掉正是最常见的那一种。
        """
        self.last_error = message
        logger.warning("课堂连接错误 code=%s msg=%s", code, message)
        try:
            self._send_json(
                {"type": "error", "code": code, "message": message, "recoverable": recoverable}
            )
        except Exception:
            logger.debug("课堂：error 帧没发出去（对端已断）")


def _config_number(config: Any, key: str, default: float, override: float | None) -> float:
    """取一个时长配置。显式传了就用显式的（测试要能把它调小）。"""
    if override is not None:
        return float(override)
    value = config.get(key)
    return float(value) if value not in (None, "") else default


def _parse(raw: Any) -> Mapping[str, Any] | None:
    if not isinstance(raw, (str, bytes, bytearray)):
        return None
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, Mapping) else None


__all__ = [
    "CLOSE_FORBIDDEN",
    "CLOSE_NORMAL",
    "CLOSE_TIMEOUT",
    "CLOSE_TOO_MANY",
    "FLUSH_LIMIT",
    "POLL_SECONDS",
    "ChannelClosed",
    "ClassroomChannel",
    "ConnectionRegistry",
    "Transport",
    "connections",
]
