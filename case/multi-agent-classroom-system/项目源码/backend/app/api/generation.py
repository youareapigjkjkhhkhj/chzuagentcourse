"""生成任务接口（P1 §4）。

P1-4 这一步先落地 SSE 一条：`GET /api/courses/generate/{jobId}/stream`。
创建任务、轮询兜底、取消、重试在 P1-5 加进同一个蓝图 —— 它们与这条流共用
「任务归属怎么判」「事件长什么样」两件事，放在一起才不会各写一套。

SSE 的四条约定（AGENTS §17），每条都对应一种「前端看到进度不动」的故障：

1. **响应头**：`X-Accel-Buffering: no` + `Cache-Control: no-cache`。
   中间的反向代理（Nginx 默认）会缓冲响应直到缓冲区满 —— 没有这两个头，
   事件其实一直在发，只是被代理攒着，前端看到的是一条不动的进度条。
2. **心跳**：15s 一次 `: ping`。代理还会掐掉「长时间没有字节」的连接，
   心跳就是让它知道这条连接还活着。
3. **单调 seq + `id:` 行**：每帧带上库里那个 seq。断线重连时浏览器会带
   `Last-Event-ID` 回来，我们据此补发 —— 不补发的话，断线期间那几页的状态
   在前端就永远丢了（AGENTS §4.3：服务端是唯一状态源）。
4. **终态即收尾**：`job.done/failed/canceled` 之后不再有帧，生成器直接返回。
   浏览器会自动重连（EventSource 的行为），所以前端收到终态要主动 close ——
   不 close 就会看到它一遍遍重放历史。
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from flask import Blueprint, Response, current_app, request

from app.api import json_body
from app.common import tasks
from app.common.errors import NotFoundError, StateError
from app.common.identity import current_owner_id, owned_by
from app.common.response import ok
from app.extensions import db
from app.models import GenJob
from app.services import audit
from app.services.courses import library, store
from app.services.generation import events, intake, pipeline, timeline
from app.services.usage import budget

bp = Blueprint("generation", __name__, url_prefix="/api")

#: SSE 响应头，见模块 docstring 第 1、2 条。
SSE_HEADERS = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    # 老代理见不得没有 Content-Length 的响应，得明说这条连接是长连接
    "Connection": "keep-alive",
}

#: 任务终态事件。收到它们之后这条流就该结束了。
TERMINAL_EVENTS = frozenset({"job.done", "job.failed", "job.canceled"})


@bp.get("/courses/generate/<job_id>/stream")
def stream_generation(job_id: str):
    """订阅一次生成的事件流。

    请求示例：
        GET /api/courses/generate/j_01H.../stream
        GET /api/courses/generate/j_01H.../stream   （带 Last-Event-ID: 12 断点续传）

    响应是 SSE：`id: <seq>` / `event: <名字>` / `data: <JSON>`，
    事件名与载荷见 §4.1。任务不存在或不属于当前用户时返回 404 信封。
    """
    job = _job_or_404(job_id)
    heartbeat = float(current_app.config.get("SSE_HEARTBEAT") or 15.0)
    after = _resume_from(job_id)
    # 生成器在请求上下文之外执行（Flask 在返回响应时就弹了上下文），
    # 所以这里先把 app 的真对象抓出来，由生成器自己推上下文。
    from app.common.context import real_app

    app = real_app()
    return Response(_stream(app, job.id, after=after, heartbeat=heartbeat), headers=SSE_HEADERS)


# --- 创建、轮询、取消、重试（P1 §4 / P1-B1）---


@bp.post("/courses/generate")
def create_generation():
    """创建一门课并开始生成，**立刻**返回（P1-B1：< 500ms）。

    请求示例：
        POST /api/courses/generate
        {"topic": "机器学习入门", "mode": "lecture", "pageCount": 12}

    这里只做两件快事：建课程行 + 建任务行（都是本地写库），然后交给后台线程。
    模型调用一步都不在这里发生 —— 12 页生成要一两分钟，同步做就是让用户
    对着一个转圈的页面等两分钟，还会把请求超时算在生成头上。

    唯一一件**会慢**的事是预算检查，但它花的是本地库的一次聚合查询
    （不像模型调用要等上游），并且必须在建课之前做：超了预算还先把课建出来，
    用户的课程列表里就会多出一门永远停在 `generating` 的课 —— 那门课的
    每一次生成都会再被拒一次，而它自己不会消失。
    """
    body = json_body()
    topic = intake.clean_topic(body.get("topic"))
    options = intake.parse_options(body)
    owner_id = current_owner_id()
    budget.ensure_allowed(course_id="", owner_id=owner_id)

    # 课程先落库（状态 generating）：生成过程中刷新页面要能看到它，
    # 而不是「任务在跑，但课程列表里什么都没有」。
    course = store.create_course(title=topic, topic=topic, options=options, owner_id=owner_id)
    job = pipeline.start_job(course, options=options, owner_id=owner_id)
    tasks.submit_job(job.id)
    # 建课是这一阶段最要紧的一次写：它同时决定了「花了多少钱」（预算是按课程算的）
    # 与「库里多了什么」。记 id、标题与页数 —— 后两个是用户自己填的参数，
    # 不是提示词正文（§19 拦的是后者）。
    audit.record(
        audit.ACTION_COURSE_CREATE,
        target=f"course:{course.id}",
        detail={"title": topic, "jobId": job.id, "pageCount": options.get("pageCount")},
    )
    return ok(
        {
            "courseId": course.id,
            "jobId": job.id,
            "status": job.status,
            "stream": f"/api/courses/generate/{job.id}/stream",
        }
    )


@bp.get("/jobs/<job_id>")
def get_job(job_id: str):
    """轮询兜底：当前步骤、进度、各步耗时与错误（§4）。

    请求示例：
        GET /api/jobs/j_01H…

    SSE 之外留这条路，是因为「流断了」和「任务停了」在浏览器里长得一样：
    前端重连两次还接不上时，就靠这个接口把状态问清楚。响应里的
    `currentStep` 是正在跑的那一步，`failedSteps` / `retryable` 供 P1-A8
    的重试按钮判断该不该亮。
    """
    job = _job_or_404(job_id)
    return ok(library.step_payload(job))


@bp.get("/jobs/<job_id>/timeline")
def get_job_timeline(job_id: str):
    """任务时间线：每步耗时 / 重试次数 / token / 失败原因与上游错误码（P5-F5-10）。

    请求示例：
        GET /api/jobs/j_01H…/timeline

    与上面那条（`GET /api/jobs/{jobId}`）是一对：那条答「现在到哪了」，是轮询用的、
    要短；这条答「它是怎么走到这儿的」，是工作台任务卡**展开**时用的，要全。

    每一步都带着账本那份（`calls`：几次调用、几次失败、多少 token、多少钱），
    按 `step_id` 归到步骤上 —— 于是「钱花在哪一步」不必再猜。
    金额只算 LLM（`model_calls`），语音按量计费、不进这张表，见响应里的 `note`。
    """
    job = _job_or_404(job_id)
    return ok(timeline.build(job))


@bp.post("/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    """取消生成（P1-A9：3 秒内前端看到终态，已生成的页面保留）。

    请求示例：
        POST /api/jobs/j_01H…/cancel

    已经结束的任务再取消不报错，照原样返回它的最终状态 —— 用户连点两下
    不该收到一个错误提示。任务停在确认点（没有工作线程）时，终态事件
    由这里补发，否则订阅着那条流的页面会一直等一个不会来的结局。
    """
    job = _job_or_404(job_id)
    if job.status in {"done", "canceled"}:
        # 已经停了就如实返回，不报错：用户连点两下「取消」不该收到一个错误
        return ok(library.step_payload(job))

    running = tasks.get_runner().is_running(job.id)
    pipeline.request_cancel(job.id)
    db.session.refresh(job)
    if not running:
        # 没有工作线程会来收这个尾（排队中被取消、停在确认点被放弃的任务），
        # 终态事件得由这里补上 —— 否则订阅着那条流的页面会一直等一个不会来的结局。
        events.emit(job.id, "job.canceled", {"jobId": job.id, "progress": job.progress})
    return ok(library.step_payload(job))


@bp.post("/jobs/<job_id>/steps/<step_id>/retry")
def retry_job_step(job_id: str, step_id: str):
    """重试失败的步骤（P1-A8）。重跑该步及其之后的步骤，已有的页面不重写。

    请求示例：
        POST /api/jobs/j_01H…/steps/s_01H…/retry

    只有 `failed` 的步骤能重试（其余 40902）。重试是**接着跑**而不是从头再来：
    已经写好的页面留在库里，重跑只补没写完的部分 —— 否则一次网络抖动就要
    把整门课重新生成一遍，那是在替用户烧钱。
    """
    job = _job_or_404(job_id)
    # 走 `steps_of`（查库）而不是 `job.steps` 关系：后台线程正在改这些行，
    # 关系读的是会话缓存，缓存里的那份可能还是重试前的老状态。
    step = next((row for row in pipeline.steps_of(job) if row.id == step_id), None)
    if step is None:
        raise NotFoundError("生成步骤不存在")
    if step.status != "failed":
        raise StateError("只有失败的步骤才能重试")

    if not tasks.submit_retry(job.id, step.id):
        raise StateError("这个任务正在运行中，等它停下来再重试")
    return ok({"jobId": job.id, "stepId": step.id, "status": "queued"})


@bp.post("/jobs/<job_id>/resume")
def resume_job(job_id: str):
    """断点续跑：从第一个没做完的步骤接着跑（P5-F5-9 / P5-A9）。

    请求示例：
        POST /api/jobs/j_01H…/resume

    「服务重启过」与「用户自己取消过」是同一个形状：页面有的写好了、有的没有，
    而**没有任何线程在跑**。两者都从这里接着来，已经写好的页面一页都不会重写
    （页级幂等，见 `pipeline.resume_job`）。

    只有这两种任务能续：跑完的没什么可续，停在大纲确认等的也不是这个按钮
    （那是用户自己的一步审查，走 `POST /api/courses/{id}/outline`），
    正在跑的再点一次则是 40902 —— 两个线程抢同一批页面会把页码与版本号写乱。
    """
    _job_or_404(job_id)
    # 「正在跑」要**排在改状态前面**判：状态一旦被摆成 queued，而任务又已经在跑了，
    # 那两次改的是同一批步骤行（一个在收尾、一个在放回 wait），页码与版本号会乱。
    # 这一判与下面 `submit_resume` 的返回值是两个不同的时窗，两道都留着。
    if job_id in tasks.active_jobs():
        raise StateError("这个任务正在运行中，等它停下来再继续")

    # 状态在**请求线程**里改（见 `pipeline.prepare_resume`）：此前它在后台线程里改，
    # 于是接口返回的、以及紧接着查到的那一份，都还是旧的终态
    # （`status: failed, resumable: true`）—— 用户点了「继续生成」，界面看起来没反应。
    job = pipeline.prepare_resume(job_id)
    if not tasks.submit_resume(job_id):
        raise StateError("这个任务正在运行中，等它停下来再继续")
    # 后台线程可能已经把状态推走了（它一提交就可能开始跑），重新读一次再回 ——
    # 前端据此渲染任务卡，读一份比刚写进去的那份更新的，总不会错。
    db.session.refresh(job)
    return ok(library.step_payload(job))


# --- 帧 ---


def _stream(app, job_id: str, *, after: int = 0, heartbeat: float = 15.0) -> Iterator[str]:
    """补发历史 → 订阅新帧，直到任务进入终态。"""
    yield ": ok\n\n"  # 先发一帧注释，让前端立刻知道连接建立成功
    with app.app_context():
        # 先订阅再补发：中间这一小段窗口里发出的事件会落进队列，
        # 补发时按 seq 去重（已经发过的不再发），一帧都不会丢也不会重。
        channel = events.subscribe(job_id)
        try:
            for frame in events.replay(job_id, after):
                yield _format(frame)
                after = int(frame["seq"])
                if frame["event"] in TERMINAL_EVENTS:
                    return

            for frame in events.iter_frames(channel, timeout=heartbeat, stopping=lambda: False):
                if frame is None:
                    yield ": ping\n\n"
                    continue
                if int(frame.get("seq") or 0) <= after:
                    continue
                yield _format(frame)
                after = int(frame["seq"])
                if frame["event"] in TERMINAL_EVENTS:
                    return
        finally:
            events.unsubscribe(job_id, channel)
            db.session.remove()


def _format(frame: dict[str, Any]) -> str:
    """一帧落成 SSE 文本。data 必须是**单行** —— 换行会把它切成两帧。"""
    data = json.dumps(frame.get("payload") or {}, ensure_ascii=False, separators=(",", ":"))
    return f"id: {frame.get('seq')}\nevent: {frame.get('event')}\ndata: {data}\n\n"


def _resume_from(job_id: str) -> int:
    """断点续传的起点：`Last-Event-ID` 头优先，其次 `?after=` 查询参数。

    浏览器 EventSource 自动带前者；后者给脚本与手工排障用。
    """
    raw = (request.headers.get("Last-Event-ID") or request.args.get("after") or "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _job_or_404(job_id: str) -> GenJob:
    """取任务并判归属。不存在与越权都返回 404（AGENTS §4.1）。"""
    job = db.session.get(GenJob, job_id)
    if job is None or not owned_by(job, current_owner_id()):
        raise NotFoundError("生成任务不存在")
    return job


__all__ = ["TERMINAL_EVENTS", "bp"]
