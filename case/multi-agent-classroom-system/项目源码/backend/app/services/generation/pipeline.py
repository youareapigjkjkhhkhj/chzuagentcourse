"""三段式生成管线（P1 §3.1 / §4.1 / P1-11）。

    parse ──► outline ──► write ──► quiz ──► tts(P2) ──► assemble

整条管线是**声明式**的：`PIPELINE` 那张表就是全部事实 —— 有哪些步骤、
各占多少权重、哪一步之后可以停、哪一步可以跳过。执行器不认识任何一步的
具体业务，加一步就加一行。

五条贯穿全篇的约定：

1. **数据库是唯一的状态载体**。步骤之间不传内存对象：写页时从 `course_pages`
   取页行，出讨论问题时从 `course_pages` 取要点。所以「暂停 → 用户删了一页 →
   继续」「某一步失败 → 重试」都不需要额外的恢复逻辑，重跑一遍就从库里读到了
   新的事实（AGENTS §4.3）。
2. **单步失败不中断整课**（P1-F1 / A8）。失败的页标记 `failed`、失败的步标记
   `failed`，剩下的步骤照跑；重试只重跑失败的那部分 —— 靠的是写页前的幂等检查。
3. **每页写完即落库**（`course_pages` + `course_page_versions`）。整门课是一个
   几十次模型调用、几分钟的过程，攒到最后一起写等于把这几分钟的不确定性
   全压在最后一步。
4. **权重累加即总进度**，且只增不减。步骤内进度写在 `gen_steps.detail_json.percent`
   里，与步骤状态一起构成唯一的进度来源。
5. **可取消**：取消在页边界生效（Python 杀不掉一个正在跑的线程，
   硬掐只会让连接和 token 都白花）。用户**立刻**看到「已取消」——
   状态由请求线程改、不由工作线程改，所以不必等那一页跑完（P1-A9）。
"""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from flask import current_app

from app.common.context import real_app
from app.common.dbw import db_write
from app.common.errors import AppError, NotFoundError, StateError
from app.common.logging import get_logger
from app.common.timeutil import elapsed_ms, parse_iso, utcnow_iso
from app.extensions import db
from app.models import Course, CoursePage, GenJob, GenStep, ModelCall
from app.providers.base import LLMProvider
from app.services.courses import store
from app.services.generation import events, prompts, sourcing
from app.services.generation.filter import (
    OUTCOME_BLOCKED,
    OUTCOME_REGENERATED,
    record_hit,
    scan_page,
)
from app.services.generation.llm import call_json, call_page, clip_feedback, error_code_of
from app.services.generation.schema import (
    SchemaInvalid,
    parse_discussion,
    parse_outline,
    parse_profile,
    schema_for_discussion,
    schema_for_outline,
    schema_for_profile,
)
from app.services.materials import citations
from app.services.usage import budget

logger = get_logger("app.generation.pipeline")


# --- 声明 ---


@dataclass(frozen=True)
class Step:
    """一个步骤的全部声明。执行器只读这些字段。"""

    type: str
    title: str
    #: 进度权重。全表相加必须是 100（§6）。它是「这一步大约占多少时间」的估计：
    #: 写 12 页内容当然比解析一句需求慢得多，进度条不该对两者一视同仁。
    weight: int
    #: 这一步干活的函数。声明表直接持有函数对象，执行器因此没有任何
    #: 「按类型分派」的代码 —— 加一步就是加一行。
    fn: Callable[["StepContext"], None]
    #: 步内并发。只有写页用得上。
    parallel: int = 1
    #: 这一步之后是否可能停下来等用户（实际是否停由 options.confirmOutline 决定，P1-A3）。
    pause_after: bool = False
    #: 可选步骤：P1 里没有实现也照常走完，标成 skipped 而不是 failed。
    optional: bool = False


#: 排期与内容参数。与 settings_service.DEFAULT_GENERATION 同名同义 ——
#: 接口层会把用户设置合并进来（P1-5）。`concurrency` 不在这里：
#: 它由 GEN_CONCURRENCY 决定，写进任务里是为了让「这次跑的几路并发」可回溯。
DEFAULT_OPTIONS: dict[str, Any] = {
    "mode": "lecture",
    "pageCount": 12,
    "classmateCount": 3,
    "scriptDetail": "detailed",
    "quizPerChapter": True,
    "confirmOutline": False,
}

#: 写页的批次大小。原型上 write 那一行下面是两行子步骤，
#: 12 页按 6 页一批正好是「第 1–6 页 / 第 7–12 页」（技术方案 §4.1）。
BATCH_SIZE = 6

_SENSITIVE_RETRY = (
    "这一版里出现了不适合课堂的内容（{words}）。请重新输出**完整的 JSON**，"
    "换一种说法讲同一件事；如果这个内容本身不适合课堂，就换一个例子。"
)

_cancel_flags: set[str] = set()
_cancel_lock = threading.Lock()


class PipelineCancelled(Exception):
    """任务被用户取消 —— 走「保留已生成的页面并收尾」而不是「失败」。"""


class StepSkipped(Exception):
    """这一步这次不跑（可选步骤）。带一个给人看的理由。"""


@dataclass(frozen=True)
class PageFailure:
    """一页没写成：给人看的原因 + 给机器分组的归类码（P5-F5-10）。

    两者分开是有用的：`message` 是「第 3 页生成失败：模型输出不符合页面要求…」，
    用户读它；`code` 是 `rate_limit` / `timeout` / `schema_invalid`，
    前端读它来决定提示语是「等一会儿再试」还是「去设置页看看 Key」。
    只有一句话的失败原因，界面就只能对着一堆不同的故障说同一句「失败了」。
    """

    message: str
    #: 缺省是「模型没写好」，也就是这一页**被尝试过**、只是没成。
    code: str = "page_failed"


# --- 对外入口 ---


def concurrency() -> int:
    return max(1, int(current_app.config.get("GEN_CONCURRENCY") or 3))


def max_page_count() -> int:
    return int(current_app.config.get("MAX_PAGE_COUNT") or 20)


def weight_of(step_type: str) -> int:
    return WEIGHTS.get(step_type, 0)


def _declaration(step_type: str) -> Step:
    """步骤行（数据库）→ 它的声明。步骤行只有 type/title，行为在声明表里。

    找不到就当场造一个「什么都不做」的声明：数据库里多出一个我们不认识的步骤
    （降级部署、手工插的行）不该让整个任务崩掉，正常跑完剩下的就行。
    """
    for step in PIPELINE:
        if step.type == step_type:
            return step
    return Step(step_type, step_type, 0, _noop)


def _noop(_ctx: StepContext) -> None:
    return None


def steps_of(job: GenJob) -> list[GenStep]:
    """任务的步骤行，按 seq 排序。

    走查询而不是 `job.steps` 关系：关系是绑定在会话上的缓存，而取消是**另一个
    线程**改的状态（P1-A9），那边提交的改动不会让这边的缓存失效。
    任务的状态机每一步都要求「读到的是库里那份」。
    """
    return list(GenStep.query.filter_by(job_id=job.id).order_by(GenStep.seq).all())


def step_of(job: GenJob, step_type: str) -> GenStep | None:
    return next((step for step in steps_of(job) if step.type == step_type), None)


def job_progress(job: GenJob) -> int:
    """总进度 = Σ(已完成步骤权重) + 当前步骤权重 × 步骤内进度（§6）。

    skipped 与 done 一样算完成：可选步骤跳过不该让整门课永远到不了 100%。
    """
    total = 0
    for step in steps_of(job):
        weight = weight_of(step.type)
        if step.status in {"done", "skipped"}:
            total += weight
        elif step.status == "running":
            total += int(weight * percent_of(step) / 100)
    return max(0, min(100, total))


def percent_of(step: GenStep) -> int:
    return int((step.detail or {}).get("percent") or 0)


def start_job(
    course: Course, *, options: Mapping[str, Any] | None = None, owner_id: str = ""
) -> GenJob:
    """建任务并铺好步骤行。**不做任何模型调用** —— 接口层要立刻返回（P1-B1）。

    建行之前先过一次预算（P5-F5-8）：超了直接 `StateError`，**一行都不落库**。
    建了任务再拒的话，那门课会永远停在 `queued`，而用户看到的是一次「点了没反应」——
    钱没花出去，却多出一条再也跑不完的任务。

    这里查的是**三个作用域全查**（含单课）：接口层在建课之前只能查全局与日预算
    （那时还没有课程 id），单课预算只有到这里才知道该查谁。
    """
    budget.ensure_allowed(course_id=course.id, owner_id=owner_id or course.owner_id or "")

    merged = {**DEFAULT_OPTIONS, **dict(options or {})}
    merged.setdefault("topic", course.topic or course.title)
    merged.setdefault("concurrency", concurrency())

    job = GenJob(
        course_id=course.id,
        owner_id=owner_id or course.owner_id or None,
        status="queued",
        progress=0,
    )
    job.options = merged

    def _work() -> GenJob:
        db.session.add(job)
        db.session.flush()
        for index, step in enumerate(PIPELINE, start=1):
            row = GenStep(job_id=job.id, seq=index, type=step.type, title=step.title, status="wait")
            row.detail = {}
            db.session.add(row)
        db.session.flush()
        return job

    return db_write(_work)


def run_job(job_id: str, *, llm: LLMProvider | None = None, resume: bool = False) -> GenJob:
    """把任务跑到「停下来」为止：跑完 / 暂停 / 失败 / 被取消。

    同步执行 —— 放到线程里是 P1-4 的事。这样它就能被测试直接驱动，
    也不必为了「怎么等一个后台线程」在断言里加 sleep。
    """
    job = db.session.get(GenJob, job_id)
    if job is None:
        raise NotFoundError(f"生成任务 {job_id} 不存在")
    # 跑完的、取消了的，以及停在确认点等用户的，都不是这一次要动的
    if job.status in {"done", "canceled"} or (job.status == "paused" and not resume):
        return job

    course = db.session.get(Course, job.course_id)
    if course is None:
        raise NotFoundError(f"生成任务 {job_id} 对应的课程不存在")

    # 子线程要自己推上下文，所以先拿到 app 的真对象（代理出了线程就失效）
    app = real_app()
    provider = llm or _provider()
    options = {**DEFAULT_OPTIONS, **(job.options or {})}
    owner_id = job.owner_id or ""

    if events.last_seq(job.id) == 0:
        events.emit(job.id, "job.start", {"jobId": job.id, "courseId": course.id, "steps": _step_plan(job)})

    failed = False
    for step in steps_of(job):
        if step.status in {"done", "skipped"}:
            continue
        if is_cancel_requested(job.id) or job.status == "canceled":
            break
        if step.status == "failed":
            step.status = "wait"
            step.error = None

        ctx = StepContext(
            app=app, job=job, course=course, step=step, decl=_declaration(step.type),
            provider=provider, options=options, owner_id=owner_id,
        )
        outcome = _run_step(ctx)
        if outcome == "failed":
            failed = True
        elif outcome == "canceled":
            break

        if ctx.decl.pause_after and options.get("confirmOutline"):
            return _pause_job(job, course)

    if job.status == "canceled" or is_cancel_requested(job.id):
        _finish_canceled(job, course)
        return job
    return _finish_job(job, course, failed=failed)


def _pause_job(job: GenJob, course: Course) -> GenJob:
    """停在大纲确认点：任务 paused，课程与页面留在原地等用户点「继续」（P1-A3）。"""
    _touch_job(job, status="paused")
    events.emit(job.id, "job.paused", {
        "jobId": job.id, "courseId": course.id,
        "outline": store.outline_tree(course), "progress": job.progress,
    })
    return job


def _finish_job(job: GenJob, course: Course, *, failed: bool) -> GenJob:
    """收尾：结算 token/耗时，给任务定终态。

    有页面失败时任务整体算 failed —— 但课程可能仍是 ready（**部分成功**：
    12 页里 11 页可用，用户能直接上课，只是有一页要重试）。这两件事不矛盾：
    任务说的是「这次跑完了没有」，课程说的是「这门课能不能用」。
    """
    job.total_tokens = _ledger_tokens(job.id)
    job.total_ms = _elapsed_since(job.created_at)
    if failed:
        _touch_job(job, status="failed", error=_first_error(job))
        events.emit(job.id, "job.failed", {
            "jobId": job.id, "error": job.error, "progress": job.progress,
        })
        return job
    _touch_job(job, status="done", progress=100, error="")
    events.emit(job.id, "job.done", {
        "jobId": job.id, "courseId": course.id,
        "pageCount": course.page_count, "progress": 100,
    })
    return job


def retry_step(job_id: str, step_id: str, *, llm: LLMProvider | None = None) -> GenJob:
    """重跑一个失败的步骤（P1-A8）。

    该步**及其之后**的步骤都回到 wait：写页补出来的内容会进 dsl，
    出讨论问题时读的就是那份 dsl —— 后面的步骤必须重算一次才对得上。
    """
    job = db.session.get(GenJob, job_id)
    if job is None:
        raise NotFoundError(f"生成任务 {job_id} 不存在")
    target = next((step for step in steps_of(job) if step.id == step_id), None)
    if target is None:
        raise NotFoundError(f"任务 {job_id} 里没有步骤 {step_id}")

    def _reset() -> None:
        for step in steps_of(job):
            if step.seq >= target.seq:
                step.status = "wait"
                step.error = None
                step.started_at = None
                step.finished_at = None

    db_write(_reset)
    _touch_job(job, status="queued", error="")
    with _cancel_lock:
        _cancel_flags.discard(job_id)
    return run_job(job_id, llm=llm, resume=True)


def prepare_resume(job_id: str) -> GenJob:
    """把任务摆回「可以接着跑」的样子，**不跑**。幂等。

    从第一个**没做完**的步骤（见 `_is_finished`）起，把 `failed` 与被取消打断的
    `skipped` 放回 `wait`；它前面的步骤一行都不动 —— 把已经写好的页重跑一遍，
    是在替用户烧第二次钱。

    单拎出来是因为它得在**请求线程**里做完（见 `POST /jobs/{id}/resume`）：
    状态改在后台线程里的话，接口返回给用户的还是那个旧的终态
    （`status: failed, resumable: true`），界面照着它渲染，看起来像没点上；
    紧接着的那次状态查询也会读到旧值 —— 前端与验收脚本都是这么问的。
    真正花时间的是后面的 `run_job`，那一半才该在后台。
    """
    job = db.session.get(GenJob, job_id)
    if job is None:
        raise NotFoundError(f"生成任务 {job_id} 不存在")
    if job.status in {"done", "paused"}:
        # done：没有要跑的了；paused：那是在等用户确认大纲，不该被这里悄悄跳过
        # （用户自己的那一步审查，只有他自己能点掉，见 `POST /courses/{id}/outline`）。
        raise StateError(_nothing_to_resume(job))

    steps = steps_of(job)
    first = next((step for step in steps if not _is_finished(step)), None)
    if first is not None:
        def _reset() -> None:
            for step in steps:
                if step.seq < first.seq:
                    continue
                if step.status in {"failed", "skipped"}:
                    step.status = "wait"
                    step.error = None
                    step.error_code = ""
                    # 「这次不适用于你」与「你被取消了」都写成 skipped，
                    # 但只有后者要重跑（见 `_is_finished`）。标记要一起摘掉，
                    # 否则它重跑完还是带着一个「已取消」的旧详情。
                    detail = dict(step.detail or {})
                    if detail.pop("canceled", None):
                        step.detail = detail

        db_write(_reset)

    course = db.session.get(Course, job.course_id)
    if course is not None:
        # 课程回到 generating：任务又要跑起来了，课程列表里那条「失败」得跟着变，
        # 否则用户在列表里看到的是红的、点进去却在转圈。跑完（或再被取消）时
        # 由 assemble / _settle_cancellation 改成终态。
        _touch_course(course, status="generating")
    _touch_job(job, status="queued", error="")
    with _cancel_lock:
        _cancel_flags.discard(job_id)
    return job


def resume_job(job_id: str, *, llm: LLMProvider | None = None) -> GenJob:
    """断点续跑：从**第一个没做完的步骤**接着跑（P5-F5-9 / P5-A9）。

    与 `retry_step` 的区别是「谁说了算」：重试是用户指着某一步说「就它」，
    续跑是对着整个任务说「接着来」。

    三道保险，缺一不可：

    1. `prepare_resume`：从第一个没做完的步骤起，把 `failed` 与被取消打断的
       `skipped` 放回 `wait`；它前面的步骤一行都不动。
    2. `run_job`：它本来就跳过 `done`/`skipped` 的步骤。
    3. `_write_one`：页面级的幂等检查（`status == "ready"` 就不重写）。

    第 3 条才是 P5-A9 真正要验的那条 —— 「前 6 页未重复调用 LLM」量的是
    `model_calls` 有没有新增，而前两条只保证我们不**主动**去写那 6 页。
    三道都在，是因为它们在不同的线程里跑（前两条在请求线程、第 3 条在写页的子线程），
    谁也替不了谁。

    取消过的任务也能续（`canceled`）：用户取消的意思是「别再花钱了」，
    不是「把已经买到的扔掉」—— 页面一页没删，课程回到 draft，接着写正是他想要的。
    """
    prepare_resume(job_id)
    return run_job(job_id, llm=llm, resume=True)


def _is_finished(step: GenStep) -> bool:
    """这一步是不是「不用再跑了」。

    `skipped` 有**两种**来源，在这里必须分开 —— 混为一谈的后果很具体：

    - **可选步骤这次不适用**（没配音色 → tts 跳过）：正常收场，别再跑一遍；
    - **取消打断的半途收手**（`detail.canceled`）：它没做完，续跑要接着做。

    看成一个的话，续跑会跳过那个被取消的 write，直接从 quiz 接着往下走 ——
    最后交出一门少了最后几页、却显示「已完成」的课。这是最难发现的一类错：
    每一处状态都是对的，只有内容少了几页。
    """
    if step.status == "done":
        return True
    return step.status == "skipped" and not (step.detail or {}).get("canceled")


def _nothing_to_resume(job: GenJob) -> str:
    if job.status == "paused":
        return "任务停在大纲确认，请先确认大纲"
    return "这个任务已经生成完成，没有要接着跑的部分"


def request_cancel(job_id: str) -> GenJob | None:
    """请求取消。状态**在这里**就改掉，不等工作线程（P1-A9：3 秒内）。

    工作线程随后在页边界收手：已生成并落库的页面照旧保留，课程回到 draft。
    """
    job = db.session.get(GenJob, job_id)
    if job is None:
        raise NotFoundError(f"生成任务 {job_id} 不存在")
    if job.status in {"done", "canceled"}:
        return job

    with _cancel_lock:
        _cancel_flags.add(job_id)
    course = db.session.get(Course, job.course_id)
    _settle_cancellation(job, course)
    return job


def is_cancel_requested(job_id: str) -> bool:
    with _cancel_lock:
        return job_id in _cancel_flags


def clear_cancel_flags() -> None:
    """测试之间复位（真实进程里没有第二个用户会来清这个集合）。"""
    with _cancel_lock:
        _cancel_flags.clear()


# --- 执行 ---


@dataclass
class StepContext:
    """一步的执行上下文。步骤函数只通过它与外界打交道。"""

    app: Any
    job: GenJob
    course: Course
    step: GenStep
    decl: Step
    provider: LLMProvider
    options: Mapping[str, Any]
    owner_id: str
    #: 非空表示这一步没做完，但**后面的步骤照跑**（P1-F1：单步失败不中断整课）。
    failure: str = ""
    #: `failure` 的归类码（P5-F5-10）。步骤函数在填 `failure` 时顺手填它；
    #: 不填就按「内部错误」记 —— 见 `_run_step` 里那两处兜底。
    failure_code: str = ""
    tokens: int = 0
    model: str = ""
    model_name: str = ""
    detail: dict = field(default_factory=dict)
    _percent: int = 0

    @property
    def topic(self) -> str:
        return str(self.options.get("topic") or self.course.topic or self.course.title)

    @property
    def job_id(self) -> str:
        return self.job.id

    def stop(self) -> bool:
        return is_cancel_requested(self.job_id)

    def count(self, tokens: int, model: str = "") -> None:
        self.tokens += int(tokens or 0)
        if model:
            self.model_name = model
            self.model = model

    def progress(self, percent: int, detail: Mapping[str, Any] | None = None) -> None:
        self._percent = max(self._percent, 0, min(100, int(percent)))
        if detail:
            self.detail.update(detail)
        payload = {**self.detail, "percent": self._percent}
        _touch_step(self.step, detail=payload)
        _touch_job(self.job)
        events.emit(self.job_id, "step.progress", {
            "stepId": self.step.id, "type": self.step.type, "percent": self._percent,
            "detail": self.detail, "progress": self.job.progress,
        })


def _run_step(ctx: StepContext) -> str:
    step = ctx.step
    # attempts 在这里 +1，也就是「这一步开始跑了第几次」（P5-F5-10）。
    # 只加不清零：重试与断点续跑都会再进一次这里，而「跑过三次才成」
    # 正是用户去查上游的那个信号 —— 清零就把它抹平了。
    run_no = int(step.attempts or 0) + 1
    _touch_step(step, status="running", started_at=utcnow_iso(), error=None, error_code="",
                attempts=run_no, detail={"percent": 0})
    _touch_job(ctx.job)
    events.emit(ctx.job_id, "step.start", {
        "stepId": step.id, "type": step.type, "title": step.title,
        "attempt": run_no, "progress": ctx.job.progress,
    })
    started = perf_counter()

    try:
        ctx.decl.fn(ctx)
    except PipelineCancelled:
        _touch_step(step, status="skipped", finished_at=utcnow_iso(), detail={**ctx.detail, "canceled": True})
        return "canceled"
    except StepSkipped as exc:
        # 跳过不是失败，**不记 error_code** —— 它在时间线上是灰的，不是红的
        _touch_step(step, status="skipped", finished_at=utcnow_iso(),
                    duration_ms=_ms(started), detail={"reason": str(exc)})
        events.emit(ctx.job_id, "step.done", {
            "stepId": step.id, "type": step.type, "skipped": True, "detail": {"reason": str(exc)},
            "progress": _touch_job(ctx.job).progress,
        })
        return "skipped"
    except Exception as exc:  # 任何异常都不该让整课崩掉（P1-F1）
        message = _error_text(exc)
        code = error_code_of(exc)
        _touch_step(step, status="failed", error=message, error_code=code,
                    finished_at=utcnow_iso(), duration_ms=_ms(started))
        # 栈只进 DEBUG 日志、且只打位置不打局部变量：局部变量里躺着提示词与
        # 模型输出，那是 AGENTS §19 明令不入日志的东西。排障时打开 DEBUG 就够定位了。
        logger.warning("步骤 %s 失败（job=%s code=%s）：%s", step.type, ctx.job_id, code, message)
        logger.debug("步骤 %s 的异常栈", step.type, exc_info=True)
        events.emit(ctx.job_id, "step.failed", {
            "stepId": step.id, "type": step.type, "error": message, "errorCode": code,
            "attempts": run_no, "progress": _touch_job(ctx.job).progress,
        })
        return "failed"

    status = "failed" if ctx.failure else "done"
    # 步骤函数填了 failure 却没填归类码时兜一个：时间线上宁可显示一个笼统的红，
    # 也不要因为缺码而在前端渲染出空白。空串只留给「成功」。
    code = (ctx.failure_code or "step_failed") if ctx.failure else ""
    _touch_step(
        step,
        status=status,
        error=ctx.failure or None,
        error_code=code,
        finished_at=utcnow_iso(),
        duration_ms=_ms(started),
        tokens=ctx.tokens,
        detail={
            **ctx.detail,
            "percent": 100,
            "model": ctx.model_name or "",
            "provider": getattr(ctx.provider, "name", ""),
            "tokens": ctx.tokens,
            "latencyMs": _ms(started),
            "attempts": run_no,
            "promptVersion": prompts.PROMPT_VERSION,
        },
    )
    events.emit(ctx.job_id, "step.done", {
        "stepId": step.id, "type": step.type, "tokens": ctx.tokens, "errorCode": code,
        "detail": ctx.detail, "progress": _touch_job(ctx.job).progress,
    })
    return status


# --- 各步骤 ---


def parse_topic(ctx: StepContext) -> None:
    """解析主题，得到受众画像。它是后面每一步的上下文起点（§4.2）。"""
    messages = prompts.profile_messages(ctx.topic, ctx.options)
    call = call_json(
        ctx.provider, messages,
        schema=schema_for_profile(), parse=parse_profile,
        job_id=ctx.job_id, owner_id=ctx.owner_id, step_id=ctx.step.id,
    )
    ctx.count(call.tokens, call.model)
    store.set_dsl_meta(ctx.course, {"audienceProfile": call.data})
    ctx.detail["profile"] = call.data
    ctx.progress(100)


def build_outline(ctx: StepContext) -> None:
    """生成大纲，并**在这里把全部页行铺出来**（页号从此定死）。

    关联了材料的课（F4-7）在这里就带上材料：大纲要贴着讲义的章节走，
    而不是生成完之后再让用户手动改（P4-A5 的第一道）。
    """
    profile = _profile_of(ctx.course)
    # 校验的是**正文页**上限：总页数上限减去系统必补的几页（见 prompts.page_budget）
    limit = prompts.content_page_limit(ctx.options, max_total=max_page_count())
    materials = list(
        sourcing.inject(
            ctx.course.id, ctx.topic, limit=citations.config_int("MATERIAL_OUTLINE_TOP_K", 5)
        ).values()
    )
    messages = prompts.outline_messages(ctx.topic, profile, ctx.options, materials=materials)
    call = call_json(
        ctx.provider, messages,
        schema=schema_for_outline(max_pages=limit),
        parse=lambda text: parse_outline(text, max_pages=limit),
        job_id=ctx.job_id, owner_id=ctx.owner_id, step_id=ctx.step.id,
    )
    ctx.count(call.tokens, call.model)
    outline = call.data

    rows = store.allocate_pages(
        ctx.course,
        outline,
        quiz_per_chapter=bool(ctx.options.get("quizPerChapter")),
        debate=str(ctx.options.get("mode") or "lecture") == "seminar",
    )
    ctx.detail["chapters"] = len(outline["chapters"])
    ctx.detail["pages"] = len(rows)
    ctx.progress(100)


def write_pages(ctx: StepContext) -> None:
    """并发写页。

    并发只影响「同时发几个请求」，不影响结果的确定性：每一页都是独立的一次调用，
    页间的顺序靠 `previous`（上一页的要点摘要）在提示词里交代。
    """
    rows = store.pages_of(ctx.course)
    if not rows:
        ctx.failure = "没有可写的页面（大纲未生成或页面已被删空）"
        ctx.failure_code = "no_pages"
        return

    batches = _build_batches(rows)
    ctx.detail["batches"] = batches
    ctx.progress(0)

    pending = [row for row in rows if row.status != "ready"]
    if not pending:
        ctx.progress(100)
        return

    total = len(pending)
    done = 0
    failed_pages: list[int] = []
    failed_codes: list[str] = []
    options = dict(ctx.options)

    # 结果按**提交顺序**取（future.result() 会等这一个，而不是等最先完成的那个）：
    # 并发跑，但进度按页号推进，用户看到的进度条是一条平滑的线而不是跳来跳去。
    with ThreadPoolExecutor(max_workers=int(options.get("concurrency") or 3)) as pool:
        futures = {
            pool.submit(_write_one, ctx.app, PageTask(
                job_id=ctx.job_id, course_id=ctx.course.id, page_id=row.id,
                provider=ctx.provider, owner_id=ctx.owner_id, step_id=ctx.step.id,
            )): row.page_no
            for row in pending
        }
        for future in futures:
            result = future.result()
            done += 1
            if result["status"] == "failed":
                failed_pages.append(result["pageNo"])
                failed_codes.append(str(result.get("errorCode") or "page_failed"))
            if result.get("tokens"):
                ctx.count(int(result["tokens"]), str(result.get("model") or ""))
            _mark_batch(batches, result["pageNo"], result["status"])
            ctx.progress(int(done * 100 / total), {"pageNo": result["pageNo"]})

    if failed_pages:
        ctx.failure = "第 " + "、".join(str(no) for no in sorted(failed_pages)) + " 页生成失败"
        # 归类码取**第一页**的：几页同时失败时（限流最常见的形态就是「并发三页一起撞墙」），
        # 用户要做的是同一件事，而把几个码拼在一起只会让前端挑不出一个来显示。
        ctx.failure_code = failed_codes[0]
    elif ctx.stop():
        raise PipelineCancelled
    ctx.detail["batches"] = _finalize_batches(batches, rows)


def make_quiz_and_discussion(ctx: StepContext) -> None:
    """章级讨论问题（§3.1 的「讨论问题（章末，开关控制）」）。

    测验页本身由 write 一并产出（同一个写作者 → 页号连续、幂等与重试都只有一条路径），
    这一步产出的是**挂在章节上的讨论问题**：它们不占页面，进课程 DSL 的 chapters[].discussion。
    """
    chapters = (ctx.course.dsl or {}).get("chapters") or []
    if not chapters:
        ctx.failure = "没有可出题的章节（大纲未生成）"
        ctx.failure_code = "no_chapters"
        return

    profile = _profile_of(ctx.course)
    rows = store.ready_pages(ctx.course)
    updated: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters, start=1):
        if ctx.stop():
            raise PipelineCancelled
        pages = [row.dsl for row in rows if int(row.chapter_no or 0) == int(chapter.get("no") or 0)]
        call = call_json(
            ctx.provider,
            prompts.discussion_messages(chapter, pages, profile),
            schema=schema_for_discussion(),
            parse=parse_discussion,
            job_id=ctx.job_id,
            owner_id=ctx.owner_id,
            step_id=ctx.step.id,
        )
        ctx.count(call.tokens, call.model)
        updated.append({"no": chapter.get("no"), "discussion": call.data["questions"]})
        ctx.progress(int(index * 100 / len(chapters)))

    store.update_chapters(ctx.course, updated)


def synthesize_narration(ctx: StepContext) -> None:
    """整课预合成（P2-A2）：把写好的讲稿变成一句一句的音频。

    **走的是与「全部合成」按钮同一条路**（`voice.jobs.run`）。合成是幂等的、
    按规格哈希认缓存，所以「老师点过按钮」与「管线跑过这一步」既不重复花钱，
    也不会互相打架。在这里另拼一遍参数（音色、语速、纠音表）迟早会分叉 ——
    接口那边加了 `force`，管线这边忘了，症状是「重生成之后声音还是旧的」。

    没有声音的几条路**跳过**而不是失败，它们都只说明「这节课没有声音」，
    课程本身是好的（P2-G3：关掉语音之后课堂仍是一节可读、可打字的纯文字课堂）：

    - 总开关关着（`VOICE_ENABLED=false`）；
    - 没有可用的音色（上游音色 ID 没配）；
    - 服务商配不上（40201）—— 语音是附加产物，Key 没填不该让整课判失败。

    反过来说，**一句都没合出来**是真失败：那说明音色或服务商配错了，
    而用户看到的应该是一个能去修的错，不是「这节课就是没有声音」。
    """
    # 局部 import：语音是可选的一整块，管线的主链路（解析→大纲→写页）不该
    # 因为语音包里的任何东西而导入失败（AGENTS §14.2 的分层也要求这一层
    # 只认「谁调我」，不认厂商细节）。
    from app.services.voice import jobs as voice_jobs

    def _progress(done: int, count: int) -> None:
        # 合成是一句一句来的，进度就是「第几句」。百分比之外再留一份数字，
        # 好让进度条说得比「37%」具体一点。
        ctx.progress(int(done * 100 / count) if count else 0, {"done": done, "beats": count})

    try:
        report = voice_jobs.run(ctx.course.id, on_progress=_progress)
    except AppError as exc:
        # 40201 之类：这一课没有声音，但课是完整的
        raise StepSkipped(f"{exc.message}（这节课没有声音）") from exc

    if not report.get("enabled"):
        raise StepSkipped(_no_voice_reason(report.get("reason") or ""))

    total = int(report.get("total") or 0)
    ctx.detail.update(
        {
            "beats": total,
            "synthesized": int(report.get("synthesized") or 0),
            "cached": int(report.get("cached") or 0),
            "failed": len(report.get("failed") or []),
        }
    )
    if total and report.get("reason") == "all_failed":
        # 进 detail、也进 failure：这一句错误是给用户看的
        ctx.failure = f"{total} 句讲稿一句都没合成出声音，请检查音色与服务商配置"
        ctx.failure_code = "voice_all_failed"
    ctx.progress(100)


#: 「这节课没有声音」的四种说法。理由要分得开：开关关着是部署的决定、
#: 音色没配是使用者的选择、服务商没配是 Key 没填 —— 修法完全不同。
_NO_VOICE_REASONS: dict[str, str] = {
    "voice_disabled": "语音功能已关闭（VOICE_ENABLED=false），这节课是纯文字的",
    "voice_not_configured": "还没有可用的音色（上游音色 ID 未配置），这节课没有声音",
    "course_not_found": "课程在合成前已被删除",
}


def _no_voice_reason(reason: str) -> str:
    return _NO_VOICE_REASONS.get(reason, "这节课没有合成语音")


def assemble_course(ctx: StepContext) -> None:
    """把页面重建成课程 DSL，并给课程定状态。"""
    ready = store.ready_pages(ctx.course)
    dsl = store.rebuild_dsl(ctx.course, meta={
        "provider": getattr(ctx.provider, "name", ""),
        "model": ctx.model_name or getattr(ctx.provider, "default_model", ""),
        "tokens": _ledger_tokens(ctx.job_id),
        "generatedAt": utcnow_iso(),
        "promptVersion": prompts.PROMPT_VERSION,
    })
    _touch_course(ctx.course, status="ready" if ready else "failed")
    ctx.detail["pages"] = len(ready)
    ctx.detail["chapters"] = len(dsl["chapters"])
    ctx.progress(100)


#: 六步与权重。放在步骤函数之后，是因为声明表直接引用函数对象。
#:
#: 权重取自两处文档的并集：技术方案 §4.1 给了 parse/outline/write/quiz/tts，
#: P1 文档 §6 给了 parse/outline/write/quiz/assemble。两处都少一个，
#: 于是 tts 与 assemble 各占 5%（tts 在 P1 还不干活，P2 接上后仍是这个位置）。
PIPELINE: tuple[Step, ...] = (
    Step("parse", "解析需求与受众画像", 5, parse_topic),
    Step("outline", "生成课程大纲", 10, build_outline, pause_after=True),
    Step("write", "撰写页面内容与讲稿", 60, write_pages, parallel=3),
    Step("quiz", "设计讨论问题与随堂测验", 15, make_quiz_and_discussion),
    Step("tts", "合成教师语音", 5, synthesize_narration, optional=True),
    Step("assemble", "装配课程", 5, assemble_course),
)

WEIGHTS: dict[str, int] = {step.type: step.weight for step in PIPELINE}


# --- 写一页 ---


@dataclass(frozen=True)
class PageTask:
    """写一页所需的全部入参。

    它只带 **id 和 provider**，不带任何 ORM 对象：任务要在子线程里重新取一次。
    把父线程的 ORM 对象递进子线程，是这类并发代码最常见的一处坑 ——
    对象绑定在父线程的会话上，子线程一碰就是「跨线程使用同一会话」。
    """

    job_id: str
    course_id: str
    page_id: str
    provider: LLMProvider
    owner_id: str
    #: 这一页算在 `gen_steps` 的哪一步上（P5-C2 的账本要用它回答
    #: 「钱花在哪一步」）。空串也合法 —— 手工触发单页重写时没有步骤。
    step_id: str = ""


def _write_one(app: Any, task: PageTask) -> dict:
    """在一页上做完「取上下文 → 调用 → 校验 → 合规检查 → 落库 → 推事件」。

    在**子线程**里跑，所以自己推一个 app 上下文、自己取一次会话里的对象：
    Flask 的上下文是线程局部的，父线程那些 ORM 对象在别的会话里碰不得。
    """
    job_id = task.job_id
    with app.app_context():
        page = db.session.get(CoursePage, task.page_id)
        if page is None:
            return {"pageNo": 0, "status": "gone"}
        number = page.page_no
        if is_cancel_requested(job_id):
            return {"pageNo": number, "status": "canceled"}
        # 幂等：已经有成功版本的页面不重写（断点续跑、重试的基础，§3.1）
        if page.status == "ready" and page.dsl:
            return {"pageNo": number, "status": "skipped"}

        course = db.session.get(Course, task.course_id)
        profile = _profile_of(course) if course else {}
        outline = _outline_of(course) if course else {}
        previous = _previous_of(course, page.page_no)

        target = {
            "pageNo": number, "chapterNo": page.chapter_no, "kind": page.kind,
            "title": page.title or "", "points": _points_of(course, number),
        }
        # 材料注入（F4-7）：按这一页要讲的东西检索这门课关联的材料。
        # 没有材料时拿到的是空表，后面每一步都会自然退回去（P4-G3）。
        injected = sourcing.inject(
            task.course_id,
            sourcing.page_query(target),
            limit=citations.config_int("MATERIAL_PAGE_TOP_K", 8),
        )
        messages = prompts.page_messages(
            target, profile=profile, outline=outline, previous=previous,
            materials=list(injected.values()),
        )

        produced = _produce(page, task, messages, number, injected=injected)
        if isinstance(produced, PageFailure):
            # 失败原因既是页面的 error，也是这一步的汇总信息（「第 3 页生成失败」）
            store.mark_page_failed(page, produced.message)
            logger.warning(
                "写页失败（job=%s page=%s code=%s）：%s", job_id, number, produced.code, produced.message
            )
            return {"pageNo": number, "status": "failed", "error": produced.message,
                    "errorCode": produced.code}
        dsl, tokens, model, attempts, sources = produced

        try:
            store.save_page(
                page, dsl, reason="generate", model=model, tokens=tokens,
                meta={"promptVersion": prompts.PROMPT_VERSION, "generatedAt": utcnow_iso(),
                      "attempts": attempts, "sources": sources},
            )
            # 溯源落到 page_sources（F4-8）：与页面内容分两次写，见 sourcing.persist
            sourcing.persist(page, dsl)
        except Exception as exc:  # 落库失败也只算这一页失败
            message = f"第 {number} 页写入失败：{type(exc).__name__}"
            store.mark_page_failed(page, message)
            logger.error("写页落库失败（job=%s page=%s）：%s", job_id, number, type(exc).__name__)
            return {"pageNo": number, "status": "failed", "error": message,
                    "errorCode": "page_write_failed"}

        events.emit(job_id, "page.ready", {
            "pageNo": number, "kind": page.kind, "title": page.title or "",
            "chapterNo": page.chapter_no, "rev": page.rev, "attempts": attempts,
            # 出处条数与「有没有引文没对上」：前端据此决定徽标是亮的还是黄的
            "sources": len(dsl.get("sources") or []),
            "sourceMissing": bool(dsl.get("sourceMissing")),
        })
        return {"pageNo": number, "status": "ready", "tokens": tokens, "model": model,
                "attempts": attempts, "sources": len(dsl.get("sources") or [])}


def _produce(
    page: CoursePage, task: PageTask, messages: list[dict], number: int,
    *, injected: Mapping[str, dict] | None = None,
) -> tuple[dict, int, str, int, dict] | PageFailure:
    """调用模型产出这一页（含合规检查与出处定案）。返回内容，或**失败的原因与归类**。

    调用与落库分成两步、失败用返回值而不是异常 —— 这样「模型没写好」和
    「写库没写成」在日志与页面的 error 里是两句不同的话，排障时不用去猜。

    出处定案（`sourcing.settle`）摆在合规检查**之后**：合规不过这一页根本不上架，
    再花一次调用去核对它的引文纯属浪费。重试也共用同一条对话 ——
    「上一版讲了什么」与「要改什么」都靠 `messages` 后面的两轮补上。
    """
    blocked = ""
    # 重生成时要把「上一版说了什么」回喂给模型，而合规重写会换掉那一版，
    # 所以用一个小格子跟着当前这一版的原文走（闭包拿不到后来的赋值）。
    state = {"text": ""}

    def _regenerate(feedback: str) -> tuple[dict, int]:
        again = call_page(
            task.provider,
            [*messages, {"role": "assistant", "content": clip_feedback(state["text"])},
             {"role": "user", "content": feedback}],
            kind=page.kind, page_no=number, chapter_no=page.chapter_no,
            job_id=task.job_id, owner_id=task.owner_id, step_id=task.step_id,
        )
        return again.data, again.tokens

    try:
        call = call_page(task.provider, messages, kind=page.kind, page_no=number,
                         chapter_no=page.chapter_no, job_id=task.job_id,
                         owner_id=task.owner_id, step_id=task.step_id)
        dsl, tokens, model = call.data, call.tokens, call.model
        attempts = call.attempts
        state["text"] = call.text

        hits = scan_page(dsl)
        if hits:
            call2 = call_page(
                task.provider,
                [*messages, {"role": "assistant", "content": clip_feedback(call.text)},
                 {"role": "user", "content": _SENSITIVE_RETRY.format(words="、".join(hits))}],
                kind=page.kind, page_no=number, chapter_no=page.chapter_no,
                job_id=task.job_id, owner_id=task.owner_id, step_id=task.step_id,
            )
            tokens += call2.tokens
            attempts += call2.attempts
            still = scan_page(call2.data)
            if still:
                # 重生成一次仍然命中：这一页不上架。审计记的是**第二次**的命中词
                # ——「重写也没救回来」的判断依据是它。
                record_hit(target=f"page:{page.id}", owner_id=task.owner_id, words=still,
                           outcome=OUTCOME_BLOCKED,
                           extra={"courseId": task.course_id, "pageNo": number})
                blocked = "内容合规检查未通过，已拦截本次生成"
            else:
                record_hit(target=f"page:{page.id}", owner_id=task.owner_id, words=hits,
                           outcome=OUTCOME_REGENERATED,
                           extra={"courseId": task.course_id, "pageNo": number})
                dsl = call2.data
                model = call2.model or model
                state["text"] = call2.text
    except Exception as exc:  # 单页失败只标记这一页（P1-F1）
        # 归类码跟着**原始异常**走：限流就是限流，超时就是超时（P5-A10 要看的正是这个）
        return PageFailure(f"第 {number} 页生成失败：{_error_text(exc)}", error_code_of(exc))

    if blocked:
        return PageFailure(blocked, "content_blocked")

    dsl, summary = sourcing.settle(dsl, injected or {}, regenerate=_regenerate)
    # 重试那次也是真花钱的调用，照样进账本（它已经在 ModelCall 里，这里只是
    # 把它加进这一步的合计，免得「账单比进度条上的数字多」）
    tokens += int(summary.get("retryTokens") or 0)
    return dsl, tokens, model, attempts, summary


# --- 上下文（每一步都从库里读，见模块 docstring 第 1 条）---


def _profile_of(course: Course | None) -> dict:
    if course is None:
        return {}
    return dict(((course.dsl or {}).get("meta") or {}).get("audienceProfile") or {})


def _outline_of(course: Course | None) -> dict:
    """全课大纲，页数写成 {title, kind} 的那一版（提示词要的是标题清单）。

    库里存的 `chapters[].pages` 是**页号**（大纲阶段铺页时定的），
    而提示词要的是「第几章讲什么」—— 从 `course_pages` 取标题补上这层。
    """
    if course is None:
        return {}
    stored = course.dsl or {}
    by_chapter: dict[int, list[CoursePage]] = {}
    for row in store.pages_of(course):
        by_chapter.setdefault(int(row.chapter_no or 0), []).append(row)

    chapters = [
        {
            "no": int(chapter.get("no") or 0),
            "title": str(chapter.get("title") or ""),
            "pages": [
                {"title": row.title or "", "kind": row.kind}
                for row in by_chapter.get(int(chapter.get("no") or 0), [])
            ],
        }
        for chapter in stored.get("chapters") or []
    ]
    return {"title": stored.get("title") or course.title, "chapters": chapters}


def _points_of(course: Course | None, page_no: int) -> list[str]:
    """这一页在大纲里被安排的要点（写页时当提示，来自大纲而不是正文）。"""
    if course is None:
        return []
    for chapter in (course.dsl or {}).get("chapters") or []:
        if page_no in (chapter.get("pages") or []):
            return [str(point) for point in chapter.get("points") or []][:4]
    return []


def _previous_of(course: Course | None, page_no: int) -> dict | None:
    """上一页的摘要：标题 + 要点，**不带讲稿**（§4.2 的上下文控制）。"""
    if course is None:
        return None
    row = store.page_by_no(course, page_no - 1)
    if row is None or row.status != "ready" or not row.dsl:
        return None
    return {
        "pageNo": row.page_no,
        "title": row.dsl.get("title") or row.title,
        "bullets": row.dsl.get("bullets") or [],
    }


# --- 批次（原型上 write 下面的两行子步骤）---


def _build_batches(rows: Sequence[CoursePage]) -> list[dict]:
    sizes = _balanced_sizes(len(rows), BATCH_SIZE)
    batches = []
    cursor = 0
    for size in sizes:
        chunk = rows[cursor : cursor + size]
        cursor += size
        batches.append({
            "label": f"撰写第 {chunk[0].page_no}–{chunk[-1].page_no} 页",
            "from": chunk[0].page_no,
            "to": chunk[-1].page_no,
            "total": len(chunk),
            "done": sum(1 for row in chunk if row.status == "ready"),
            "status": "wait",
        })
    return batches


def _balanced_sizes(count: int, size: int) -> list[int]:
    """把 count 页尽量均匀地分成若干批，每批不超过 size 页。

    均匀而不是「凑满 size」：13 页按 6 切会得到 [6, 6, 1]，
    最后那批只有一页，看起来像出错。均衡成 [5, 5, 3]。
    """
    parts = max(1, math.ceil(count / max(1, size)))
    base, extra = divmod(count, parts)
    return [base + (1 if index < extra else 0) for index in range(parts)]


def _mark_batch(batches: Sequence[dict], page_no: int, status: str) -> None:
    """一页收工后推进它所在批次的计数。

    canceled 不算完成 —— 那一页并没有写成，把它算进去会让批次显示成绿的。
    """
    for batch in batches:
        if batch["from"] <= page_no <= batch["to"]:
            if status in {"ready", "skipped", "failed"}:
                batch["done"] = min(batch["total"], batch["done"] + 1)
            batch["status"] = "done" if batch["done"] >= batch["total"] else "running"
            break


def _finalize_batches(batches: list[dict], rows: Sequence[CoursePage]) -> list[dict]:
    """收尾时以页面行的真实状态为准重算一遍 —— 进度是过程，状态是结果。"""
    for batch in batches:
        chunk = [row for row in rows if batch["from"] <= row.page_no <= batch["to"]]
        batch["done"] = sum(1 for row in chunk if row.status in {"ready", "failed"})
        batch["status"] = "done" if batch["done"] >= batch["total"] else "failed"
    return batches


# --- 重启收拾 ---

#: 被重启打断的实例留下的状态。**不含 paused**：等用户确认大纲的任务本来就该
#: 停在原地，进程重启后用户点「继续」照样能跑（P1-A3）。
STUCK_JOB_STATUSES = ("queued", "running")

#: 恢复时写给用户看的原因。要能照着做：这是「重试」按钮存在的理由（P1-C5）。
RESTART_ERROR = "服务重启，生成已中断，可重试"


def recover_stuck_jobs() -> dict[str, int]:
    """收拾上一次进程留下的「还在生成中」（P1-C5）。

    进程一重启，跑任务的线程就没了，可库里的状态还停在 `running` ——
    前端会永远显示一个不动的进度环，而用户没有任何办法把它推下去。
    所以启动时把它们统一改成 `failed` + 一句可重试的说明。

    只改状态、不删数据：已经写好的页面留着，用户点「重试」时幂等检查会
    跳过它们（同一门课不会为已经付过钱的页再付一次）。
    """
    jobs = GenJob.query.filter(GenJob.status.in_(STUCK_JOB_STATUSES)).all()
    # 课程跟任务走，但**等大纲确认的课程除外**：它的任务 paused，课程状态还是
    # generating 是正常的 —— 用户点「继续」时它就该从那儿接着跑。
    # 少了这个例外，重启会把每一门等确认的课判死，而那是用户没点过的按钮。
    paused_courses = {
        row.course_id for row in GenJob.query.filter(GenJob.status == "paused").all()
    }
    courses = [
        course
        for course in Course.query.filter(Course.status == "generating").all()
        if course.id not in paused_courses
    ]
    if not jobs and not courses:
        return {"jobs": 0, "courses": 0}

    def _work() -> None:
        for job in jobs:
            job.status = "failed"
            job.error = RESTART_ERROR
            job.progress = job_progress(job)
        for course in courses:
            course.status = "failed"
            # 课程跟着任务一起失败，但页面留着 —— 重试时它们就是省下来的钱
        for step in GenStep.query.filter(
            GenStep.job_id.in_([job.id for job in jobs]),
            GenStep.status == "running",
        ):
            # 步骤也停在 running，跟着一起收：否则重试时它会从 wait 之外的地方开始
            step.status = "failed"
            step.error = RESTART_ERROR
            # 归类码：重启与「上游挂了」是两回事，时间线上要分得开 ——
            # 前者该点「继续生成」，后者得先看看上游（P5-A9 / P5-A10）。
            step.error_code = "interrupted"

    db_write(_work)
    for job in jobs:
        events.emit(job.id, "job.failed", {
            "jobId": job.id, "error": RESTART_ERROR, "progress": job.progress, "recovered": True,
        })
    logger.warning(
        "重启收拾：%d 个任务、%d 门课程被标记为失败（可重试）", len(jobs), len(courses)
    )
    return {"jobs": len(jobs), "courses": len(courses)}


# --- 收尾 ---


def _finish_canceled(job: GenJob, course: Course | None) -> None:
    _settle_cancellation(job, course)
    events.emit(job.id, "job.canceled", {"jobId": job.id, "progress": job.progress})


def _settle_cancellation(job: GenJob, course: Course | None) -> None:
    """取消的落点：任务 canceled、课程回到 draft、已生成的页面保留（P1-A9）。

    课程回到 draft 而不是 failed：它没有坏，只是还没写完，用户可以接着生成或删掉。
    页面一页都不删 —— 取消的意思是「别再花钱了」，不是「把已经花钱买到的扔掉」。
    """
    _touch_job(job, status="canceled")
    if course is None:
        return
    store.rebuild_dsl(course)
    _touch_course(course, status="draft")


def _ledger_tokens(job_id: str) -> int:
    """这次任务的 token 消耗，直接问账本（P1-D4 的对账口径）。"""
    total = (
        db.session.query(db.func.coalesce(db.func.sum(ModelCall.tokens), 0))
        .filter(ModelCall.job_id == job_id)
        .scalar()
    )
    return int(total or 0)


def _elapsed_since(created_at: str | None) -> int:
    return elapsed_ms(parse_iso(created_at))


def _first_error(job: GenJob) -> str:
    for step in steps_of(job):
        if step.status == "failed" and step.error:
            return step.error
    return "生成失败"


def _step_plan(job: GenJob) -> list[dict]:
    return [
        {"id": step.id, "type": step.type, "title": step.title, "weight": weight_of(step.type)}
        for step in steps_of(job)
    ]


def _error_text(exc: BaseException) -> str:
    """给人看的失败原因。**不含生成内容、不含提示词**（AGENTS §19）。"""
    if isinstance(exc, AppError):
        return str(exc.message)
    if isinstance(exc, SchemaInvalid):
        return str(exc)
    return f"内部错误（{type(exc).__name__}）"


def _touch_job(job: GenJob, **fields: Any) -> GenJob:
    def _work() -> None:
        for key, value in fields.items():
            setattr(job, key, value)
        job.progress = job_progress(job)

    db_write(_work)
    return job


def _touch_step(step: GenStep, **fields: Any) -> GenStep:
    def _work() -> None:
        for key, value in fields.items():
            if key == "detail":
                step.detail = dict(value)
            else:
                setattr(step, key, value)

    db_write(_work)
    return step


def _touch_course(course: Course, **fields: Any) -> None:
    def _work() -> None:
        for key, value in fields.items():
            setattr(course, key, value)

    db_write(_work)


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _provider() -> LLMProvider:
    from app.services.provider_registry import get_registry

    return get_registry().current_llm()


__all__ = [
    "BATCH_SIZE",
    "DEFAULT_OPTIONS",
    "PIPELINE",
    "RESTART_ERROR",
    "WEIGHTS",
    "PageFailure",
    "PipelineCancelled",
    "Step",
    "StepContext",
    "StepSkipped",
    "clear_cancel_flags",
    "concurrency",
    "is_cancel_requested",
    "job_progress",
    "percent_of",
    "recover_stuck_jobs",
    "request_cancel",
    "resume_job",
    "retry_step",
    "run_job",
    "start_job",
    "step_of",
    "weight_of",
]
