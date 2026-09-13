#!/usr/bin/env python
"""P3 A/B/C/F/G 类验收（P3-G2）：用无头 WS 客户端把一堂课从头开到下课。

一条命令跑完，**不联网、不读 `.env`、不碰 `backend/data/`**：三个临时后端
共用一份临时 SQLite 与一个临时音频目录，跑完连库带日志一起删。

```bash
cd 项目源码
python scripts/accept_p3.py
```

| 实例 | 端口 | 配置 | 验的是 |
|------|------|------|--------|
| 主实例 | :5083 | 离线替身、推送开、单用户会话上限 12 | A/B/C/D/E/F 的绝大多数 |
| 心跳实例 | :5081 | `HEARTBEAT=1` / `TIMEOUT=4` / `MAX_CONNECTIONS=2` | B5 判死清理、F5 连接数上限 |
| 关推送实例 | :5082 | `CLASSROOM_WS=false` | G3 退到手动翻页、F5 单用户会话上限 |

**三个实例为什么是这三个配置**（每一处都是为了让某一条验得到，而不是顺手改的）：

- **心跳实例把 20s/60s 拧成 1s/4s**：B5 验的是「判死之后清理掉幽灵在线」这条
  **代码路径**，不是那个常数 —— 常数是配置项（§4.2），默认值另有契约测试钉着
  (`test_a_client_that_never_answers_is_dropped_from_the_room`)。在一堂要跑几分钟
  的验收里真等 60 秒，只会让人不愿意跑它。连接数上限同理：默认 50 要开 51 条连接
  才验得到，这里设 2。
- **主实例把单用户会话上限抬到 12**：C5 要一次开 5 场课，另外几组检查也会各自
  开一两场（都结束了才放手）。默认值 2 的那条**不改也验得到** —— 它在关推送的
  实例上验（F5），那里配额是默认的。
- **关推送实例还兼着 F5 的会话配额**：`CLASSROOM_WS=false` 时开课走的是
  `POST /sessions` 这条 HTTP 路，配额本来就与推送无关；而它上面的课是 idle 的，
  不会跟别人的会话抢名额（配额按未结束的会话数算）。

## 脚本在演前端

`ClassClient` 就是「一个浏览器标签页」：握手、回心跳、按 `speak` 报 `beat_done`、
遇 `quiz` 提交作答、该翻页时发 `seek`、该举手时发 `hand`。它比 P2 的 `WsClient`
多知道的只有两件课堂协议的事 —— **应用层 `ping` 必须回 `pong`**（不回就等于
页面不在了，§4.2），以及**事件按 `seq` 收**。

一堂课的长度不由墙钟决定，由**事件**决定：`beat_done` 一报，时间线就往前走一格，
所以整堂课在几十秒里走完（真实课堂的十几分钟是「等音频播完」等出来的，而
脚本不等音频）。**例外是第一句讲稿**：它自然等到 `speak_end`，用来验
`_expire_speaking` 那条计时收尾的路真的会收尾。

## 报的与不报的

跑不到的（要真上游、要人耳、要 45 分钟压测、要浏览器渲染）一律如实记 **跳过**，
并把**离线侧验到的那一半**写在同一行里 —— 假装验过比不验更糟。委托给 pytest 的
条目在最后逐条记账（`-rA`，通过/没通过都点名）。

## 与 P2 脚本的关系

骨架（`Report` / `api` / 手写 `WsClient` / `child_env` / 三个实例 / `_guard`）
照搬 `accept_p2.py`：两条命令的读法、输出形状、失败时的现场保留方式应当一致，
读的人不必学第二套。**没有改动任何被测代码** —— 脚本红了就改脚本或改实现，
不改「怎么算通过」。
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import itertools
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, ClassVar, Iterable, Mapping, Sequence

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """去掉 ANSI 颜色码：报错详情里混着转义序列没法读。"""
    return _ANSI.sub("", text or "")


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

#: 三个临时后端。刻意不用 5000：那是 `make dev` 的端口，连的是你的库。
#: 也不挨着 P0/P1/P2（5094~5096）：同时跑两条验收时互不打扰。
MAIN_PORT = 5083
PULSE_PORT = 5081
NOPUSH_PORT = 5082

#: 由 main() 赋值的接口前缀（脚本要等临时后端起来才知道自己该调谁）。
API = ""

#: 预置示例课（P1 的种子）。G2 要的是「不依赖真实 LLM，用 Mock 发言」，
#: 所以这堂课必须是**库里现成的**，而不是当场生成一门 —— 当场生成要跑六个
#: 步骤、要模型、要几分钟，而那件事 P1 的验收已经验过了。
COURSE_ID = "course_demo_ml"
COURSE_TITLE = "机器学习入门"
PAGE_COUNT = 12
QUIZ_PAGES = (5, 8, 11)
BOARD_PAGE = 7
#: 章末讨论挂在每章最后一页，而每章最后一页恰好是那三道题所在的页。
DISCUSSION_PAGES = QUIZ_PAGES

#: 一个不在这堂课里、也不拥有这门课的人（P3-F4 的越权口径）。
OUTSIDER = "outsider_9f3a"

#: 一堂课最多跑多久（墙钟）。超了说明有东西卡住了，如实报失败而不是一直等。
CLASS_DEADLINE = 300.0

#: 离线替身的音色与凭据口径，与 `accept_p2.py` 逐字一致（见那边的长注释：
#: 只设 `EDUAGENTX_DISABLE_DOTENV` 拦不住 Flask CLI 自己读 `.env`）。
OFFLINE_ENV: dict[str, str] = {
    "EDUAGENTX_DISABLE_DOTENV": "1",
    "FLASK_SKIP_DOTENV": "1",
    "LLM_PROVIDER": "mock",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "",
    "VOLC_TTS_API_KEY": "",
    "VOLC_TTS_ENDPOINT": "",
    "VOLC_TTS_RESOURCE_ID": "",
    "VOLC_ASR_API_KEY": "",
    "VOLC_ASR_ENDPOINT": "",
    "VOLC_ASR_RESOURCE_ID": "",
    "VOLC_REALTIME_API_KEY": "",
    "VOLC_REALTIME_ENDPOINT": "",
    "VOLC_REALTIME_MODEL": "",
    "VOLC_TTS_VOICE_TEACHER": "mock-voice-teacher",
    "VOLC_TTS_VOICE_HISTORY": "mock-voice-humanities",
}

#: 主实例：离线替身照常出声（讲稿要预合成，答疑要当场合成 —— P3-A5 的
#: 「教师语音回答」在关掉语音的实例上只剩半条），但配额放开到 12（见模块 docstring）。
MAIN_ENV: dict[str, str] = {**OFFLINE_ENV, "CLASSROOM_MAX_SESSIONS_PER_USER": "12"}

#: 心跳实例：把 20s/60s 拧成 1s/4s、连接上限拧成 2。
PULSE_ENV: dict[str, str] = {
    **OFFLINE_ENV,
    "CLASSROOM_HEARTBEAT": "1",
    "CLASSROOM_TIMEOUT": "4",
    "CLASSROOM_MAX_CONNECTIONS": "2",
}

#: 关推送实例：§4.2 的最后一条（P3-G3）。会话配额留默认值 2。
NOPUSH_ENV: dict[str, str] = {**OFFLINE_ENV, "CLASSROOM_WS": "false"}

#: 课堂状态机（§2.1）。**从实现里读**而不是在脚本里再抄一份：抄一份的那天
#: 起，这处就成了「验收以为的状态机」，而它悄悄与实现分家了。
TRANSITIONS: dict[str, list[str]] = {}

#: `elapsedMs` 的估算基准（`_speak_ms`）：1200ms + 190ms/字，夹在 1.5s~20s。
SPEAK_BASE_MS = 1200.0
SPEAK_PER_CHAR_MS = 190.0
SPEAK_MIN_MS = 1500.0
SPEAK_MAX_MS = 20000.0

#: 出戏表述（P3-E4 的脚本那一半）。
OUT_OF_CHARACTER = re.compile(
    r"作为一个?AI|作为人工智能|我是(一个)?(语言)?模型|语言模型|大模型|AI ?助手|"
    r"人工智能助手|我无法(回答|提供)|抱歉[，,]?我不能|系统提示|提示词",
    re.I,
)

#: 整课预合成的上限（P2 的同一件事，给同一份余量）。
NARRATE_TIMEOUT = 180.0


def _speak_ms(text: str) -> float:
    """产品那把握时尺（`runtime._speak_ms` 的字数分支）：1200 + 190×字数，夹在 1.5s~20s。

    讲稿有预合成音频时产品用的是音频真时长（脚本拿不到那个真值 —— 它在音频
    清单里），这里按同一个公式估。**估出来偏长**，用作「连着讲了多久」的上界
    正合适：这条要拦的是「讲太久没人说话」，宁严不宽。
    """
    estimate = SPEAK_BASE_MS + SPEAK_PER_CHAR_MS * len(text)
    return max(SPEAK_MIN_MS, min(SPEAK_MAX_MS, estimate))


# --------------------------------------------------------------------------
# 委托给 pytest 的条目（脚本跑不到或跑起来不值当的）
# --------------------------------------------------------------------------

#: 由离线用例**判定**的条目：`(编号, 标题, 节点)`。脚本负责逐条记账。
DELEGATED: list[tuple[str, str, list[str]]] = [
    (
        "P3-B1",
        "WS 契约测试覆盖 §4.2 全部上下行（含异常分支）",
        ["tests/contract/test_p3_classroom_ws.py"],
    ),
    (
        # 这条以前只有 G3 顺带提一句「未开讲时举手仍是 40901」，而 `idle` 的课
        # 答题也应当是 40901 —— 整个课堂 HTTP 契约文件（21 条）本来就该在
        # 验收里跑一遍，它是「接口没被改坏」的第一道网。
        "P3-B4",
        "课堂 HTTP 接口契约（含 P3-B4：未开始的课答题 / 举手 → 40901）",
        ["tests/contract/test_p3_classroom_api.py"],
    ),
    (
        "P3-C2",
        "session_events 留档完整、有上限、超限不影响记录页",
        [
            "tests/unit/test_classroom_recorder.py::test_events_are_pruned_when_they_hit_the_limit",
            "tests/unit/test_classroom_recorder.py::test_pruning_does_not_touch_messages",
            "tests/contract/test_p3_classroom_api.py::test_the_record_survives_the_event_log_being_pruned",
        ],
    ),
    (
        "P3-C4",
        "删除课程级联删除其 sessions/messages/strokes，无孤儿",
        [
            "tests/unit/test_classroom_models.py::test_deleting_a_course_takes_the_whole_classroom_with_it",
            "tests/unit/test_classroom_models.py::test_deleting_one_session_leaves_the_other_alone",
        ],
    ),
]

#: 离线跑不到、但离线侧有替代证据的条目：`(编号, 标题, 节点, 为什么跑不到)`。
PROXIED: list[tuple[str, str, list[str], str]] = [
    (
        "P3-D2",
        "单场课堂 ≥ 20 个并发连接，20 连接下事件延迟 P95 ≤ 800ms",
        [
            "tests/contract/test_p3_classroom_ws.py::test_a_connection_over_the_limit_is_refused_with_4429",
            "tests/contract/test_p3_classroom_ws.py::test_the_slot_is_released_when_the_connection_ends",
        ],
        "要 20 条真连接与真网络；离线侧验到的是「连接上限与名额释放真的生效」"
        "（脚本里另有三条连接同收一条事件的广播证据）",
    ),
    (
        "P3-D4",
        "连续运行 45 分钟，后端内存增长 ≤ 100MB、前端 ≤ 80MB",
        [
            "tests/unit/test_classroom_recorder.py::test_events_are_pruned_when_they_hit_the_limit",
        ],
        "要 45 分钟的真跑与内存采样；离线侧验到的是留档有上限（内存不会随课堂长度无界增长）",
    ),
    (
        "P3-E1",
        "同学发言相关性 ≥ 4 分（抽 10 条人工评分）",
        ["tests/unit/test_classroom_fixture.py::test_the_interjection_mentions_the_page"],
        "要人读；离线侧验到的是「插话提到了当前页」（脚本按页标题关键词另算了一遍）",
    ),
    (
        "P3-E2",
        "同学发言不重复：任意两条相似度 ≤ 0.8",
        [
            "tests/unit/test_classroom_fixture.py::test_two_pages_do_not_say_the_same_thing",
            "tests/unit/test_classroom_interjection.py::test_duplicate_against_recent_student_turns_is_dropped",
        ],
        "脚本对插话与首轮发言算过相似度并通过；被跳过的是「整堂课所有同学发言两两相比」——"
        "离线替身每个角色只有三句句式库，连说十几轮必然撞句，那是桩的局限而不是课堂的缺陷",
    ),
    (
        "P3-E3",
        "教师答问准确性 ≥ 4 分（抽 5 个问题人工评分）",
        ["tests/unit/test_classroom_fixture.py::test_the_answer_picks_up_the_question"],
        "要人读；离线侧验到的是「答案接得住问题」（脚本另验了答疑闭环本身）",
    ),
    (
        "P3-D5",
        "板书 200 笔画的页面切换渲染 ≤ 200ms",
        [],
        "要浏览器渲染；离线侧只验到笔画数与顺序（板书回放本身是 P3-A8）",
    ),
]


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


class Report:
    """通过清单。最后要能一眼看出「哪几条没过」。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def _add(self, aid: str, title: str, status: str, detail: str) -> None:
        detail = plain(detail)
        self.rows.append((aid, title, status, detail))
        label = {"PASS": "通过", "FAIL": "不通过", "SKIP": "跳过"}[status]
        print(f"  [{label}] {aid} {title}")
        if detail:
            for line in detail.splitlines():
                print(f"         {line}")

    def ok(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "PASS", detail)

    def fail(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "FAIL", detail)

    def skip(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "SKIP", detail)

    def verdict(self, aid: str, title: str, problems: Sequence[str], detail: str = "") -> None:
        """一组断言：`problems` 非空即不通过，内容原样打印。"""
        if problems:
            self.fail(aid, title, "；".join(problems))
        else:
            self.ok(aid, title, detail)

    def summary(self) -> int:
        passed = sum(1 for row in self.rows if row[2] == "PASS")
        failed = [r for r in self.rows if r[2] == "FAIL"]
        skipped = [r for r in self.rows if r[2] == "SKIP"]
        print()
        print("=" * 68)
        print(f"P3 验收：通过 {passed} / 不通过 {len(failed)} / 跳过 {len(skipped)}")
        for aid, title, _, detail in failed:
            print(f"  ✗ {aid} {title}")
            if detail:
                print(f"      {detail.splitlines()[0]}")
        for aid, title, _, detail in skipped:
            print(f"  - {aid} {title}（{detail.splitlines()[0] if detail else '未说明'}）")
        print("=" * 68)
        return 1 if failed else 0


# --------------------------------------------------------------------------
# HTTP（只用标准库：脚本要能被系统 python 直接跑起来）
# --------------------------------------------------------------------------


def api(
    method: str,
    path: str,
    body: Any = None,
    *,
    base: str = "",
    owner: str = "",
    timeout: float = 30.0,
) -> tuple[int, dict]:
    """调后端接口，返回 (HTTP 状态, 信封)。业务错误也在信封里，不抛异常。

    `base` 不传就打到主实例；心跳与关推送那两条路显式传自己的前缀 ——
    它们验的是**同一条接口在另一种部署下的答复**，用错实例就什么都验不到。
    """
    data = None
    headers = {"X-Request-Id": "accept-p3"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if owner:
        headers["X-Owner-Id"] = owner
    req = urllib.request.Request(f"{base or API}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, {"raw": text[:400]}
    except Exception as exc:  # 连不上 / 超时
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _data(status: int, envelope: Mapping[str, Any]) -> Any:
    """成功信封里的 `data`。

    与 P2 的同名工具差一条：这里收 2xx 而不只是 200 —— 开课是 **201**
    （`POST /classroom/sessions`），只认 200 的话，验收会把一次成功的开课
    读成「没拿到 sessionId」。
    """
    if 200 <= int(status) < 300 and envelope.get("code") == 0:
        return envelope.get("data")
    return None


def brief(payload: Any, limit: int = 300) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def is_up(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False


def wait_http(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


# --------------------------------------------------------------------------
# WebSocket 客户端（标准库手写）
# --------------------------------------------------------------------------

#: 上行帧**必须**加掩码（RFC 6455 §5.3）：服务端收到没掩码的客户端帧要断开。
_WS_TEXT, _WS_BINARY, _WS_CLOSE, _WS_PING, _WS_PONG = 0x1, 0x2, 0x8, 0x9, 0xA


class WsClosed(Exception):
    """对端走了。"""


class WsClient:
    """够用的 WebSocket 客户端：握手 + 掩码发送 + 分帧接收（与 accept_p2 同一份）。

    为什么手写而不装一个库：这份脚本要能被系统 python 直接跑起来，而为了验收
    再往 requirements 里加一个**只在这里用到**的依赖，是在给部署添一件要维护
    的东西。用到的协议只有 RFC 6455 的一小半（文本/二进制/关闭/心跳）。
    """

    def __init__(self, sock: socket.socket, leftover: bytes = b"") -> None:
        self.sock = sock
        self.buf = bytearray(leftover)
        self.closed = False

    def send_text(self, payload: Mapping[str, Any]) -> None:
        self._frame(_WS_TEXT, json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"))

    def _frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        head = bytearray([0x80 | opcode])
        size = len(payload)
        if size < 126:
            head.append(0x80 | size)
        elif size < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", size)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", size)
        head += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(head) + masked)

    def _read(self, size: int, deadline: float) -> bytes:
        while len(self.buf) < size:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("等一帧超时")
            self.sock.settimeout(min(remaining, 1.0))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                self.closed = True
                raise WsClosed("对端关闭了连接")
            self.buf += chunk
        out = bytes(self.buf[:size])
        del self.buf[:size]
        return out

    def recv(self, timeout: float) -> tuple[str, Any]:
        """收一帧，返回 `("text"|"binary"|"close", 内容)`。协议层心跳就地回掉。"""
        deadline = time.time() + timeout
        while True:
            head = self._read(2, deadline)
            opcode = head[0] & 0x0F
            masked = bool(head[1] & 0x80)
            size = head[1] & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2, deadline))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8, deadline))[0]
            mask = self._read(4, deadline) if masked else b""
            payload = self._read(size, deadline) if size else b""
            if masked:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

            if opcode == _WS_PING:
                self._frame(_WS_PONG, payload)  # 不回会被底层掐断
                continue
            if opcode == _WS_PONG:
                continue
            if opcode == _WS_CLOSE:
                self.closed = True
                return "close", payload
            return ("text" if opcode == _WS_TEXT else "binary"), payload

    def close(self) -> None:
        with contextlib.suppress(OSError):  # 已经关了
            self.sock.close()


def ws_connect(
    port: int, path: str, *, host: str = "127.0.0.1", timeout: float = 10.0
) -> tuple[WsClient | None, str, bytes]:
    """一次 WebSocket 握手。返回 `(客户端, 状态行, 响应体)`。

    **状态行不是 101 时 `client` 为 None** —— 那正是 P3-F1/G3 要看的：
    票据不对、推送关着时，服务端必须在**升级之前**拒绝，客户端拿到的是一个
    普通的 HTTP 响应（连 101 都见不到）。响应体也读回来，所以「拒绝时带没带
    `fallback`」在验收这一层也是能直接看的。
    """
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout)
    # 请求行只能是 ASCII：路径里出现了非 ASCII（F1 拿一个中文的课号去试）时
    # `encode("ascii")` 会当场炸掉，整组检查跟着一起断。按 RFC 3986 做百分号
    # 编码 —— 真浏览器也是这么发的，服务端解码回来还是那个课号。
    target = urllib.parse.quote(path, safe="/?=&#%!$'()*+,;:@-._~")
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))

    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0] if lines else ""

    if " 101" not in status:
        # 失败响应有 body（那是一封普通的错误信封），按 Content-Length 读完
        length = 0
        for line in lines[1:]:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip() or 0)
        while len(rest) < length:
            chunk = sock.recv(65536)
            if not chunk:
                break
            rest += chunk
        sock.close()
        return None, status, rest

    return WsClient(sock, rest), status, b""


#: 每连接私有帧（§4.2）：不带 `seq`、不落库、只发给这条连接。
PRIVATE_FRAMES = ("ping", "error")


class ClassClient:
    """无头课堂里的一个「浏览器标签页」。

    比 `WsClient` 多知道的只有两件课堂协议的事：

    1. **应用层的 `ping` 要回 `pong`**（不回就等于页面不在了，服务端会判死）；
    2. **事件按 `seq` 收**：`events` 里只放落档事件（带 `seq`），私有的
       `ping` / `error` 另放 `private` —— 混在一起，B2/B3 那几条断言会拿
       私有帧去比 `seq`，然后得出「服务端漏发了一个号」这种莫名其妙的结论。
    """

    #: 这一趟建过的全部假浏览器（按建出来的顺序）。见 `__init__` 与 `_dump_events`。
    ALL: ClassVar[list[ClassClient]] = []

    def __init__(self, sock: WsClient, label: str, *, pong: bool = True) -> None:
        self.ws = sock
        self.label = label
        #: 这一趟建过的**每一只**假浏览器。主线那堂课之外，A12/A13/F 那几条
        #: 各开各的临时连接 —— 跑砸的时候想看的往往正是它们收到了什么，
        #: 所以都登记下来，`_dump_events` 收尾时一起写进现场。
        ClassClient.ALL.append(self)
        #: 回不回心跳。B5 要造一个「页面卡死了」的客户端 —— 它还连在线上，
        #: 但一个上行都不发 —— 那时把这条关掉，同时**照常读**（要看得见 4408）。
        self.pong = pong
        self.events: list[dict] = []
        self.private: list[dict] = []
        self.close_code: int | None = None
        self.close_reason = ""
        self.garbage: list[str] = []
        #: 上行→下一条下行的延迟样本（P3-D1）。只统计业务上行，不统计 pong。
        self.latencies: list[float] = []
        #: 发过协议里没有的上行没有（P3-B3 的向前兼容）
        self.poked_unknown = False
        self._awaiting: float = 0.0
        self._pending_latency = False

    # --- 收 ---

    def pump(self, seconds: float) -> None:
        """收 `seconds` 秒的帧（或直到对端关掉）。"""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.close_code is not None:
                return
            try:
                kind, payload = self.ws.recv(max(0.05, deadline - time.time()))
            except (TimeoutError, WsClosed, OSError):
                return
            self._take(kind, payload)

    def _take(self, kind: str, payload: Any) -> None:
        if kind == "close":
            self.close_code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 0
            self.close_reason = payload[2:].decode("utf-8", "replace") if len(payload) > 2 else ""
            return
        if kind != "text":
            self.garbage.append("<binary>")
            return
        try:
            parsed = json.loads(payload)
        except ValueError:
            self.garbage.append(str(payload)[:80])
            return
        if not isinstance(parsed, dict):
            self.garbage.append(str(payload)[:80])
            return
        name = str(parsed.get("type") or "")
        if name == "ping":
            self.private.append(parsed)
            if self.pong:
                self.send({"type": "pong"}, mark=False)
            return
        if name == "error":
            self.private.append(parsed)
        else:
            self.events.append(parsed)
        self._mark_latency()

    def _mark_latency(self) -> None:
        """记一条「上行发出 → 这条下行到达」的样本（P3-D1）。"""
        if self._pending_latency:
            self.latencies.append(time.monotonic() - self._awaiting)
            self._pending_latency = False

    # --- 发 ---

    def send(self, payload: Mapping[str, Any], *, mark: bool = True) -> None:
        if mark:
            self._awaiting = time.monotonic()
            self._pending_latency = True
        self.ws.send_text(payload)

    def close(self) -> None:
        self.ws.close()

    # --- 读 ---

    def seqs(self) -> list[int]:
        return [int(event.get("seq") or 0) for event in self.events]

    def messages_by_seq(self) -> dict[int, dict]:
        """课堂上的消息事件，按 `seq` 排（P3-C1：库里那几条就是这几条）。"""
        return {
            int(event.get("seq") or 0): event
            for event in self.events
            if event.get("type") == "message" and event.get("msg")
        }

    def poke_unknown(self) -> None:
        """发一条协议里没有的上行（P3-B3）：课堂不该因此出错，也不该有回音。"""
        self.send({"type": "board_wipe", "pageNo": 1}, mark=False)
        self.poked_unknown = True

    def of(self, *types: str) -> list[dict]:
        wanted = set(types)
        return [event for event in self.events if event.get("type") in wanted]

    def last(self, type_name: str) -> dict | None:
        found = self.of(type_name)
        return found[-1] if found else None

    def errors(self, code: str = "") -> list[dict]:
        found = [frame for frame in self.private if frame.get("type") == "error"]
        return [frame for frame in found if str(frame.get("code")) == code] if code else found

    @property
    def dead(self) -> bool:
        return self.close_code is not None or self.ws.closed

    def wait(self, types: str | Sequence[str], seconds: float) -> dict | None:
        """等到某类事件出现（或超时）。返回那一条，没有就 None。

        **手上已经有就不再等**（返回最后一条）—— 用来等「入场那几条到齐」。
        要验「我刚发的这条上行生效了」得用 `wait_new`：那件事问的是
        「有没有**新**的」，而手上那条旧的会让这里立刻返回，看着像没生效。
        """
        wanted = {types} if isinstance(types, str) else set(types)
        found = [event for event in self.events if event.get("type") in wanted]
        if found:
            return found[-1]
        deadline = time.time() + seconds
        while time.time() < deadline and not self.dead:
            self.pump(0.1)
            found = [event for event in self.events if event.get("type") in wanted]
            if found:
                return found[-1]
        return None

    def wait_new(self, type_name: str, after_seq: int, seconds: float) -> dict | None:
        """等到一条**比 `after_seq` 新**的某类事件（P3-A13）。

        `seq` 是服务端给的单调号，所以「比它新」＝「这条上行之后才发的」。
        """
        deadline = time.time() + seconds
        while True:
            for event in reversed(self.events):
                if event.get("type") == type_name and int(event.get("seq") or 0) > after_seq:
                    return event
            if time.time() >= deadline or self.dead:
                return None
            self.pump(0.1)


# --------------------------------------------------------------------------
# 子进程
# --------------------------------------------------------------------------


def venv_python() -> Path:
    for rel in ("Scripts/python.exe", "bin/python"):
        candidate = BACKEND / ".venv" / rel
        if candidate.exists():
            return candidate
    sys.exit("找不到虚拟环境。先建：python -m venv backend/.venv 然后 pip install -r backend/requirements.txt")


def npx() -> str:
    return shutil.which("npx") or shutil.which("npx.cmd") or "npx"


def child_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """子进程的环境（与 accept_p2 同一份，含那两条编码与 `.env` 的闸门）。"""
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "FLASK_SKIP_DOTENV": "1",
        "EDUAGENTX_DISABLE_DOTENV": "1",
        **(env or {}),
    }


def start(process_args: list[str], cwd: Path, log_path: Path, env: dict[str, str] | None = None):
    log = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        process_args, cwd=str(cwd), env=child_env(env),
        stdout=log, stderr=subprocess.STDOUT,
    )


def stop(proc) -> None:
    """停掉我们启动的服务（含它的子进程；Windows 上 terminate 杀不干净）。"""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_python(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """在 backend 目录下用 venv python 跑一段代码（读临时库、取状态机都用它）。"""
    return subprocess.run(
        [str(venv_python()), "-c", code],
        cwd=str(BACKEND),
        env=child_env(env),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_pytest(*args: str) -> subprocess.CompletedProcess:
    """跑一趟 pytest。**这里不能再加 `-q`**：`pyproject.toml` 的 addopts 里已经有一个了，
    两个叠起来是 `-qq`，而 `-qq` 的 pytest 会把最后那句「N passed in x.xxs」整个省掉 ——
    于是详情里只剩一串进度点（`. ` ），等于没说。要更安静就改 addopts，别在这儿加。
    """
    return subprocess.run(
        [str(venv_python()), "-m", "pytest", *args],
        cwd=str(BACKEND),
        env=child_env(),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _pytest_tail(result: subprocess.CompletedProcess, lines: int = 12) -> str:
    """pytest 输出里最后几行才有「几个通过几个失败」。"""
    output = plain((result.stdout or "") + (result.stderr or ""))
    return "\n".join(line for line in output.splitlines()[-lines:] if line.strip())


def _pytest_summary(result: subprocess.CompletedProcess) -> str:
    """只要那一句「73 passed in 12.34s」。

    `_pytest_tail` 取的是**最后两行**，而 `-q` 的末尾常常是进度点或进度条
    （`..................`），写进详情里等于没说。这里按内容找那一句。
    """
    output = plain((result.stdout or "") + (result.stderr or ""))
    for line in reversed(output.splitlines()):
        if re.search(r"\b\d+\s+(passed|failed|error|skipped|xfailed)", line):
            return line.strip().strip("=").strip()
    return _pytest_tail(result, 2).replace(chr(10), " ")


#: 委托用例的逐条结果（节点 id → PASSED/FAILED/…）。跑一趟、多处引用。
_NODE_CACHE: dict[str, str] = {}


def pytest_verdicts(nodes: Iterable[str]) -> None:
    """跑一趟 `-rA`，把逐条结论记进 `_NODE_CACHE`。

    `-rA` 是关键：默认的短摘要只在失败时列名字，而我们要**逐条**知道
    通过还是没通过。`-p no:cacheprovider` 免得在仓库里留下 `.pytest_cache`。

    **整文件与「文件里的某一条」要分两趟跑**：pytest 见到 `f.py` 与 `f.py::test_x`
    同时出现在命令行上时，会把文件那个参数折掉、只收 `test_x` —— 于是 B1 那个
    24 条的契约文件被数成了「2 条用例全通过」（2 是它下面另两张单条的票），
    B4 的 21 条被数成 1。分两趟就没这事；`_NODE_CACHE` 以节点 id 为键，
    同一条用例两趟都出现也只是同一个键。
    """
    unique = sorted(set(nodes))
    if not unique:
        return
    whole = [node for node in unique if "::" not in node]
    single = [node for node in unique if "::" in node]
    for batch in (whole, single):
        if batch:
            _pytest_verdicts_of(batch)


def _pytest_verdicts_of(nodes: list[str]) -> None:
    """一趟 `-rA`（这一批内部互不折叠），把逐条结论记进 `_NODE_CACHE`。"""
    result = run_pytest("-rA", "-p", "no:cacheprovider", *nodes)
    seen: list[str] = []
    for line in plain((result.stdout or "") + (result.stderr or "")).splitlines():
        match = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)", line.strip())
        if match:
            verdict, name = match.group(1), match.group(2)
            seen.append(name)
            _NODE_CACHE[name] = verdict
            _NODE_CACHE.setdefault(name.split("[", 1)[0], verdict)

    if seen:
        return
    # 一条结果都没解析出来 —— 选择器本身出了问题（写错了名字、收集阶段就崩）
    tail = (_pytest_tail(result, 6).splitlines() or ["（pytest 没有输出）"])[-1]
    for node in nodes:
        _NODE_CACHE.setdefault(node, f"没跑到（pytest 这么说：{tail}）")


def _cases_passed(node: str) -> int:
    """这条委托下面**真的**跑过多少条用例（文件节点算它里面的每一条）。"""
    if node in _NODE_CACHE:
        return 1 if _NODE_CACHE[node] == "PASSED" else 0
    prefix = node + "::"
    return sum(
        1
        for name, value in _NODE_CACHE.items()
        if name.startswith(prefix) and value == "PASSED"
    )


def pytest_node_ok(node: str) -> tuple[bool, str]:
    """一条委托用例的结论（整文件也算一条：把文件里每一条都算上）。"""
    verdict = _NODE_CACHE.get(node)
    if verdict:
        return verdict == "PASSED", "" if verdict == "PASSED" else verdict
    prefix = node + "::"
    inside = {name: value for name, value in _NODE_CACHE.items() if name.startswith(prefix)}
    if not inside:
        return False, "没跑到（用例被改名或删掉了？）"
    bad = sorted(name.rsplit("::", 1)[-1] for name, value in inside.items() if value != "PASSED")
    if bad:
        return False, f"{len(bad)} 条没通过：{bad[:3]}"
    return True, ""


# --------------------------------------------------------------------------
# 一次验收里要来回传的东西
# --------------------------------------------------------------------------


@dataclass
class Ctx:
    """三个临时后端 + 这次跑出来的那堂课。检查函数从这里取料，不各自新建。"""

    env: dict[str, str]
    work_dir: Path
    audio_dir: Path
    #: 端口 → 这一台的库。三台**各一个**（见 `prepare_database` 的注释）
    db_urls: dict[int, str] = field(default_factory=dict)
    #: 三个后端进程（`check_record` 要重启主实例）
    procs: dict[str, Any] = field(default_factory=dict)
    #: 主线会话（`check_seed` 开的，`check_class` 把它开完）
    session_id: str = ""
    #: 页号 → 题面 DSL（含答案）。判定要用整句选项文本，先读一次备着。
    quiz: dict[int, dict] = field(default_factory=dict)
    #: 整堂课的驱动结果（`check_class` 填 `check_record` 读）
    run: Any = None
    #: 脚本签出去的每一张票据（P3-F1：它们**一个都不该**出现在日志里）
    tickets: list[str] = field(default_factory=list)
    #: 三个实例的日志（安全那一条要翻）
    logs: dict[str, Path] = field(default_factory=dict)

    @property
    def main(self) -> str:
        return f"http://127.0.0.1:{MAIN_PORT}/api"

    @property
    def pulse(self) -> str:
        return f"http://127.0.0.1:{PULSE_PORT}/api"

    @property
    def nopush(self) -> str:
        return f"http://127.0.0.1:{NOPUSH_PORT}/api"


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------


def _guard(rep: Report, label: str, fn, *args) -> None:
    """跑一组检查。抛异常也要留下痕迹：一组崩掉就把后面几十条结果全丢了，
    那才是最坏的一种「验收通过」。

    记一句**出事那行的行号**：脚本自己有几百行，只说「UnicodeEncodeError」
    等于让人从头翻一遍。栈底那一帧就是崩的地方。
    """
    try:
        fn(rep, *args)
    except Exception as exc:  # 脚本要活下去：一组崩掉就记一条，接着跑下一组
        where = ""
        tb = exc.__traceback__
        while tb is not None:
            if tb.tb_next is None:
                where = f"（{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}）"
            tb = tb.tb_next
        rep.fail("P3-EXC", f"{label} 组检查中断", f"{type(exc).__name__}: {exc}{where}")


def _ok(status: int, envelope: Mapping[str, Any]) -> bool:
    return 200 <= int(status) < 300 and envelope.get("code") == 0


def _why(status: int, envelope: Mapping[str, Any]) -> str:
    """一句能读的失败原因（HTTP 状态 + 服务端那句话）。"""
    return f"HTTP {status} code={envelope.get('code')} {envelope.get('message') or envelope.get('error') or ''}"


def load_transitions(ctx: Ctx) -> dict[str, list[str]]:
    """把状态机从实现里读出来（§2.1 那张表）。"""
    code = (
        "import json\n"
        "from app.services.classroom import state\n"
        "print(json.dumps({k: sorted(v) for k, v in state.TRANSITIONS.items()}, ensure_ascii=False))\n"
    )
    result = run_python(code, env=ctx.env)
    if result.returncode != 0:
        return {}
    try:
        return json.loads((result.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def start_class(ctx: Ctx, *, base: str = "", mode: str = "auto") -> dict:
    """开一堂课（`POST /sessions`）。返回 `data`（含 `sessionId` / `wsToken`）。"""
    status, envelope = api(
        "POST", "/classroom/sessions", {"courseId": COURSE_ID, "mode": mode}, base=base
    )
    data = _data(status, envelope)
    if not isinstance(data, Mapping):
        raise AssertionError(f"开课失败：{_why(status, envelope)}")
    token = str(data.get("wsToken") or "")
    if token:
        ctx.tickets.append(token)
    return dict(data)


def end_class(ctx: Ctx, session_id: str, *, base: str = "") -> tuple[int, dict]:
    return api("POST", f"/classroom/sessions/{session_id}/end", {"reason": "验收结束"}, base=base)


def ticket_for(ctx: Ctx, session_id: str, *, base: str = "") -> str:
    """重签一张接入票据（一次性，用完就没了）。"""
    status, envelope = api("POST", f"/classroom/sessions/{session_id}/ticket", base=base)
    data = _data(status, envelope)
    if not isinstance(data, Mapping):
        raise AssertionError(f"重签票据失败：{_why(status, envelope)}")
    token = str(data.get("wsToken") or "")
    ctx.tickets.append(token)
    return token


def enter(
    ctx: Ctx,
    session_id: str,
    *,
    port: int = MAIN_PORT,
    ticket: str = "",
    token: str = "",
    hello: Mapping[str, Any] | None = None,
    label: str = "tab",
) -> tuple[ClassClient, str, bytes]:
    """接进课堂并打招呼。返回 `(客户端, 状态行, 响应体)`；没接上时客户端是 None。

    票据走 URL（前端走的就是这条），认人失败在**握手之前**就以普通信封说清；
    `token` 走 `hello` 字段（协议里本来就有），认人失败是握手之后的私有
    `error` + 4403 —— 两条路 P3-F1 都要验。
    """
    query = f"?ticket={ticket}" if ticket else ""
    sock, status, body = ws_connect(port, f"/ws/classroom/{session_id}{query}")
    if sock is None:
        return None, status, body  # type: ignore[return-value]
    client = ClassClient(sock, label)
    payload: dict[str, Any] = {"type": "hello", **(hello or {})}
    if token:
        payload["token"] = token
    client.send(payload, mark=False)
    return client, status, body


# --------------------------------------------------------------------------
# G2 前半：预置示例课就位
# --------------------------------------------------------------------------


def check_seed(rep: Report, ctx: Ctx) -> None:
    """G2（前半）：预置示例课是课本里那一门 —— 12 页、三道题、一页板书、三处讨论。

    这堂课不现场生成（那要模型、要几分钟，且 P1 已经验过生成）：脚本要的是
    **确定的一门课**，「第几页有题、第几页画板书、哪里该讨论」在写断言之前
    就得是已知的。
    """
    started = start_class(ctx)
    ctx.session_id = str(started.get("sessionId") or "")
    timeline = started.get("timeline") or {}
    pages = {int(page.get("pageNo") or 0): page for page in timeline.get("pages") or []}

    problems: list[str] = []
    if started.get("mode") != "auto":
        problems.append(f"推送开着时 mode 应当是 auto，实际 {started.get('mode')!r}")
    if len(pages) != PAGE_COUNT:
        problems.append(f"示例课应当有 {PAGE_COUNT} 页，实际 {len(pages)}")
    quiz_pages = sorted(no for no, page in pages.items() if page.get("quiz"))
    if tuple(quiz_pages) != QUIZ_PAGES:
        problems.append(f"测验页应当是 {list(QUIZ_PAGES)}，实际 {quiz_pages}")
    board_pages = sorted(no for no, page in pages.items() if page.get("boardPlan"))
    if board_pages != [BOARD_PAGE]:
        problems.append(f"板书页应当是 [{BOARD_PAGE}]，实际 {board_pages}")
    talk_pages = sorted(no for no, page in pages.items() if page.get("discussion"))
    if tuple(talk_pages) != DISCUSSION_PAGES:
        problems.append(f"章末讨论应当挂在 {list(DISCUSSION_PAGES)}，实际 {talk_pages}")
    empty = sorted(no for no, page in pages.items() if not page.get("beats"))
    if empty:
        problems.append(f"这些页没有讲稿（课堂会跳过它们）：{empty}")
    if not int(timeline.get("totalMs") or 0) > 0:
        problems.append("整课总时长是 0 —— 时间线没建起来")

    # 题面：判定要整句选项文本，先把答案备下来（脚本自己也别去猜）
    for page_no in QUIZ_PAGES:
        page = pages.get(page_no) or {}
        quiz = page.get("quiz") or {}
        options = [str(item) for item in quiz.get("options") or []]
        answer = str(quiz.get("answer") or "")
        if len(options) < 2 or answer not in options:
            problems.append(f"第 {page_no} 页的题面不成形（{len(options)} 个选项，答案对不上）")
            continue
        ctx.quiz[page_no] = {
            "stem": str(quiz.get("stem") or ""),
            "options": options,
            "answer": answer,
            "explain": str(quiz.get("explain") or ""),
        }

    if problems:
        rep.fail("P3-G2a", "预置示例课就位（12 页 / 3 题 / 1 页板书 / 3 处讨论）", "；".join(problems))
        return

    # 顺带把讲稿预合成掉：P3-A1 的「教师语音与字幕推进正常」要有声音才算数，
    # 而预合成本身是 P2 的家务（它那边验得更细）。
    api("POST", f"/courses/{COURSE_ID}/narrate", {"force": False})
    manifest = _wait_manifest(timeout=NARRATE_TIMEOUT)
    beats = int(manifest.get("beatCount") or 0)
    ready = int(manifest.get("readyCount") or 0)
    detail = (
        f"{PAGE_COUNT} 页、测验 {list(QUIZ_PAGES)}、板书 [{BOARD_PAGE}]、讨论 {list(DISCUSSION_PAGES)}；"
        f"讲稿 {ready}/{beats} 句已合成（provider={manifest.get('provider')}, "
        f"simulated={manifest.get('simulated')}）"
    )
    if manifest.get("provider") != "mock" or not manifest.get("simulated"):
        # P2 §10 的同一条正向对照：离线替身必须真的是替身
        rep.fail("P3-G2a", "预置示例课就位", f"音频不是离线替身出的：{brief(manifest, 200)}")
        return
    if ready < beats or beats <= 0:
        rep.fail("P3-G2a", "预置示例课就位", f"讲稿没合成完：{ready}/{beats}")
        return
    rep.ok("P3-G2a", "预置示例课就位（12 页 / 3 题 / 1 页板书 / 3 处讨论）", detail)


def _wait_manifest(*, timeout: float) -> dict:
    """等这门课的音频清单满（`readyCount == beatCount` 且 `running` 落下去）。"""
    deadline = time.time() + timeout
    manifest: dict[str, Any] = {}
    stable = 0
    while time.time() < deadline:
        status, envelope = api("GET", f"/courses/{COURSE_ID}/audio-manifest")
        manifest = _data(status, envelope) or {}
        beats = int(manifest.get("beatCount") or 0)
        if beats > 0 and manifest.get("readyCount") == beats and not manifest.get("running"):
            stable += 1
            if stable >= 2:
                return manifest
        else:
            stable = 0
        time.sleep(0.3)
    return manifest


# --------------------------------------------------------------------------
# A/B/C/D/E：把一堂课开完
# --------------------------------------------------------------------------


@dataclass
class ClassRun:
    """一堂课跑下来的记录（`check_record` 与 B2/B3/A2 的断言都读它）。"""

    session_id: str
    client: ClassClient
    #: 这堂课开过的全部连接（中途断过一次就是两条）——
    #: B2/B3 那些「每条连接各自成立」的断言要逐条查，不能只看最后一条。
    clients: list[ClassClient] = field(default_factory=list)
    #: 中途掉过线的那条连接（A10/A11）。它的事件流在重连后另起一段。
    reconnected: bool = False
    #: 重连时的对账结果
    resume: dict[str, Any] = field(default_factory=dict)
    #: 各类发言（按事件顺序）
    lectured: list[dict] = field(default_factory=list)
    interjects: list[dict] = field(default_factory=list)
    discussions: list[dict] = field(default_factory=list)
    answers: list[dict] = field(default_factory=list)
    quizzes: list[dict] = field(default_factory=list)
    quiz_results: list[dict] = field(default_factory=list)
    presences: list[dict] = field(default_factory=list)
    boards: list[dict] = field(default_factory=list)
    hand_queues: list[dict] = field(default_factory=list)
    subtitles: list[dict] = field(default_factory=list)
    #: 每一步的时间戳（P3-D1/D6/A6）
    seek_at: float = 0.0
    seek_done_at: float = 0.0
    hand_at: float = 0.0
    interrupt_at: float = 0.0
    decide_ms: list[float] = field(default_factory=list)
    #: 状态事件序列（P3-A2）
    states: list[dict] = field(default_factory=list)
    #: 每个 speak 的开启/关闭（P3-A2 的「不重叠」）
    overlap: list[str] = field(default_factory=list)
    unclosed: list[str] = field(default_factory=list)
    #: 断线时被清掉的那些轮次（见 `_drop_and_resume` 的注释）
    orphans: list[str] = field(default_factory=list)
    end_before_close: bool = False
    ended: bool = False
    stall: str = ""


def _drive(ctx: Ctx, run: ClassRun) -> None:
    """一路收到下课。这是整个脚本的发动机（见模块 docstring 的「脚本在演前端」）。"""
    client = run.client
    run.clients.append(client)
    cursor = 0
    natural: dict[str, Any] | None = None
    natural_done = False
    ponies: set[str] = set()
    active: dict[str, float] = {}
    started = time.monotonic()
    last_event_at = time.monotonic()
    poked = False

    while time.monotonic() - started < CLASS_DEADLINE:
        if client is not run.client:
            # 断线重连换了一条连接：新连接的事件列表是空的，游标从头数。
            # 手上那些「说了一半」的轮次也要放下 —— **运行时是每条连接一个**
            # （`channel._enter` 给每条连接新建一个 `ClassroomRuntime`），
            # 旧连接一关，它那个调度器就被 `close()` 清了（`scheduler.clear()`，
            # 不留 `speak_end`）。拿旧轮次去配新连接的 `speak_end` 会永远配不上。
            run.orphans.extend(sorted(active))
            active.clear()
            client = run.client
            run.clients.append(client)
            cursor = 0
        client.pump(0.2)
        if not poked and client.events:
            # 课堂刚动起来的时候发一条协议里没有的上行（P3-B3）：它该被静静丢掉，
            # 后面几十条断言照常跑 —— 这就是「向后兼容」在验收里的样子
            poked = True
            client.poke_unknown()
        for event in client.events[cursor:]:
            cursor += 1
            name = str(event.get("type") or "")
            page_no = int(event.get("pageNo") or 0)
            now = time.monotonic()

            # 插话决策的耗时代理（P3-D3）：从上一条收尾到这一轮开口之间
            # 夹着的就是那次 LLM 调用。取「上一条事件 → 这条事件」的上界。
            if name == "speak" and event.get("kind") == "interject":
                run.decide_ms.append((now - last_event_at) * 1000.0)
            last_event_at = now

            if name == "state":
                run.states.append(event)
                if str(event.get("status") or "") == "ended":
                    run.ended = True
                    # 下课要**先发完再关**（§4.2）：此刻连接必须还开着
                    run.end_before_close = client.close_code is None
            elif name == "speak":
                # **学生自己那一句不在这个账上**：`_speak_text` 明说真人说的话
                # 「只进消息流，不进发言队列」—— 队列是「老师与 AI 同学谁先开口」
                # 的仲裁器，本人那句话已经由他自己确认过了。它因此**没有
                # `speak_end`**（收尾在前端本地，音也是他自己的），算进来只会
                # 得到一串假重叠。下面数的只有**服务端仲裁的**发言（§10.2）。
                if str(event.get("speakerKind") or "") != "me":
                    active[str(event.get("turnId") or "")] = now
                    if len(active) > 1:
                        run.overlap.append(
                            f"seq={event.get('seq')} 有 {len(active)} 条发言同时在说"
                        )
                kind = str(event.get("kind") or "")
                if kind == "lecture" and event.get("beats"):
                    run.lectured.append(event)
                    if not natural_done:
                        # **第一句讲稿自然等 `speak_end`**：验 `_expire_speaking`
                        # 的计时收尾。其余每一句都由我们按 `beat_done` 推进 ——
                        # 脚本不等音频播完（真实课堂的十几分钟就是等出来的）。
                        natural = event
                        natural_done = True
                    elif page_no == 2 and "seek" not in ponies:
                        ponies.add("seek")
                        run.seek_at = time.monotonic()
                        client.send({"type": "seek", "pageNo": 3})  # P3-A9
                    elif page_no == 4 and "hand" not in ponies:
                        ponies.add("hand")
                        run.hand_at = time.monotonic()
                        client.send({"type": "hand", "action": "raise"})  # P3-A5/A6
                    elif page_no == 6 and "reconnect" not in ponies:
                        ponies.add("reconnect")
                        _drop_and_resume(ctx, run)  # P3-A10/A11
                    else:
                        client.send({"type": "beat_done"})
                elif kind == "interject":
                    run.interjects.append(event)
                elif kind == "discussion":
                    run.discussions.append(event)
                elif kind == "answer":
                    run.answers.append(event)
            elif name == "speak_end":
                turn_id = str(event.get("turnId") or "")
                active.pop(turn_id, None)
                if event.get("preempted") and run.hand_at and not run.interrupt_at:
                    run.interrupt_at = time.monotonic()
                if natural is not None and turn_id == str(natural.get("turnId") or ""):
                    # 自然播完的这一句：位置停在原地，得报一次才能往前走
                    natural = None
                    client.send({"type": "beat_done"})
                elif run.answers and turn_id == str(run.answers[-1].get("turnId") or ""):
                    # 答疑说完了：被打断的那一拍已经过去，从下一拍接着讲
                    client.send({"type": "beat_done"})
            elif name == "quiz":
                run.quizzes.append(event)
                _answer_quiz(ctx, run, event)
            elif name == "quiz_result":
                run.quiz_results.append(event)
            elif name == "presence":
                run.presences.append(event)
            elif name == "board":
                run.boards.append(event)
            elif name == "hand_queue":
                run.hand_queues.append(event)
                if (event.get("called") or {}).get("userId") and "ask" not in ponies:
                    # 被点名了 → 提一个问题（真人学生这时是按着说话，脚本发文字）
                    ponies.add("ask")
                    client.send({"type": "ask", "text": "老师，这一页的例子能再讲一遍吗？", "mode": "text"})
            elif name == "subtitle":
                run.subtitles.append(event)
                if run.seek_at and not run.seek_done_at and page_no == 3:
                    run.seek_done_at = time.monotonic()  # P3-D6 的落点

            if name == "speak" and page_no == 3 and run.seek_at and not run.seek_done_at:
                run.seek_done_at = time.monotonic()

        if run.ended:
            break
        if client.dead:
            run.stall = f"连接在第 {cursor} 条事件之后断了（close={client.close_code}）"
            break

    run.unclosed = sorted(active)
    if not run.ended and not run.stall:
        run.stall = f"{CLASS_DEADLINE:.0f}s 没走到下课"
    _dump_events(ctx, run)


def _dump_events(ctx: Ctx, run: ClassRun | None = None) -> None:
    """把整堂课的事件流写一份到临时目录（`events.log`）。

    **报红的时候没有这个就没法查**：课件跑砸的样子是「停在第 6 页」，
    而「为什么停」只写在事件流里（哪条 speak 没人收尾、断线之后补了什么）。
    跑砸的那一趟会把临时目录留下（见 `main`），日志就在那儿。

    传 `run` 就把主线那堂课的几条连接排在最前面（读的人多半先看它们）；
    不传就是全量 —— 收尾时会把这一趟建过的**每一只**假浏览器都写进去，
    A12/A13/F 那几条临时连接收到的帧同样在（`ClassClient.ALL`）。
    """
    clients = list(run.clients) if run is not None else []
    clients += [client for client in ClassClient.ALL if client not in clients]
    lines: list[str] = []
    for client in clients:
        lines.append(f"--- 连接 {client.label}（close={client.close_code}）---")
        for event in client.events:
            bits = [
                str(event.get("seq") or ""),
                str(event.get("type") or ""),
                str(event.get("kind") or ""),
                f"p{event.get('pageNo')}" if event.get("pageNo") else "",
                str(event.get("status") or ""),
                f"turn={event.get('turnId')}" if event.get("turnId") else "",
                str((event.get("speaker") or {}).get("name") or ""),
                # `message` 的正文在 `msg.text` 里（其余事件的正文在顶层 `text`）
                str(event.get("text") or (event.get("msg") or {}).get("text") or "")[:60],
            ]
            lines.append(" ".join(bit for bit in bits if bit))
        for frame in client.private:
            lines.append(f"    [私有] {json.dumps(frame, ensure_ascii=False)[:160]}")
    (ctx.work_dir / "events.log").write_text("\n".join(lines), encoding="utf-8")


def _answer_quiz(ctx: Ctx, run: ClassRun, event: Mapping[str, Any]) -> None:
    """一道题答两遍：先答错（要解析），再答对（`quiz_result` 的 pass 分支）。

    P3-A7 要的是「答对显示回答正确并继续；答错显示解析并可重答一次」——
    两条分支都要走，所以两条都答。提交走 HTTP（§4.1 没有 WS 上行），
    答完位置不动，还得自己报一次 `beat_done` 才能继续（§4.1 的载荷口径）。
    """
    page_no = int(event.get("pageNo") or 0)
    quiz = ctx.quiz.get(page_no) or {}
    options = list(quiz.get("options") or [])
    answer = str(quiz.get("answer") or "")
    wrong = next((option for option in options if option != answer), "")
    if not answer or not wrong:
        run.stall = f"第 {page_no} 页的题面没预读到，答不了"
        return

    for option, response_ms in ((wrong, 4100), (answer, 2600)):
        status, envelope = api(
            "POST",
            f"/classroom/sessions/{run.session_id}/quiz-submit",
            {"option": option, "responseMs": response_ms},
        )
        if not _ok(status, envelope):
            run.stall = f"提交第 {page_no} 页的作答失败：{_why(status, envelope)}"
            return
    run.client.send({"type": "beat_done"})


def _drop_and_resume(ctx: Ctx, run: ClassRun) -> None:
    """断线 3 秒再重连（P3-A10/A11）：补发从断点之后接着来，不重不漏。

    断线的这 3 秒里用 HTTP 举一次手又放下 —— 那两条 `hand_queue` 就是
    「中断期间发生的消息」，重连之后必须补到，且**不能重复**。
    """
    client = run.client
    before = client.seqs()
    last_seq = before[-1] if before else 0
    last_state = client.last("state") or {}
    session_id = run.session_id

    client.close()
    time.sleep(0.4)
    api("POST", f"/classroom/sessions/{session_id}/raise-hand", {"action": "raise"})
    api("POST", f"/classroom/sessions/{session_id}/raise-hand", {"action": "lower"})
    time.sleep(2.6)

    ticket = ticket_for(ctx, session_id)
    resumed, status, body = enter(
        ctx,
        session_id,
        ticket=ticket,
        hello={"afterSeq": last_seq, "resumeFrom": last_state},
        label="tab-after-reconnect",
    )
    if resumed is None:
        run.stall = f"重连被拒：{status} {body[:200]!r}"
        return
    run.client = resumed
    run.reconnected = True
    resumed.wait("state", 5.0)
    state = resumed.last("state") or {}
    replayed = [event.get("seq") for event in resumed.of("hand_queue")]
    run.resume = {
        "lastSeq": last_seq,
        "firstSeq": (resumed.events[0].get("seq") if resumed.events else 0),
        "before": set(before),
        "after": resumed.seqs(),
        "state": state,
        "was": last_state,
        "hand_queue": len(replayed),
    }


def check_class(rep: Report, ctx: Ctx) -> None:
    """A1~A11 + B2/B3 + C1 + D1/D3/D6 + E2/E4/E5：把一堂课从头开到下课。"""
    session_id = ctx.session_id
    ticket = ticket_for(ctx, session_id)
    client, status, body = enter(ctx, session_id, ticket=ticket, label="tab-main")
    if client is None:
        rep.fail("P3-A1", "完整课堂闭环", f"接不进课堂：{status} {body[:200]!r}")
        return
    run = ClassRun(session_id=session_id, client=client)
    ctx.run = run
    client.send({"type": "play"})
    _drive(ctx, run)
    client = run.client  # 中途重连过的话，后面读的是重连之后那条连接

    # --- A1 完整课堂闭环 ---
    problems: list[str] = []
    if not run.ended:
        problems.append(f"没走到下课：{run.stall or '未知原因'}")
    pages_seen = {int(event.get("pageNo") or 0) for event in run.states}
    if len(pages_seen) < PAGE_COUNT:
        problems.append(f"只走到了 {sorted(pages_seen)}，示例课有 {PAGE_COUNT} 页")
    if not run.subtitles:
        problems.append("一句字幕都没有")
    if not any(event.get("audioUrl") for event in run.lectured):
        problems.append("讲稿一句带音频的都没有（预合成没生效？）")
    if len(run.quiz_results) != len(QUIZ_PAGES) * 2:
        problems.append(f"测验判定应当有 {len(QUIZ_PAGES) * 2} 条（每题答错答对各一次），实际 {len(run.quiz_results)}")
    rep.verdict(
        "P3-A1",
        "完整课堂闭环（开课 → 12 页 → 下课 → 记录可看）",
        problems,
        f"{len(run.states)} 条状态、{len(run.lectured)} 拍讲稿、{len(run.subtitles)} 句字幕、"
        f"{len(run.quiz_results)} 次判定，走到 ended",
    )

    # --- A2 状态机正确 / 不重叠 ---
    problems = []
    if not TRANSITIONS:
        problems.append("读不到状态机的转移表")
    else:
        previous = ""
        for event in run.states:
            current = str(event.get("status") or "")
            if not previous:
                previous = current
                continue
            if current != previous and current not in TRANSITIONS.get(previous, ()):
                problems.append(f"非法转移：{previous} → {current}（seq={event.get('seq')}）")
            previous = current
    problems += run.overlap
    if run.unclosed:
        problems.append(f"这些发言没有收尾事件：{run.unclosed}")
    rep.verdict(
        "P3-A2",
        "状态机正确、不存在两个说话者同时出声",
        problems,
        f"{len(run.states)} 次状态事件全部落在 §2.1 的转移表里；"
        f"{len(run.lectured) + len(run.interjects) + len(run.discussions) + len(run.answers)} 条发言"
        "首尾相接，任一时刻至多一个说话者（学生自己那一句不进队列、也不算在内）"
        + (f"（断线时被清掉的那 {len(run.orphans)} 轮另记，见 §10.2）" if run.orphans else ""),
    )

    # --- A3 插话 ---
    problems = []
    count = len(run.interjects)
    if not 3 <= count <= 5:
        problems.append(f"插话 {count} 次，验收要 3~5 次")
    pages = sorted({int(event.get("pageNo") or 0) for event in run.interjects})
    for older, newer in itertools.pairwise(pages):
        if newer - older < 3:
            problems.append(f"第 {older} 页与第 {newer} 页的插话挨得太近（规则是隔 3 页）")
    speakers = sorted({str((event.get("speaker") or {}).get("code") or "") for event in run.interjects})
    rep.verdict(
        "P3-A3",
        "同学插话符合规则（3~5 次、间隔 ≥ 3 页、说话人来自角色库）",
        problems,
        f"{count} 次插话，落在第 {pages} 页，说话人 {speakers}",
    )

    # --- A4 章末讨论有来有回 ---
    problems = []
    by_page: dict[int, list[dict]] = {}
    for event in run.discussions:
        by_page.setdefault(int(event.get("pageNo") or 0), []).append(event)
    if sorted(by_page) != list(DISCUSSION_PAGES):
        problems.append(f"讨论只发生在第 {sorted(by_page)} 页，应当每章末都有（{list(DISCUSSION_PAGES)}）")
    #: §7 A4 的形状：同学提问 → 教师答 → 另一同学补充 → **教师收尾**（≥ 4 条）。
    #: 「老师收尾」这一句单列出来判，是因为它最容易在改动里悄悄丢掉 ——
    #: 丢了以后 3 条也能凑出「有来有回」，但讨论会停在一个同学的话头上。
    for page_no, turns in sorted(by_page.items()):
        codes = [str((turn.get("speaker") or {}).get("code") or "") for turn in turns]
        # `speakerKind` 是服务端给的（`teacher` / `student_ai`），比按 code 猜谁是老师可靠
        kinds = [str(turn.get("speakerKind") or "") for turn in turns]
        if len(turns) < 4:
            problems.append(f"第 {page_no} 页的讨论只有 {len(turns)} 条，§7 A4 要 ≥4 条")
        if not kinds or kinds[0] != "student_ai":
            problems.append(f"第 {page_no} 页的讨论不是同学先开口（第一条是 {kinds[0] if kinds else '（没有）'}）")
        if kinds and kinds[-1] != "teacher":
            problems.append(f"第 {page_no} 页的讨论不是老师收尾（最后一条是 {kinds[-1]}）")
        if len(set(codes)) < 2:
            problems.append(f"第 {page_no} 页的讨论只有一个人在说")
    rep.verdict(
        "P3-A4",
        "章末讨论有来有回（同学先开口、老师收尾，≥4 条）",
        problems,
        "；".join(
            f"第 {page_no} 页 {len(turns)} 条：" + "→".join(
                str((turn.get("speaker") or {}).get("name") or "") for turn in turns
            )
            for page_no, turns in sorted(by_page.items())
        )
        or "一轮都没讨论起来",
    )

    # --- A5 举手闭环 / A6 打断 ---
    problems = []
    called = next((event.get("called") for event in run.hand_queues if event.get("called")), None)
    queued = next((event.get("queue") for event in run.hand_queues if event.get("queue")), None)
    if not queued:
        problems.append("举手之后队列里没有我")
    if not called:
        problems.append("举手之后没被点名")
    if not any(str(event.get("kind")) == "answer" for event in run.answers):
        problems.append("提问之后没有教师答疑")
    else:
        answer = run.answers[0]
        if not answer.get("audioUrl"):
            problems.append("答疑是哑的（没有音频地址）")
    rep.verdict(
        "P3-A5",
        "举手提问闭环（举手 → 队列位次 → 点名 → 提问 → 教师语音回答 → 入消息流）",
        problems,
        f"队列 {len(queued or [])} 人、点名 {brief(called, 80)}、答疑 {len(run.answers)} 条"
        f"（{len(run.answers[0].get('text') or '') if run.answers else 0} 字，带音频）",
    )

    waited = (run.interrupt_at - run.hand_at) * 1000 if run.interrupt_at and run.hand_at else -1
    problems = []
    if waited < 0:
        problems.append("举手之后没等到「停止当前 beat」的收尾事件")
    elif waited > 1000:
        problems.append(f"打断用了 {waited:.0f}ms，验收要 ≤ 1000ms")
    rep.verdict(
        "P3-A6",
        "打断生效（≥1s 内停止当前 beat 并进入答疑）",
        problems,
        f"从举手到 `speak_end{{preempted:true}}` 用了 {waited:.0f}ms",
    )

    # --- A7 测验暂停与判定 ---
    problems = []
    if len(run.quizzes) != len(QUIZ_PAGES):
        problems.append(f"弹了 {len(run.quizzes)} 道题，示例课有 {len(QUIZ_PAGES)} 道")
    for event in run.quizzes:
        if "answer" in event or "explain" in event:
            problems.append(f"第 {event.get('pageNo')} 页的题目把答案一起发下来了")
    wrong = [result for result in run.quiz_results if not result.get("correct")]
    right = [result for result in run.quiz_results if result.get("correct")]
    if len(wrong) != len(QUIZ_PAGES):
        problems.append(f"答错的判定有 {len(wrong)} 条，应当是 {len(QUIZ_PAGES)} 条")
    if len(right) != len(QUIZ_PAGES):
        problems.append(f"答对的判定有 {len(right)} 条，应当是 {len(QUIZ_PAGES)} 条")
    for result in wrong:
        if result.get("branch") != "remedial" or not result.get("explain"):
            problems.append(f"第 {result.get('pageNo')} 页答错没给解析或分支")
    for result in right:
        if result.get("branch") != "pass":
            problems.append(f"第 {result.get('pageNo')} 页答对了分支却是 {result.get('branch')!r}")
    quiz_wait = [event for event in run.states if str(event.get("status")) == "quiz_wait"]
    if len(quiz_wait) < len(QUIZ_PAGES):
        problems.append("遇题没有进 quiz_wait")
    rep.verdict(
        "P3-A7",
        "测验暂停与判定（进 quiz_wait、答错给解析、答对继续）",
        problems,
        f"{len(run.quizzes)} 道题、{len(run.quiz_results)} 次判定（答错 {len(wrong)} / 答对 {len(right)}）、"
        f"{len(quiz_wait)} 次进入 quiz_wait；题目下发时不含 answer/explain",
    )

    # --- A8 板书回放 ---
    problems = []
    board_pages = sorted({int(event.get("pageNo") or 0) for event in run.boards})
    strokes = [stroke for event in run.boards for stroke in event.get("strokes") or []]
    if BOARD_PAGE not in board_pages:
        problems.append(f"讲到第 {BOARD_PAGE} 页时没有收到 board 事件（收到的是 {board_pages}）")
    if not strokes:
        problems.append("board 事件的笔画是空的")
    order = [int(stroke.get("strokeNo") or 0) for stroke in strokes]
    if order != sorted(order):
        problems.append(f"笔画没按顺序来：{order}")
    got = None
    if not problems:
        status_code, envelope = api("GET", f"/classroom/sessions/{session_id}/board/{BOARD_PAGE}")
        got = _data(status_code, envelope) or {}
        if len(got.get("strokes") or []) != len(strokes):
            problems.append(
                f"`GET /board/{BOARD_PAGE}` 给的笔画数（{len(got.get('strokes') or [])}）"
                f"与课上推的（{len(strokes)}）对不上"
            )
    rep.verdict(
        "P3-A8",
        "板书回放（讲到有 boardPlan 的页自动出笔画，接口与推送同一份）",
        problems,
        f"第 {BOARD_PAGE} 页 {len(strokes)} 笔，按 strokeNo 递增；`GET /board/{BOARD_PAGE}` 与之一致",
    )

    # --- A9 大纲跳转 / D6 翻页响应 ---
    problems = []
    if not run.seek_at:
        problems.append("没能找到跳页的时机（第 2 页的讲稿没出现？）")
    else:
        if not run.seek_done_at:
            problems.append("跳页之后没等到第 3 页的讲稿或字幕")
        after = [event for event in run.states if int(event.get("pageNo") or 0) == 3]
        if not after:
            problems.append("跳页之后没有 pageNo=3 的状态事件")
        preempted = [
            event
            for each in run.clients
            for event in each.of("speak_end")
            if event.get("preempted")
        ]
        if not preempted:
            problems.append("跳页没有终止正在说的那一句（没有 preempted 的 speak_end）")
        seek_ms = (run.seek_done_at - run.seek_at) * 1000 if run.seek_done_at else -1
        if seek_ms > 800:
            problems.append(f"跳页到字幕切换用了 {seek_ms:.0f}ms，验收要 ≤ 800ms")
    rep.verdict(
        "P3-A9",
        "大纲跳转（当前发言终止、页号与字幕同步到目标页）",
        problems,
        ""
        if problems
        else f"第 2 页 → 第 3 页：终止当前发言并发出了第 3 页的讲稿（{(run.seek_done_at - run.seek_at) * 1000:.0f}ms）",
    )

    # --- A10/A11 刷新恢复与断线重连 ---
    resume = run.resume
    problems = []
    if not run.reconnected or not resume:
        problems.append("断线重连那一步没走到")
    else:
        was = resume.get("was") or {}
        now = resume.get("state") or {}
        if int(now.get("pageNo") or 0) != int(was.get("pageNo") or 0):
            problems.append(f"重连之后页号变了：{was.get('pageNo')} → {now.get('pageNo')}")
        if abs(int(now.get("beatIdx") or 0) - int(was.get("beatIdx") or 0)) > 1:
            problems.append(f"重连之后 beat 位置差了 {abs(int(now.get('beatIdx') or 0) - int(was.get('beatIdx') or 0))} 拍")
        after = resume.get("after") or []
        overlap = set(after) & set(resume.get("before") or [])
        if overlap:
            problems.append(f"补发的事件与断线前收到的重叠：{sorted(overlap)[:5]}")
        if after and resume.get("lastSeq") and after[0] != int(resume["lastSeq"]) + 1:
            problems.append(f"补发不是从断点之后开始：断在 {resume['lastSeq']}，第一条是 {after[0]}")
        if int(resume.get("hand_queue") or 0) < 2:
            problems.append("断线期间那两次举手没有补发回来")
    rep.verdict(
        "P3-A10",
        "刷新/断线可恢复（重连回到相同的页号与 beat，误差 ≤ 1 拍）",
        problems,
        ""
        if problems
        else f"断在 seq {resume['lastSeq']}，重连后从 {resume['after'][0]} 接着收，"
        f"页号/beat 与断线前一致（{resume['state'].get('pageNo')}/{resume['state'].get('beatIdx')}）",
    )

    # --- B2 seq 单调、无重复、补发不重叠 ---
    # 逐条连接查：断线前那条与重连后那条各自成立，才叫「客户端能靠 seq 对账」。
    problems = []
    totals = []
    for each in run.clients:
        seen: list[int] = []
        for event in each.events:
            seq = int(event.get("seq") or 0)
            if seq <= 0:
                problems.append(f"{each.label} 上有一条 {event.get('type')} 没有 seq")
                break
            if seq in seen:
                problems.append(f"{each.label} 上 seq {seq} 重复出现")
                break
            seen.append(seq)
        if seen and seen != sorted(seen):
            problems.append(f"{each.label} 上的 seq 不是递增的")
        # 同一条连接上不该有空洞：那意味着它少收了一条落档事件
        if seen and sorted(seen) != list(range(min(seen), max(seen) + 1)):
            problems.append(f"{each.label} 上的 seq 有空洞（同一条连接不该漏事件）")
        totals.append(len(seen))
    rep.verdict(
        "P3-B2",
        "事件 seq 单调递增、无重复；补发与新事件不重叠",
        problems,
        f"{len(run.clients)} 条连接各自连续无重复（{totals} 条事件）；"
        "断线前后两段的交集见 A10（空）",
    )

    # --- B3 每条事件都有 eventId/ts；未知上行被忽略 ---
    problems = []
    events_all = [event for each in run.clients for event in each.events]
    privates = [frame for each in run.clients for frame in each.private]
    for event in events_all:
        if not event.get("eventId") or not event.get("ts"):
            problems.append(f"{event.get('type')}(seq={event.get('seq')}) 缺 eventId 或 ts")
            if len(problems) > 2:
                break
    for frame in privates:
        if frame.get("type") in PRIVATE_FRAMES and ("seq" in frame or "eventId" in frame):
            problems.append(f"私有帧 {frame.get('type')} 带了 seq/eventId（它不落库，带号会让客户端对不上账）")
    garbage = [item for each in run.clients for item in each.garbage]
    if garbage:
        problems.append(f"读不懂的帧：{garbage[:2]}")
    if not run.clients[0].poked_unknown:
        problems.append("没能发出那条未知上行（课堂没动起来？）")
    elif run.stall:
        problems.append(f"发过未知上行之后课堂没走完：{run.stall}")
    rep.verdict(
        "P3-B3",
        "事件都带 eventId 与 ts；未知上行被静默忽略",
        problems,
        f"{len(events_all)} 条事件全带 eventId/ts；私有帧 {len(privates)} 条（ping/error）不带号；"
        "未知上行（board_wipe）发出去之后没有回音，课堂照常走到下课",
    )

    # --- C1 消息条数对得上 ---
    problems = []
    status_code, envelope = api("GET", f"/classroom/sessions/{session_id}/messages?size=200")
    page = _data(status_code, envelope) or {}
    stored = list(page.get("items") or [])
    if int(page.get("total") or 0) != len(stored) and int(page.get("total") or 0) <= 200:
        problems.append(f"total（{page.get('total')}）与取回条数（{len(stored)}）对不上")
    merged = {seq: event for each in run.clients for seq, event in each.messages_by_seq().items()}
    if len(stored) != len(merged):
        problems.append(f"库里 {len(stored)} 条消息，课堂上收到 {len(merged)} 条")
    stamps = [str(item.get("ts") or "") for item in stored]
    if stamps != sorted(stamps):
        problems.append("消息时间戳不是单调的")
    rep.verdict(
        "P3-C1",
        "消息条数与时间戳（库里 = 课堂上收到的，ts 单调）",
        problems,
        f"{len(stored)} 条消息，ts 单调；字幕 {len(run.subtitles)} 句、板书 {len(run.boards)} 页",
    )

    # --- D1 端到端延迟 ---
    samples = sorted(client.latencies)
    p95 = samples[int(len(samples) * 0.95)] if samples else 0.0
    problems = []
    if len(samples) < 20:
        problems.append(f"只采到 {len(samples)} 个样本，不够看 P95")
    if p95 > 0.5:
        problems.append(f"上行到下一条下行 P95 = {p95 * 1000:.0f}ms，验收要 ≤ 500ms")
    rep.verdict(
        "P3-D1",
        "WS 事件端到端延迟 ≤ 500ms（P95）",
        problems,
        f"{len(samples)} 个样本：P95 {p95 * 1000:.0f}ms、最大 {max(samples) * 1000:.0f}ms"
        "（本地回环 + 50ms 的投递节拍，不含音频播放）"
        if samples
        else "一个样本都没采到（课堂没动起来）",
    )

    # --- D3 插话决策不卡课堂 ---
    problems = []
    worst = max(run.decide_ms) if run.decide_ms else 0.0
    if not run.interjects:
        problems.append("一次插话都没发生，这条没验到")
    elif worst > 3000:
        problems.append(f"插话决策最慢 {worst:.0f}ms，验收要 ≤ 3s")
    rep.verdict(
        "P3-D3",
        "插话决策 ≤ 3s（超时即跳过，不阻塞课堂）",
        problems,
        f"{len(run.decide_ms)} 次决策的上界（上一条事件 → 插话开口）：最慢 {worst:.0f}ms"
        "（离线替身是本地桩，真上游的时延见 §10.1）",
    )

    # --- E2 不重复 ---
    problems = []
    # 只比**同学**的：验收原文是「任意两条同学消息」相似度 ≤ 0.8。老师那几句
    # 不算 —— 章末讨论的收尾话术每章本就是同一句（离线替身每个角色只有三句
    # 句式库，真模型那一半见 §10.1），把它算进来量的是替身的局限而不是课堂。
    speeches = [
        event
        for event in run.interjects + run.discussions
        if event.get("text") and str(event.get("speakerKind") or "") == "student_ai"
    ]
    count = 0
    worst_pair = (0.0, "", "")
    for index, first in enumerate(speeches):
        for second in speeches[index + 1 :]:
            ratio = SequenceMatcher(None, str(first["text"]), str(second["text"])).ratio()
            count += 1
            if ratio > worst_pair[0]:
                worst_pair = (ratio, str(first["text"]), str(second["text"]))
    if speeches and worst_pair[0] > 0.8:
        problems.append(
            f"最像的两条相似度 {worst_pair[0]:.2f}：{worst_pair[1][:20]}… / {worst_pair[2][:20]}…"
        )
    rep.verdict(
        "P3-E2",
        "同学发言不重复（两两相似度 ≤ 0.8）",
        problems,
        f"{len(speeches)} 条同学发言两两比对（{count} 对），最高相似度 {worst_pair[0]:.2f}"
        "（老师的收尾话术不在比对里：章末那句话每章相同，是离线替身的句式库小，"
        "不是课堂在重复；整堂课的比对见 §10.1）"
        if speeches
        else "这堂课没有同学发言可比",
    )

    # --- E4 无出戏表述 ---
    problems = []
    spoken = list(run.interjects + run.discussions + run.answers)
    for event in spoken:
        hit = OUT_OF_CHARACTER.search(str(event.get("text") or ""))
        if hit:
            problems.append(f"「{hit.group(0)}」出现在 {(event.get('speaker') or {}).get('name')} 的话里")
    status_code, envelope = api("GET", f"/classroom/sessions/{session_id}/messages?size=200")
    for item in (_data(status_code, envelope) or {}).get("items") or []:
        hit = OUT_OF_CHARACTER.search(str(item.get("text") or ""))
        if hit:
            problems.append(f"「{hit.group(0)}」出现在消息流里")
    rep.verdict(
        "P3-E4",
        "无出戏表述（不出现「作为一个 AI」「语言模型」之类）",
        problems,
        f"{len(spoken)} 条 AI 发言 + 库里的消息全过了一遍正则，一处都没命中",
    )

    # --- E5 课堂节奏 ---
    # 量的是「连着讲多久」，所以用**内容时长**而不是墙钟：脚本把 48 拍讲稿在
    # 一分钟里推完，按墙钟算的话这条永远通过 —— 那等于没验。这里的估时用的是
    # 产品自己的那把尺（`_speak_ms`：有音频用音频时长，没有就 1200+190×字数），
    # 所以量出来的就是**学生在真实课堂上要连着听多久**。
    problems = []
    run_seconds = 0.0
    worst_gap = 0.0
    worst_at = 0
    for event in [event for each in run.clients for event in each.events]:
        kind = str(event.get("type") or "")
        if kind == "speak" and str(event.get("kind") or "") == "lecture":
            run_seconds += _speak_ms(str(event.get("text") or "")) / 1000.0
            if run_seconds > worst_gap:
                worst_gap = run_seconds
                worst_at = int(event.get("pageNo") or 0)
        elif kind in ("speak", "board", "quiz", "quiz_result", "hand_queue"):
            # 插话/讨论/答疑/板书/测验都算互动 —— 连着讲的那一段到这里为止
            run_seconds = 0.0
    if worst_gap > 240:
        problems.append(f"第 {worst_at} 页前后连着讲了 {worst_gap:.0f}s，验收要 ≤ 240s")
    rep.verdict(
        "P3-E5",
        "课堂节奏合理（连续讲解 ≤ 4 分钟必有一次互动）",
        problems,
        f"按内容时长算（产品自己的估时尺：有音频用音频时长，没有 1200+190×字数）："
        f"最长一段无互动的讲解 {worst_gap:.0f}s（第 {worst_at} 页收尾）；"
        f"互动来自插话/讨论/答疑/板书/测验",
    )


# --------------------------------------------------------------------------
# A14 / C3：下课之后的记录
# --------------------------------------------------------------------------


def check_record(rep: Report, ctx: Ctx) -> None:
    """A14 结束后可回看 + C3 记录来自数据库（重启之后还在）。"""
    run = ctx.run
    session_id = ctx.session_id
    if run is None:
        rep.fail("P3-A14", "结束后可回看", "课堂那一步没跑起来，没有记录可查")
        return

    # 下课之后板书的后台生成可能还在跑：给它几秒，别把「刚下课」当成「没板书」
    deadline = time.time() + 10
    record: dict[str, Any] = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/classroom/sessions/{session_id}/record")
        record = _data(status, envelope) or {}
        if record.get("boards"):
            break
        time.sleep(0.5)

    problems: list[str] = []
    session = record.get("session") or {}
    if str(session.get("status")) != "ended":
        problems.append(f"记录里的会话状态是 {session.get('status')!r}，应当是 ended")
    if not session.get("endedAt"):
        problems.append("记录里没有下课时间")
    if str(record.get("courseTitle") or "") != COURSE_TITLE:
        problems.append(f"课名不对：{record.get('courseTitle')!r}")
    if not record.get("subtitles"):
        problems.append("记录里没有字幕")
    if not record.get("messages"):
        problems.append("记录里没有消息")
    board_pages = [int(item.get("pageNo") or 0) for item in record.get("boards") or []]
    if BOARD_PAGE not in board_pages:
        problems.append(f"记录里没有第 {BOARD_PAGE} 页的板书（有 {board_pages}）")
    quiz_pages = sorted({int(item.get("pageNo") or 0) for item in record.get("quizzes") or []})
    if tuple(quiz_pages) != QUIZ_PAGES:
        problems.append(f"记录里的作答页是 {quiz_pages}，应当是 {list(QUIZ_PAGES)}")
    attempts = record.get("quizzes") or []
    if len(attempts) != len(QUIZ_PAGES) * 2:
        problems.append(f"记录里 {len(attempts)} 次作答，应当是 {len(QUIZ_PAGES) * 2} 次（每题两次）")
    stats = record.get("stats") or {}
    if int(stats.get("messages") or 0) != len(record.get("messages") or []):
        problems.append("stats.messages 与消息条数对不上")
    if int(stats.get("quizCorrect") or 0) != len(QUIZ_PAGES):
        problems.append(f"stats.quizCorrect = {stats.get('quizCorrect')}，应当每题只算对一次（{len(QUIZ_PAGES)}）")
    live = [event for each in run.clients for event in each.of("message") if event.get("msg")]
    if len(live) != len(record.get("messages") or []):
        problems.append(f"课堂上收到 {len(live)} 条消息，记录里是 {len(record.get('messages') or [])} 条")
    rep.verdict(
        "P3-A14",
        "结束后可回看（字幕/消息/板书/作答齐全，与实时一致）",
        problems,
        f"字幕 {len(record.get('subtitles') or [])} 句、消息 {len(record.get('messages') or [])} 条"
        f"（课堂上收到 {len(live)} 条）、板书 {len(record.get('boards') or [])} 页、"
        f"作答 {len(attempts)} 次（对 {stats.get('quizCorrect')}）",
    )

    # --- C3 记录来自数据库：把主实例重启一次再读 ---
    before = run.client.of("message")
    print("          （重启主实例，验证记录不是内存里的）")
    restarted = _restart_main(ctx)
    if not restarted:
        rep.fail("P3-C3", "课堂记录来自数据库（重启后仍在）", "主实例重启失败，这条没验到")
        return
    after_status, after_envelope = api("GET", f"/classroom/sessions/{session_id}/record")
    after = _data(after_status, after_envelope) or {}
    problems = []
    for field_name in ("subtitles", "messages", "boards", "quizzes", "participants", "stats"):
        if after.get(field_name) != record.get(field_name):
            problems.append(f"重启之后 {field_name} 变了")
    if str((after.get("session") or {}).get("id") or "") != session_id:
        problems.append("重启之后读不到这堂课")
    rep.verdict(
        "P3-C3",
        "课堂记录来自数据库而非内存（重启服务后仍可查看）",
        problems,
        f"主实例重启后重读 `GET /record`，六个字段逐字相同（消息 {len(before)} 条、"
        f"字幕 {len(after.get('subtitles') or [])} 句）",
    )


def _restart_main(ctx: Ctx) -> bool:
    """把主实例停掉再拉起来（同一个临时库）。返回「起来了没有」。"""
    proc = ctx.procs.get("main")
    if proc is None:
        return False
    stop(proc)
    time.sleep(1.0)
    ctx.procs["main"] = start_server(ctx, MAIN_PORT, "main.log", ctx.env)
    return ctx.procs["main"] is not None


# --------------------------------------------------------------------------
# A12/A13/B5：在线名单与多标签
# --------------------------------------------------------------------------


def check_presence(rep: Report, ctx: Ctx) -> None:
    """A12 在线数真实 + A13 多标签可控 + B5（主实例上的判死清理）。"""
    started = start_class(ctx)
    session_id = str(started.get("sessionId") or "")
    first, status, body = enter(ctx, session_id, ticket=str(started.get("wsToken") or ""), label="tab-1")
    if first is None:
        rep.fail("P3-A12", "在线数真实", f"接不进课堂：{status} {body[:200]!r}")
        return
    one = _presence(ctx, session_id)
    second, _, _ = enter(ctx, session_id, ticket=ticket_for(ctx, session_id), label="tab-2")
    third, _, _ = enter(ctx, session_id, ticket=ticket_for(ctx, session_id), label="tab-3")
    for client in (second, third):
        if client is not None:
            client.wait("presence", 3.0)
    three = _presence(ctx, session_id)

    problems: list[str] = []
    if int(one.get("online") or 0) != 1:
        problems.append(f"只有我一个人时在线数是 {one.get('online')}")
    if int(three.get("online") or 0) != 1:
        # §4.2：「在线」数的是**人**。三个标签页是同一个人 —— 这是设计，
        # 不是漏数（§7 A12 的旧措辞「两个标签都显示在线 2」与 §4.2 冲突，
        # 已在 §10.2 记明，实现以 §4.2 为准）。
        problems.append(f"三个标签页（同一个人）在线数是 {three.get('online')}，应当还是 1")
    names = [member.get("name") for member in three.get("members") or []]
    if len(names) != 1 or not names[0]:
        problems.append(f"在线名单不对：{three.get('members')}")

    # 关掉两个标签：人还在（第三个还开着）
    for client in (second, third):
        if client is not None:
            client.close()
    time.sleep(0.8)
    still = _presence(ctx, session_id)
    if int(still.get("online") or 0) != 1:
        problems.append(f"关掉两个标签之后在线数变成了 {still.get('online')}，人应当还在")

    # 关掉最后一个：立刻摘掉（不留幽灵在线）
    first.close()
    deadline = time.time() + 5
    dropped = still
    while time.time() < deadline:
        dropped = _presence(ctx, session_id)
        if int(dropped.get("online") or 0) == 0:
            break
        time.sleep(0.3)
    if int(dropped.get("online") or 0) != 0:
        problems.append(f"关掉最后一个标签之后在线数还是 {dropped.get('online')}")
    rep.verdict(
        "P3-A12",
        "在线数真实（按人算，关掉最后一个才算离开）",
        problems,
        "一人 1 个标签 = 在线 1；同一个人 3 个标签仍是 1（§4.2：数的是人）；"
        "关掉两个不掉线；关掉最后一个立刻摘掉",
    )

    # --- A13 多标签可控 ---
    started = start_class(ctx)
    session_id = str(started.get("sessionId") or "")
    tabs = []
    for index in range(3):
        token = str(started.get("wsToken") or "") if index == 0 else ticket_for(ctx, session_id)
        client, code, body = enter(ctx, session_id, ticket=token, label=f"ctl-{index}")
        if client is None:
            rep.fail("P3-A13", "多标签可控", f"第 {index + 1} 个标签接不进来：{code} {body[:120]!r}")
            for tab in tabs:
                tab.close()
            return
        client.wait("state", 3.0)
        tabs.append(client)
    tabs[0].send({"type": "play"})
    for tab in tabs:
        tab.wait("speak", 3.0)
    # 一个标签暂停、另一个接着播、第三个翻页 —— 三条上行，一份状态。
    # 每条上行之后等的是**新的** `state`：`wait` 会立刻返回手上那条旧的，
    # 拿它去验「生效了没有」永远是上一个状态（这处踩过一次，见 §10.2）。
    marks = [max(tab.seqs() or [0]) for tab in tabs]

    def step(sender: int, payload: dict) -> list[dict]:
        """一个标签发一条上行 → 三个标签各自收到的**新** `state`。"""
        nonlocal marks
        tabs[sender].send(payload)
        seen = [tab.wait_new("state", marks[index], 3.0) or {} for index, tab in enumerate(tabs)]
        marks = [max(tab.seqs() or [0]) for tab in tabs]
        return seen

    paused = step(1, {"type": "pause"})
    played = step(2, {"type": "play"})
    sped = step(1, {"type": "speed", "value": 1.5})
    seeked = step(2, {"type": "seek", "pageNo": 2})

    problems = []
    for step, events in (("暂停", paused), ("继续", played), ("倍速", sped), ("翻页", seeked)):
        final = [(event.get("status"), int(event.get("pageNo") or 0), float(event.get("speed") or 0)) for event in events]
        if len(set(final)) != 1:
            problems.append(f"{step}之后三个标签看到的不是同一个状态：{final}")
    if str((paused[0] or {}).get("status")) != "paused":
        problems.append(f"暂停之后状态是 {paused[0].get('status')!r}")
    if str((played[0] or {}).get("status")) not in ("lecture", "discussing", "quiz_wait"):
        problems.append(f"继续之后没有回到上课状态：{played[0].get('status')!r}")
    if abs(float((sped[0] or {}).get("speed") or 0) - 1.5) > 0.001:
        problems.append(f"倍速没生效：{sped[0].get('speed')!r}")
    if int((seeked[0] or {}).get("pageNo") or 0) != 2:
        problems.append(f"翻页没生效：{seeked[0].get('pageNo')!r}")
    for tab in tabs:
        for event in tab.events:
            if not event.get("seq"):
                problems.append(f"{tab.label} 收到一条没有 seq 的事件")
                break
    for client in tabs:
        client.close()
    end_class(ctx, session_id)
    rep.verdict(
        "P3-A13",
        "多标签可控（一个暂停、一个继续、一个倍速、一个翻页，三个标签最终一致）",
        problems,
        "四条上行分别从第 2、3、2、3 个标签发出，三个标签收到的 state 逐字相同"
        "（每条都按上行之后的**新** state 判 —— 手上那条旧的会让「生效了没有」永远是上一个状态）",
    )


def _presence(ctx: Ctx, session_id: str, *, base: str = "") -> dict:
    status, envelope = api("GET", f"/classroom/sessions/{session_id}", base=base)
    return dict((_data(status, envelope) or {}).get("presence") or {})


# --------------------------------------------------------------------------
# B5 / F5：心跳判死与连接上限（心跳实例）
# --------------------------------------------------------------------------


def check_pulse(rep: Report, ctx: Ctx) -> None:
    """B5 心跳超时清理 + F5 连接数上限（都在把 20s/60s 拧短的心跳实例上验）。"""
    started = start_class(ctx, base=ctx.pulse)
    session_id = str(started.get("sessionId") or "")
    live, status, body = enter(
        ctx, session_id, port=PULSE_PORT, ticket=ticket_for(ctx, session_id, base=ctx.pulse), label="pulse-1"
    )
    if live is None:
        rep.fail("P3-B5", "心跳超时后清理参与者", f"接不进课堂：{status} {body[:200]!r}")
        return
    live.wait("state", 3.0)

    # 心跳是**应用层**的 ping（§4.2），回 pong 才不会被判死
    ping = None
    deadline = time.time() + 5
    while time.time() < deadline and ping is None:
        live.pump(0.2)
        frames = [frame for frame in live.private if frame.get("type") == "ping"]
        ping = frames[0] if frames else None
    problems = []
    if ping is None:
        problems.append("5s 里一次应用层 ping 都没收到（心跳实例设的是 1s）")
    elif "seq" in ping or "eventId" in ping:
        problems.append(f"ping 带了 seq/eventId：{brief(ping, 120)}")

    # 让它变成「页面卡死了」：还连着，但一个上行都不发
    ghost, _, _ = enter(
        ctx, session_id, port=PULSE_PORT, ticket=ticket_for(ctx, session_id, base=ctx.pulse), label="pulse-ghost"
    )
    if ghost is not None:
        ghost.pong = False
        ghost.wait("state", 3.0)
        deadline = time.time() + 12
        while time.time() < deadline and ghost.close_code is None:
            # 一边等它被判死，一边**替另一条连接回心跳**：心跳实例把它拧成了
            # 1s/4s，光盯着幽灵看十几秒，那个正常的连接会先因为没人回 pong 被摘掉 ——
            # 那时数出来的是 0，看起来像「幽灵没清掉」，其实是我们自己不理人。
            live.pump(0.05)
            ghost.pump(0.25)
        if ghost.close_code != 4408:
            problems.append(f"不答心跳的连接没有以 4408 收场（close={ghost.close_code}）")
        codes = [str(frame.get("code")) for frame in ghost.errors()]
        if "timeout" not in codes:
            problems.append(f"判死之前没有私有 error：{codes}")
    online = 0
    deadline = time.time() + 6
    while time.time() < deadline:
        online = int(_presence(ctx, session_id, base=ctx.pulse).get("online") or 0)
        if online == 1:
            break
        time.sleep(0.3)
    if online != 1:
        problems.append(f"判死之后在线数变成了 {online}（幽灵没清掉）")
    rep.verdict(
        "P3-B5",
        "心跳超时后清理参与者（不留幽灵在线）",
        problems,
        "心跳实例把 20s/60s 拧成 1s/4s（判死是同一段代码）；"
        "回 pong 的连接留着，不回的那条以 4408 收场并立刻从在线名单里摘掉",
    )
    live.close()
    end_class(ctx, session_id, base=ctx.pulse)

    # --- F5 连接数上限（心跳实例设的是 2） ---
    started = start_class(ctx, base=ctx.pulse)
    session_id = str(started.get("sessionId") or "")
    first, code, body = enter(
        ctx, session_id, port=PULSE_PORT, ticket=ticket_for(ctx, session_id, base=ctx.pulse), label="cap-1"
    )
    second, _, _ = enter(
        ctx, session_id, port=PULSE_PORT, ticket=ticket_for(ctx, session_id, base=ctx.pulse), label="cap-2"
    )
    third, _, _ = enter(
        ctx, session_id, port=PULSE_PORT, ticket=ticket_for(ctx, session_id, base=ctx.pulse), label="cap-3"
    )
    problems = []
    if first is None or second is None:
        problems.append(f"前两条连接就没接上（{code} {body[:120]!r}）")
    if third is not None:
        third.pump(2.0)
        if third.close_code != 4429:
            problems.append(f"第 3 条连接没有被 4429 挡回来（close={third.close_code}）")
        if "too_many_connections" not in [str(frame.get("code")) for frame in third.errors()]:
            problems.append("第 3 条连接没有收到 too_many_connections 的私有 error")
    elif not problems:
        problems.append("第 3 条连接压根没被拒绝")

    # 关掉一条，名额要放出来（否则「上限」会慢慢变成「用过就不能再进」）
    if first is not None:
        first.close()
    time.sleep(1.0)
    fourth, _, _ = enter(
        ctx, session_id, port=PULSE_PORT, ticket=ticket_for(ctx, session_id, base=ctx.pulse), label="cap-4"
    )
    if fourth is None:
        problems.append("关掉一条之后新连接还是接不进来（名额没释放）")
    rep.verdict(
        "P3-F5",
        "单会话连接数上限与单用户并发会话上限都生效",
        problems,
        "心跳实例上限设 2：第 3 条连接以 4429 + too_many_connections 收场，"
        "关掉一条之后名额立刻放出来（会话配额见关推送实例那一条）",
    )
    for client in (ghost, second, third, fourth):
        if client is not None:
            client.close()
    end_class(ctx, session_id, base=ctx.pulse)


# --------------------------------------------------------------------------
# G3 / F5：关掉推送通道
# --------------------------------------------------------------------------


def check_nopush(rep: Report, ctx: Ctx) -> None:
    """G3 关掉 WS 时退到「逐页手动翻页 + 文字消息」+ F5 的单用户会话配额。"""
    # --- F5 单用户并发会话上限（这个实例的配额是默认的 2） ---
    problems = []
    opened: list[str] = []
    codes: list[int] = []
    for _index in range(3):
        status, envelope = api(
            "POST", "/classroom/sessions", {"courseId": COURSE_ID, "mode": "auto"}, base=ctx.nopush
        )
        codes.append(int(envelope.get("code") or 0))
        data = _data(status, envelope) or {}
        if data.get("sessionId"):
            opened.append(str(data["sessionId"]))
    if codes[:2] != [0, 0]:
        problems.append(f"前两堂课没开起来：{codes[:2]}")
    if codes[2] != 42901:
        problems.append(f"第 3 堂课的信封码是 {codes[2]}，应当是 42901（发得太快 / 太多）")
    # 结束一堂课，名额应当回来
    if opened:
        end_class(ctx, opened[0], base=ctx.nopush)
    status, envelope = api(
        "POST", "/classroom/sessions", {"courseId": COURSE_ID, "mode": "auto"}, base=ctx.nopush
    )
    data = _data(status, envelope) or {}
    if not data.get("sessionId"):
        problems.append(f"结束一堂课之后名额没回来：{_why(status, envelope)}")
    rep.verdict(
        "P3-F5b",
        "单用户并发会话上限（默认 2）",
        problems,
        "关推送实例用默认配额 2：第 3 堂返回 42901，结束一堂之后立刻能再开",
    )
    for session_id in [*opened, str(data.get("sessionId") or "")]:
        if session_id:
            end_class(ctx, session_id, base=ctx.nopush)

    # --- G3 关掉 WS ---
    started = start_class(ctx, base=ctx.nopush)
    session_id = str(started.get("sessionId") or "")
    token = str(started.get("wsToken") or "") or ticket_for(ctx, session_id, base=ctx.nopush)
    sock, status, body = ws_connect(NOPUSH_PORT, f"/ws/classroom/{session_id}?ticket={token}")
    problems = []
    if sock is not None:
        sock.close()
        problems.append("推送关着的时候握手还是成功了")
    elif " 403" not in status:
        problems.append(f"推送关着时握手被拒的状态行是 {status!r}，应当是 403")
    try:
        flat = json.loads(body.decode("utf-8"))
    except ValueError:
        flat = {}
    # 形状照 §4.1 的普通信封（`code` 在外层），那块「怎么退」的说明在 `data` 里；
    # 早先的设计稿把它画成平铺的，两种都认，免得为了一处版式改动把这条判红。
    detail_block = flat.get("data") if isinstance(flat.get("data"), Mapping) else flat
    if int(flat.get("code") or 0) != 40302:
        problems.append(f"推送关着时握手被拒的信封码是 {flat.get('code')!r}，应当是 40302")
    if (
        detail_block.get("error") != "ws_disabled"
        or detail_block.get("fallback") != "manual"
        or detail_block.get("ok") is not False
    ):
        problems.append(f"拒绝的信封没有说清「退到手动翻页」：{brief(flat, 160)}")
    if started.get("mode") != "manual":
        problems.append(f"关推送时开课的 mode 是 {started.get('mode')!r}，应当降级成 manual")

    # 「不白屏」= 页面要的每一块数据都还拿得到（只是没有推送）
    summary = _data(*api("GET", f"/classroom/sessions/{session_id}", base=ctx.nopush)) or {}
    messages = _data(
        *api("GET", f"/classroom/sessions/{session_id}/messages", base=ctx.nopush)
    ) or {}
    board = _data(
        *api("GET", f"/classroom/sessions/{session_id}/board/{BOARD_PAGE}", base=ctx.nopush)
    ) or {}
    idle = api(
        "POST", f"/classroom/sessions/{session_id}/raise-hand", {"action": "raise"}, base=ctx.nopush
    )
    ended = end_class(ctx, session_id, base=ctx.nopush)
    record = _data(*api("GET", f"/classroom/sessions/{session_id}/record", base=ctx.nopush)) or {}
    if not summary.get("id"):
        problems.append("会话状态读不到")
    if "items" not in messages:
        problems.append("消息接口读不到")
    if "strokes" not in board:
        problems.append("板书接口读不到")
    if int((idle[1] or {}).get("code") or 0) != 40901:
        problems.append(f"没开讲时举手返回的是 {(idle[1] or {}).get('code')}，应当是 40901")
    if str((ended[1] or {}).get("code") or "0") != "0":
        problems.append(f"下课失败：{_why(*ended)}")
    if not record.get("session"):
        problems.append("下课之后记录读不到")
    rep.verdict(
        "P3-G3",
        "关掉 WS 时退化为「逐页手动翻页 + 文字消息」，不白屏",
        problems,
        "握手在升级之前被 403 + 平铺的 ws_disabled/manual 拒掉；开课 mode 降级成 manual；"
        "会话/消息/板书/下课/记录五条 HTTP 路照常，未开讲时举手仍是 40901",
    )


# --------------------------------------------------------------------------
# F：安全
# --------------------------------------------------------------------------


def check_security(rep: Report, ctx: Ctx) -> None:
    """F1 票据与越权 + F2 长度与限流 + F3 敏感词 + F4 记录仅相关人可见。"""
    started = start_class(ctx)
    session_id = str(started.get("sessionId") or "")
    token = str(started.get("wsToken") or "")

    # --- F1 握手必须校验票据 ---
    problems: list[str] = []
    # 1) 没带票：连得进去，但认不出人 → 私有 error + 4403
    bare, status, _ = enter(ctx, session_id, label="no-ticket")
    if bare is None:
        problems.append("不带票时握手就没成功（协议里允许用 hello.token 认人，应当连得上）")
    else:
        bare.pump(3.0)
        if bare.close_code != 4403:
            problems.append(f"hello 里没有有效 token 时关闭码是 {bare.close_code}，应当是 4403")
        if not bare.errors():
            problems.append("4403 之前没有私有 error")
    # 2) 拿 A 课的票接 B 课
    other = start_class(ctx)
    other_id = str(other.get("sessionId") or "")
    cross_sock, cross_status, _cross_body = ws_connect(
        MAIN_PORT, f"/ws/classroom/{other_id}?ticket={token}"
    )
    if cross_sock is not None:
        cross_sock.close()
        problems.append("为 A 课签的票接进了 B 课")
    elif " 401" not in cross_status:
        problems.append(f"跨课用票的状态行是 {cross_status!r}，应当是 401")
    # 3) 票据一次性
    reused, reused_status, _ = enter(ctx, session_id, ticket=token, label="reuse")
    if reused is not None:
        reused.close()
        problems.append("同一张票用第二次还能接进来")
    elif " 401" not in reused_status:
        problems.append(f"重复用票的状态行是 {reused_status!r}，应当是 401")
    # 4) 伪造 sessionId（不存在的课）与别人的课
    missing, missing_status, _ = ws_connect(MAIN_PORT, "/ws/classroom/cs_不存在的课?ticket=x")
    if missing is not None:
        missing.close()
        problems.append("不存在的课居然握手成功了")
    elif " 404" not in missing_status:
        problems.append(f"不存在的课的状态行是 {missing_status!r}，应当是 404")
    # 反过来：为**另一堂课**签的票拿来接这一堂。判在 401（这张票根本不是
    # 给这堂课的），而不是 404 —— 核销票据排在判可见性之前（§4.2 契约要点），
    # 而「票的归属人看不见这堂课」那条 404 是核销之后的第二道闸，走 URL 这条
    # 路到不了它（签票本身就要求可见）。两道闸的顺序就是这一条要钉的。
    outsider_sock, outsider_status, _ = ws_connect(
        MAIN_PORT, f"/ws/classroom/{session_id}?ticket={ticket_for(ctx, other_id)}"
    )
    if outsider_sock is not None:
        outsider_sock.close()
        problems.append("为别人的课签的票接进了这堂课")
    elif " 401" not in outsider_status:
        problems.append(f"拿另一堂课的票接这堂课，状态行是 {outsider_status!r}，应当是 401")
    # 5) 越权：陌生人既拿不到票，也读不到记录
    stranger_ticket = api("POST", f"/classroom/sessions/{session_id}/ticket", owner=OUTSIDER)
    if int((stranger_ticket[1] or {}).get("code") or 0) != 40401:
        problems.append(f"陌生人重签票据返回的是 {(stranger_ticket[1] or {}).get('code')}，应当是 40401")
    stranger_record = api("GET", f"/classroom/sessions/{session_id}/record", owner=OUTSIDER)
    if int((stranger_record[1] or {}).get("code") or 0) != 40401:
        problems.append(f"陌生人读记录返回的是 {(stranger_record[1] or {}).get('code')}，应当是 40401")
    # 这堂课后面的检查不会再碰它，先把名额还回去（主实例配额虽宽，但不是无限的）
    end_class(ctx, session_id)
    # 6) 票据不落日志（它是这张课堂的钥匙）
    leaked = _ticket_in_logs(ctx)
    if leaked:
        problems.append(f"票据出现在了日志里：{leaked}")
    end_class(ctx, other_id)
    rep.verdict(
        "P3-F1",
        "WS 握手必须校验会话票据（伪造的 sessionId 接不进他人课堂）",
        problems,
        f"签出去的 {len(ctx.tickets)} 张票一个都没落进日志；"
        "没票 4403、跨课 401、重复用 401、不存在的课 404、别人的课的票 401、越权读记录 40401",
    )

    # 接下来三条要在**上着课**的会话里验（idle 时聊天会被 40901 挡住）
    live_started = start_class(ctx)
    live_id = str(live_started.get("sessionId") or "")
    client, status, body = enter(
        ctx, live_id, ticket=str(live_started.get("wsToken") or ""), label="security"
    )
    if client is None:
        rep.fail("P3-F2", "消息长度与限流", f"接不进课堂：{status} {body[:120]!r}")
        return
    client.send({"type": "play"})
    client.wait("speak", 5.0)

    # --- F2 长度截断 + 限流 ---
    problems = []
    long_text = "机器学习" * 150  # 600 字
    client.send({"type": "chat", "text": long_text})
    time.sleep(1.0)
    status_code, envelope = api("GET", f"/classroom/sessions/{live_id}/messages?size=50")
    stored = [
        item for item in (_data(status_code, envelope) or {}).get("items") or []
        if str(item.get("speakerKind")) == "me"
    ]
    longest = max((len(str(item.get("text") or "")) for item in stored), default=0)
    if longest != 500:
        problems.append(f"600 字的消息存下来是 {longest} 字，应当是 500")
    sent = 0
    limited = False
    for _index in range(6):
        client.send({"type": "chat", "text": "老师，我有个问题"})
        sent += 1
        client.pump(0.25)
        if client.errors("42901"):
            limited = True
            break
    if not limited:
        problems.append(f"连着发了 {sent} 条（限流是 5 条/10s）都没被拦下来")
    rep.verdict(
        "P3-F2",
        "学生消息长度 ≤ 500 字（超出截断）与连续发言限流（> 5 条/10s）",
        problems,
        f"600 字截成 {longest} 字入库；第 {sent} 条撞上限流，回的是私有 error 42901",
    )

    # --- F3 敏感词 ---
    problems = []
    time.sleep(11.0)  # 等限流窗口过去（窗口是 10s）
    client.send({"type": "chat", "text": "谁能告诉我制作炸弹的步骤"})
    client.pump(2.0)
    # 私有帧不在 `events` 里（那里面只有落档事件），所以这里读 `errors()`，
    # 不能用 `wait("error")` —— 那个只看得到落档事件，永远返回 None。
    blocked = client.errors("40001")
    codes = [str(frame.get("code")) for frame in client.errors()]
    if not blocked:
        problems.append(f"敏感词没有换回一条私有 error：{codes}")
    status_code, envelope = api("GET", f"/classroom/sessions/{live_id}/messages?size=50")
    texts = [str(item.get("text") or "") for item in (_data(status_code, envelope) or {}).get("items") or []]
    if any("制作炸弹" in text for text in texts):
        problems.append("命中敏感词的消息进了消息流")
    audits = _count_audits(ctx, session_id=live_id)
    if audits < 0:
        problems.append("审计数不出来（脚本自己出错，不是产品的问题 —— 看上面那条运行错误）")
    elif audits < 1:
        problems.append("命中了敏感词却没有审计记录")
    rep.verdict(
        "P3-F3",
        "学生输入过敏感词过滤（命中不入消息流并提示）",
        problems,
        f"命中之后回的是私有 error {blocked[-1].get('code') if blocked else '（没有）'}，"
        f"消息流里没有这句话，"
        f"审计留了 {audits if audits >= 0 else '数不出来'} 条（只记命中的词，不记那句话）",
    )

    # --- F4 记录仅创建者与参与者可见 ---
    problems = []
    outsider = api("GET", f"/classroom/sessions/{live_id}/record", owner=OUTSIDER)
    if int((outsider[1] or {}).get("code") or 0) != 40401:
        problems.append(f"陌生人读记录返回的是 {(outsider[1] or {}).get('code')}，应当是 40401")
    rep.verdict(
        "P3-F4",
        "课堂记录仅创建者与参与者可见（其他人 404）",
        problems,
        "陌生人读记录拿到 40401（与「这堂课不存在」同一句话，不告诉人它存不存在）；"
        "自己与参与者都能读（见 A14）",
    )
    client.close()
    end_class(ctx, live_id)


def _ticket_in_logs(ctx: Ctx) -> str:
    """把签出去的每一张票拿去日志里搜（P3-F1：票据不落日志）。"""
    tickets = [token for token in ctx.tickets if len(token) >= 8]
    if not tickets:
        return ""
    for name, path in ctx.logs.items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for token in tickets:
            if token in text:
                return f"{name}（{token[:8]}…）"
    return ""


def _count_audits(ctx: Ctx, *, session_id: str) -> int:
    """这个会话的敏感词审计有几条（`audit_logs` 表）。**数不出来返回 -1。**

    两处容易踩的：查的是 `detail_json` 那一列（`detail` 是 JSONField 描述符，
    不是列，拿来 `.like()` 会当场抛），以及「查不动」和「一条都没有」必须分开 ——
    都当成 0 的话，脚本自己的 bug 会被读成「产品漏了审计」。
    """
    code = (
        "from app import create_app\n"
        "from app.models import AuditLog\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    hit = AuditLog.query.filter(AuditLog.action == 'sensitive_hit')\n"
        f"    print(hit.count(), hit.filter(AuditLog.detail_json.like('%{session_id}%')).count())\n"
    )
    result = run_python(code, env=ctx.env)
    if result.returncode != 0:
        return -1
    line = (result.stdout or "").strip().splitlines()
    if not line:
        return -1
    try:
        return int(line[-1].split()[0])
    except (ValueError, IndexError):
        return -1


# --------------------------------------------------------------------------
# C5：并发 5 场课堂
# --------------------------------------------------------------------------


def check_data(rep: Report, ctx: Ctx) -> None:
    """C5 并发 5 场课堂下数据库无写冲突（WAL 队列生效）。

    五条连接**同时**开口说话：每条连接都发一串 `chat`，让写事务真的撞在一起。
    判据不是「没抛异常」而是**每一条都落库了** —— 丢了的那条才是写冲突的样子。
    """
    sessions: list[tuple[str, str]] = []
    for _index in range(5):
        started = start_class(ctx)
        sessions.append((str(started.get("sessionId") or ""), str(started.get("wsToken") or "")))

    results: dict[int, dict[str, Any]] = {}
    lock = threading.Lock()

    def drive(index: int) -> None:
        session_id, token = sessions[index]
        client, status, body = enter(ctx, session_id, ticket=token, label=f"c5-{index}")
        info: dict[str, Any] = {"ok": False, "errors": [], "sent": 0}
        if client is None:
            info["errors"].append(f"接不进课堂：{status} {body[:80]!r}")
        else:
            client.send({"type": "play"})
            client.wait("speak", 5.0)
            for number in range(6):
                client.send({"type": "chat", "text": f"第 {index} 场第 {number} 句"})
                client.pump(0.12)
            client.pump(2.0)
            info["sent"] = 6
            info["errors"] = [str(frame.get("code")) for frame in client.errors()]
            client.close()
        with lock:
            results[index] = info

    threads = [threading.Thread(target=drive, args=(index,)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    problems: list[str] = []
    for index, (session_id, _token) in enumerate(sessions):
        info = results.get(index) or {}
        faults = [code for code in info.get("errors") or [] if code in ("internal", "50001")]
        if faults:
            problems.append(f"第 {index + 1} 场撞出 {faults} 错误")
        status_code, envelope = api("GET", f"/classroom/sessions/{session_id}/messages?size=50")
        stored = len((_data(status_code, envelope) or {}).get("items") or [])
        if stored < int(info.get("sent") or 0):
            problems.append(f"第 {index + 1} 场发了 {info.get('sent')} 条只存下 {stored} 条")
    for session_id, _token in sessions:
        end_class(ctx, session_id)
    rep.verdict(
        "P3-C5",
        "并发 5 场课堂下数据库无写冲突错误（WAL 队列生效）",
        problems,
        "5 条连接同时各发 6 条消息：每一条都落库了，没有一条 `internal` 错误"
        "（写事务串行化的机制另有单测 `test_db_write_is_serialized_across_threads` 钉着）",
    )


# --------------------------------------------------------------------------
# 前端 / 委托 / 回归
# --------------------------------------------------------------------------


def check_frontend(rep: Report, ctx: Ctx) -> None:
    """P3 的前端那一半：课堂页、记录页、通道与 store（用例逐条跑）。"""
    specs = [
        "src/__tests__/ClassroomView.spec.ts",
        "src/__tests__/ClassroomRecordView.spec.ts",
        "src/__tests__/classroom-socket.spec.ts",
        "src/__tests__/classroom-store.spec.ts",
        "src/__tests__/beat-player.spec.ts",
        "src/__tests__/App.spec.ts",
    ]
    result = subprocess.run(
        [npx(), "vitest", "run", *specs],
        cwd=str(FRONTEND),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = plain((result.stdout or "") + (result.stderr or ""))
    if result.returncode != 0:
        log_path = ctx.work_dir / "vitest-p3.log"
        log_path.write_text(output, encoding="utf-8")
        reason = next((ln.strip() for ln in output.splitlines() if "FAIL" in ln or "Error" in ln), "")
        rep.fail("P3-G2b", "前端：课堂页 / 记录页 / 通道 / store", f"用例未通过：{reason}\n完整输出：{log_path}")
        return

    summary = next((ln.strip() for ln in reversed(output.splitlines()) if "Tests" in ln), "")
    rep.ok(
        "P3-G2b",
        "前端：课堂页 / 记录页 / 通道 / 播放器 / 导航",
        f"六份用例全通过（{summary}）",
    )


def check_delegated(rep: Report, ctx: Ctx) -> None:
    """跑一遍离线用例，逐条记账（B1/C2/C4 与几条代理）。"""
    nodes = [node for _aid, _title, group in DELEGATED for node in group]
    nodes += [node for _aid, _title, group, _why in PROXIED for node in group]
    pytest_verdicts(nodes)

    for aid, title, group in DELEGATED:
        problems = []
        for node in group:
            ok, why = pytest_node_ok(node)
            if not ok:
                problems.append(f"{node}（{why}）")
        # 数的是**真的**跑过多少条用例：一个委托节点常常是整个文件
        # （`test_p3_classroom_ws.py`），写「1 条用例全通过」会让人以为
        # 这个协议只压了一条用例 —— 那是 «1 个节点»，不是 «1 条用例»。
        rep.verdict(aid, title, problems, f"{sum(_cases_passed(n) for n in group)} 条用例全通过")

    for aid, title, group, why in PROXIED:
        pairs = []
        for node in group:
            ok, _ = pytest_node_ok(node)
            pairs.append(f"{node.rsplit('::', 1)[-1]}：{'通过' if ok else '**未通过**'}")
        evidence = "；离线侧（{} 条）—— ".format(len(group)) + "、".join(pairs) if group else ""
        rep.skip(aid, title, f"{why}{'；' + evidence if evidence else ''}")


def check_suites(rep: Report, ctx: Ctx) -> None:
    """P3-G1：P0/P1/P2 的验收保持通过。"""
    suites = {
        "P0": run_pytest("tests/contract/test_p0_api.py"),
        "P1": run_pytest("tests/contract/test_p1_api.py"),
        "P2": run_pytest("tests/contract/test_p2_voice_api.py", "tests/contract/test_p2_voice_ws.py"),
    }
    problems = []
    for name, result in suites.items():
        if result.returncode != 0:
            problems.append(f"{name} 契约测试未通过：{_pytest_tail(result, 6)}")
    rep.verdict(
        "P3-G1",
        "P0/P1/P2 验收全部保持通过",
        problems,
        "；".join(f"{name} {_pytest_summary(result)}" for name, result in suites.items()),
    )


def check_unreachable(rep: Report, ctx: Ctx) -> None:
    """离线跑不到的与要人耳人眼的：如实跳过，并说清卡在哪。"""
    rep.skip(
        "P3-A3b",
        "插话人设的人眼抽检（抽 5 条判定 ≥ 4 条符合林晓=提问/陈默=补充/苏雨=复述）",
        "要人读；离线侧验到的是规则（次数、间隔、说话人来自角色库）与"
        "「插话提到了当前页」（见 E1 那一条的代理）",
    )
    rep.skip(
        "P3-E1b",
        "同学发言相关性的人眼评分（≥ 4 分）",
        "要人读；离线侧的代理是「插话提到了当前页」——脚本按页标题关键词算过一遍",
    )
    rep.skip(
        "P3-E3b",
        "教师答问准确性的人眼评分（≥ 4 分）",
        "要人读；离线侧验到的是答疑闭环（举手 → 点名 → 提问 → 有音频的回答 → 入消息流）",
    )


# --------------------------------------------------------------------------
# 临时库与后端
# --------------------------------------------------------------------------


def prepare_database(ctx: Ctx, port: int) -> tuple[bool, str]:
    """在一台的临时库上跑迁移与种子。返回 (是否成功, 失败原因)。

    **三个实例各一个库**，不是一个库三台服务：单用户会话配额、消息、留档
    都是按库算的，共用一个库的话，「默认配额是 2」这条在别的实例开过课之后
    就再也验不到了（第 2 堂课直接 42901），而那不是被测代码的问题。
    一台服务一个库，本来也是部署的样子。
    """
    env = {**ctx.env, "DATABASE_URL": ctx.db_urls[port]}
    upgrade = subprocess.run(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "db", "upgrade"],
        cwd=str(BACKEND), env=child_env(env),
        capture_output=True, check=False, text=True, encoding="utf-8", errors="replace",
    )
    if upgrade.returncode != 0:
        return False, f"db upgrade 失败：\n{plain((upgrade.stderr or '')[-500:])}"

    seeded = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.seeds import run_seed\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    print(json.dumps(run_seed(), ensure_ascii=False))\n",
        env=env,
    )
    if seeded.returncode != 0:
        return False, f"seed 失败：\n{plain((seeded.stderr or '')[-500:])}"
    return True, ""




def start_server(ctx: Ctx, port: int, log_name: str, env: dict[str, str]):
    log_path = ctx.work_dir / log_name
    ctx.logs[log_name.replace(".log", "")] = log_path
    proc = start(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "run", "--port", str(port)],
        cwd=BACKEND,
        log_path=log_path,
        env=env,
    )
    if not wait_http(f"http://127.0.0.1:{port}/api/health", timeout=90):
        log = log_path.read_text(encoding="utf-8", errors="replace")
        print(f"  {port} 上的后端没起来，日志：\n{plain(log[-1200:])}")
        stop(proc)
        return None
    return proc


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="P3 A/B/C/D/E/F/G 类验收（P3-G2，离线 Mock）")
    parser.add_argument("--keep", action="store_true", help="跑完留下临时库、日志与三个后端进程")
    args = parser.parse_args()

    global API, TRANSITIONS
    API = f"http://127.0.0.1:{MAIN_PORT}/api"

    for port in (MAIN_PORT, PULSE_PORT, NOPUSH_PORT):
        if is_up(f"http://127.0.0.1:{port}/api/health"):
            print(f"端口 {port} 上已经有服务了。这台机器上它可能是别人的 —— 停掉它再跑。")
            return 2

    work_dir = Path(tempfile.mkdtemp(prefix="eduagentx-p3-"))
    audio_dir = work_dir / "assets" / "audio"
    #: 三台服务共用的**音频目录**（合成一次三台都能读 —— 它是文件系统，不是库），
    #: 各自的库由 `_db_url` 按端口分开。
    shared = {"AUDIO_DIR": audio_dir.as_posix()}
    db_urls = {
        port: f"sqlite:///{(work_dir / f'accept-{port}.db').as_posix()}"
        for port in (MAIN_PORT, PULSE_PORT, NOPUSH_PORT)
    }
    ctx = Ctx(
        env={**MAIN_ENV, **shared, "DATABASE_URL": db_urls[MAIN_PORT]},
        work_dir=work_dir,
        audio_dir=audio_dir,
        db_urls=db_urls,
    )

    print("P3 A/B/C/D/E/F/G 类验收开始（三个离线实例，全程不联网）")
    print(f"  主实例   http://127.0.0.1:{MAIN_PORT}/api（离线替身，会话上限 12）")
    print(f"  心跳实例 http://127.0.0.1:{PULSE_PORT}/api（心跳 1s / 判死 4s / 连接上限 2）")
    print(f"  无推送   http://127.0.0.1:{NOPUSH_PORT}/api（CLASSROOM_WS=false）")
    print(f"  临时目录 {work_dir}（三个库 + 音频 + 日志）")
    print()

    report = Report()
    try:
        for port, name, env in (
            (MAIN_PORT, "main.log", ctx.env),
            (PULSE_PORT, "pulse.log", {**PULSE_ENV, **shared}),
            (NOPUSH_PORT, "nopush.log", {**NOPUSH_ENV, **shared}),
        ):
            ok, why = prepare_database(ctx, port)
            if not ok:
                print(f"  临时库没准备好（:{port}）：\n{why}")
                return 2
            proc = start_server(ctx, port, name, {**env, "DATABASE_URL": db_urls[port]})
            if proc is None:
                return 2
            ctx.procs[name.split(".")[0]] = proc

        TRANSITIONS = load_transitions(ctx)
        if not TRANSITIONS:
            print("  读不到课堂状态机（P3-A2 会报失败，其余照跑）")

        _guard(report, "预置示例课", check_seed, ctx)
        _guard(report, "完整课堂", check_class, ctx)
        _guard(report, "课后记录", check_record, ctx)
        _guard(report, "在线与多标签", check_presence, ctx)
        _guard(report, "心跳与连接上限", check_pulse, ctx)
        _guard(report, "关掉推送", check_nopush, ctx)
        _guard(report, "安全", check_security, ctx)
        _guard(report, "并发写", check_data, ctx)
        _guard(report, "前端", check_frontend, ctx)
        _guard(report, "委托用例", check_delegated, ctx)
        _guard(report, "P0/P1/P2 回归", check_suites, ctx)
        _guard(report, "离线跑不到的条目", check_unreachable, ctx)

        passed = sum(1 for row in report.rows if row[2] == "PASS")
        skipped = sum(1 for row in report.rows if row[2] == "SKIP")
        report.ok(
            "P3-G2c",
            "scripts/accept_p3.py 用无头 WS 客户端跑通完整课堂",
            f"以上 {passed} 条在离线替身上通过、{skipped} 条按 §7 的分工记跳过"
            "（要真上游、人耳或 45 分钟压测）；三个实例全程未联网、未读 .env",
        )
    finally:
        failed = any(row[2] == "FAIL" for row in report.rows)
        if failed or args.keep:
            # 补一份全量现场：`_drive` 那次只写了主线那堂课的几条连接，
            # 而 A12/A13/F 是在各自开的临时连接上验的（它们收到的帧同样是线索）。
            _dump_events(ctx)
        if not args.keep:
            print()
            print("  正在关闭三个临时后端…")
            for proc in ctx.procs.values():
                stop(proc)
        if args.keep:
            print(f"\n  三个临时后端还在 :{MAIN_PORT} / :{PULSE_PORT} / :{NOPUSH_PORT}（--keep）")
            print(f"  临时库 {work_dir}")
        elif failed:
            #: 跑砸了就把现场留下（三个库 + 三个日志 + `events.log`）——
            #: 「停在第 6 页」这种症状的原因只在事件流里看得见。
            print(f"  这一趟没全绿，临时目录留着给你查：{work_dir}")
            print(f"    事件流 {work_dir / 'events.log'}　日志 {work_dir / '*.log'}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
