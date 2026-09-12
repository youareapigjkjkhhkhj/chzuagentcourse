"""SSE 事件流（P1 §4.1 / P1-B2 / AGENTS §17）。

这一层要挡的是**「事件其实发了，前端一动不动」**这类故障 —— 它们
不报错、不进日志，只是让用户盯着一个不动的进度环：

- 少了 `X-Accel-Buffering: no`：事件被反向代理攒着，直到缓冲区满
- 少了心跳：代理掐掉「长时间没字节」的连接，前端以为任务卡住了
- 少了 `id:` 行：断线重连只能从头发，或者干脆丢一段进度

所以断言分成「响应头」「帧的形态」「断点续传」「终态收尾」四组。
流是用 `buffered=False` 真读的：那样才验得到「一帧一帧地推」。
"""

from __future__ import annotations

import json
import re
import threading
import time

import pytest

from app.common.identity import OWNER_HEADER
from app.services.courses import store
from app.services.generation import events

pytestmark = pytest.mark.unit

_FRAME = re.compile(r"id: (\d+)\nevent: ([a-z.]+)\ndata: (\{.*\})\n\n")


class StreamReader:
    """在后台线程里读 SSE，免得「读」和「发」在同一个线程里互相等。"""

    def __init__(self, response) -> None:
        self._response = response
        self._chunks: list[str] = []
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        for chunk in self._response.response:
            self._chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))

    @property
    def text(self) -> str:
        return "".join(self._chunks)

    def frames(self) -> list[tuple[int, str, dict]]:
        return [
            (int(seq), name, json.loads(data)) for seq, name, data in _FRAME.findall(self.text)
        ]

    def wait_for(self, needle: str, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if needle in self.text:
                return True
            time.sleep(0.01)
        return False

    def wait_closed(self, timeout: float = 5.0) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()


def _job(app, *, owner_id: str = ""):
    course = store.create_course(title="机器学习入门", topic="机器学习入门", owner_id=owner_id)
    from app.services.generation.pipeline import start_job

    return start_job(course), course


def _stream(client, job_id: str, **kwargs):
    return client.get(
        f"/api/courses/generate/{job_id}/stream", buffered=False, **kwargs
    )


# --- 响应头 ---


def test_the_response_disables_proxy_buffering_and_caching(app, client):
    job, _course = _job(app)

    response = _stream(client, job.id)
    reader = StreamReader(response)
    try:
        assert response.headers["Content-Type"].startswith("text/event-stream")
        assert response.headers["X-Accel-Buffering"] == "no", "代理会攒着不发"
        assert response.headers["Cache-Control"] == "no-cache"
    finally:
        events.emit(job.id, "job.done", {})
        assert reader.wait_closed()


def test_the_stream_starts_with_a_comment_so_the_client_knows_it_is_connected(app, client):
    job, _course = _job(app)

    response = _stream(client, job.id)
    reader = StreamReader(response)
    try:
        assert reader.wait_for(": ok")
    finally:
        events.emit(job.id, "job.canceled", {})
        assert reader.wait_closed()


# --- 帧 ---


def test_history_is_replayed_and_live_frames_keep_coming(app, client):
    """连上之前发生的（重新打开页面）与连上之后发生的，都要看得到。"""
    job, _course = _job(app)
    events.emit(job.id, "job.start", {"jobId": job.id})
    events.emit(job.id, "step.start", {"type": "parse"})

    response = _stream(client, job.id)
    reader = StreamReader(response)
    try:
        assert reader.wait_for("job.start"), "历史事件没有补发"
        assert reader.wait_for("step.start")

        events.emit(job.id, "step.progress", {"type": "write", "percent": 40})
        assert reader.wait_for("step.progress"), "实时事件没有推出来"
    finally:
        events.emit(job.id, "job.done", {})
        assert reader.wait_closed()

    assert [name for _seq, name, _data in reader.frames()] == [
        "job.start",
        "step.start",
        "step.progress",
        "job.done",
    ]


def test_every_frame_carries_a_strictly_increasing_id(app, client):
    """P1-B2：seq 严格递增无重复，前端按它判断「有没有漏帧」。"""
    job, _course = _job(app)
    events.emit(job.id, "job.start", {})
    events.emit(job.id, "step.start", {"type": "parse"})

    response = _stream(client, job.id)
    reader = StreamReader(response)
    try:
        assert reader.wait_for("step.start")
        events.emit(job.id, "step.done", {"type": "parse"})
        assert reader.wait_for("step.done")
    finally:
        events.emit(job.id, "job.done", {})
        assert reader.wait_closed()

    seqs = [seq for seq, _name, _data in reader.frames()]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    assert seqs == [1, 2, 3, 4]


def test_the_payload_is_json_on_one_line(app, client):
    """data 里出现换行会被 SSE 拆成两帧 —— 载荷必须是单行 JSON。"""
    job, _course = _job(app)
    events.emit(job.id, "step.progress", {"detail": {"batches": [{"label": "撰写第 1–6 页"}]}})

    response = _stream(client, job.id)
    reader = StreamReader(response)
    try:
        assert reader.wait_for("step.progress")
    finally:
        events.emit(job.id, "job.done", {})
        assert reader.wait_closed()

    block = reader.text.split("event: step.progress\ndata: ")[1].split("\n\n")[0]
    assert "\n" not in block
    assert json.loads(block)["detail"]["batches"][0]["label"] == "撰写第 1–6 页"


# --- 断点续传 ---


def test_last_event_id_resumes_without_resending_what_the_client_has(app, client):
    job, _course = _job(app)
    for index in range(3):
        events.emit(job.id, "step.progress", {"n": index})

    response = _stream(client, job.id, headers={"Last-Event-ID": "1"})
    reader = StreamReader(response)
    try:
        assert reader.wait_for('{"n":2}')
    finally:
        events.emit(job.id, "job.done", {})
        assert reader.wait_closed()

    assert [seq for seq, _name, _data in reader.frames()] == [2, 3, 4]


def test_the_after_query_parameter_works_too(app, client):
    """脚本与手工排障用 `?after=`，浏览器才带 Last-Event-ID。"""
    job, _course = _job(app)
    events.emit(job.id, "step.start", {})

    response = _stream(client, job.id, query_string={"after": 1})
    reader = StreamReader(response)
    try:
        assert reader.wait_for("job.done") is False  # 还没发生
        events.emit(job.id, "job.done", {})
        assert reader.wait_for("job.done")
    finally:
        assert reader.wait_closed()

    assert [seq for seq, _name, _data in reader.frames()] == [2]


def test_a_garbage_last_event_id_starts_from_the_beginning(app, client):
    job, _course = _job(app)
    events.emit(job.id, "job.start", {})
    events.emit(job.id, "job.done", {})

    response = _stream(client, job.id, headers={"Last-Event-ID": "别猜了"})
    reader = StreamReader(response)

    assert reader.wait_closed()
    assert [name for _seq, name, _data in reader.frames()] == ["job.start", "job.done"]


# --- 心跳与收尾 ---


def test_a_ping_is_sent_while_the_job_is_quiet(app, client):
    """15s 一次是默认值；这里把它压到几十毫秒，验的是「会发」而不是「发得准」。"""
    app.config["SSE_HEARTBEAT"] = 0.05
    job, _course = _job(app)

    response = _stream(client, job.id)
    reader = StreamReader(response)
    try:
        assert reader.wait_for(": ping"), "没有心跳，代理会掐连接"
    finally:
        events.emit(job.id, "job.canceled", {})
        assert reader.wait_closed()


def test_the_stream_ends_at_a_terminal_event(app, client):
    job, _course = _job(app)

    response = _stream(client, job.id)
    reader = StreamReader(response)
    assert reader.wait_for(": ok")

    events.emit(job.id, "job.done", {"courseId": "c1"})
    assert reader.wait_closed(), "终态之后这条流该结束（前端据此 close，不再重连）"

    events.emit(job.id, "step.start", {"type": "late"})
    time.sleep(0.05)
    assert "late" not in reader.text, "收尾之后不该再有帧"


def test_a_finished_job_replays_everything_and_closes(app, client):
    """刷新页面时任务早就跑完了：一次把历史给全，然后关掉。"""
    job, _course = _job(app)
    events.emit(job.id, "job.start", {})
    events.emit(job.id, "job.done", {"courseId": "c1"})

    response = _stream(client, job.id)
    reader = StreamReader(response)

    assert reader.wait_closed()
    assert [name for _seq, name, _data in reader.frames()] == ["job.start", "job.done"]


# --- 一次真实生成的事件序列（P1-B2）---


def test_a_real_generation_streams_the_documented_sequence(app, client):
    """`job.start → step.* → page.ready → job.done`，一条都不少、顺序不乱。

    这里跑的是**真的管线**（只把模型换成桩）：事件从 worker 线程出来，
    经扇出、SSE 路由，落到测试客户端读到的字节上 —— P1-B2 量的是这一整条。
    """
    from app.common import tasks
    from app.services.generation.pipeline import DEFAULT_OPTIONS
    from tests.unit.test_generation_pipeline import StubLLM

    course = store.create_course(title="机器学习入门", topic="机器学习入门", options=DEFAULT_OPTIONS)
    from app.services.generation.pipeline import start_job

    job = start_job(course, options=DEFAULT_OPTIONS)

    response = _stream(client, job.id)
    reader = StreamReader(response)
    try:
        assert tasks.submit_job(job.id, llm=StubLLM()) is True
        assert reader.wait_closed(30), "生成跑完了，流却没结束"
    finally:
        tasks.shutdown_runner(app)

    names = [name for _seq, name, _data in reader.frames()]
    assert names[0] == "job.start"
    assert names[-1] == "job.done"
    assert {"step.start", "step.done", "step.progress", "page.ready"} <= set(names)
    assert names.count("page.ready") == len(store.pages_of(course))


# --- 归属（P1-F3）---


def test_an_unknown_job_is_a_404_envelope(app, client):
    response = _stream(client, "j_不存在")

    assert response.status_code == 404
    body = response.get_json()
    assert body["code"] == 40401
    assert body["message"]


def test_another_users_job_is_indistinguishable_from_a_missing_one(app, client):
    """越权返回 404 而不是 403：403 等于承认「这个 id 存在，只是不给你看」。"""
    from app.extensions import db
    from app.models import User

    other = User(name="别人", role="teacher")
    db.session.add(other)
    db.session.commit()
    job, _course = _job(app, owner_id=other.id)

    response = _stream(client, job.id, headers={OWNER_HEADER: "me"})

    assert response.status_code == 404
    assert response.get_json()["code"] == 40401
