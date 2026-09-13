"""生成任务时间线（P5-F5-10 / P5-A10）。

`GET /api/jobs/{jobId}` 回答的是「现在到哪了」，这个模块回答的是
**「它是怎么走到这儿的」**：每一步跑了多久、跑了几次、花了多少 token、
失败在上游的哪一类错误上。工作台的任务卡展开时读它。

与 `services/classroom/timeline.py` 不是一回事：那个是**课堂播放**的时间线
（第 1 页念 42 秒、合计 25:00），这个是**生成过程**的时间线。两个同名模块在
两个不同的包里，各自服务一端的界面。

### 三个数从哪儿来

| 数 | 来源 | 为什么 |
|----|------|--------|
| 耗时 / 重试次数 / 错误码 | `gen_steps` 自己的列 | 它是「这一步」的事实 |
| token / 金额 / 调用次数 | `model_calls` 按 `step_id` 分组 | 账本口径，与成本看板同源（§10.2） |
| 失败原因那句话 | `gen_steps.error` | 给人读的，不含提示词与生成内容 |

**金额只认 `model_calls`（LLM）**，与成本看板同一条口径。语音（TTS/ASR/实时）
另有 `usage_records` 那条链路，且**按课程计量、不挂在这条任务上** ——
它不进这张表，所以这里也不编一个假的「本任务语音花费」。看板上看得到。

### 一次查询，不是 N+1

一次生成有 6 个步骤、几十次调用。逐个步骤去查账本的话，工作台每展开一次
任务卡就是 7 次查询。这里一次把整个任务的账本行取回来，在内存里按
`step_id` 分桶 —— 行数是有界的（一次生成撑死几百行）。
"""

from __future__ import annotations

from typing import Any, Sequence

from app.models import GenJob, GenStep, ModelCall
from app.services.generation import pipeline

#: 金额口径的说明，与看板、预算同一条（三处都写这一句，是因为它们会出现在
#: 三个不同的界面上，而用户不该在两个界面看到两种说法）。
NOTE = "估算值，以账单为准；语音按量计费，见成本看板"

#: 一个步骤最多带回几个模型名。这一步正常只会用一个，多了说明中途换过服务商
#: 或降级过 —— 值得看见，但不值得为它把整个列表铺出来。
_MAX_MODELS = 3


def build(job: GenJob) -> dict[str, Any]:
    """任务时间线：任务概要 + 逐步详情 + 合计。"""
    steps = pipeline.steps_of(job)
    buckets = _by_step(_calls_of_job(job.id))
    return {
        "job": _job_payload(job, steps),
        "steps": [_step_payload(step, buckets.get(step.id, [])) for step in steps],
        "totals": _totals(steps, buckets),
        "note": NOTE,
    }


# --------------------------------------------------------------------------
# 任务
# --------------------------------------------------------------------------


def _job_payload(job: GenJob, steps: Sequence[GenStep]) -> dict[str, Any]:
    payload = job.to_dict()
    # 任务自己没有 error_code 列（失败原因那句话来自它的某个步骤），
    # 所以这里从步骤上推：折叠着的任务卡要能一眼看出「是限流还是没配 Key」。
    payload["errorCode"] = _job_error_code(steps)
    payload["currentStep"] = next(
        (step.id for step in steps if step.status == "running"), ""
    )
    return payload


def _job_error_code(steps: Sequence[GenStep]) -> str:
    for step in steps:
        if step.status == "failed" and step.error_code:
            return step.error_code
    return ""


# --------------------------------------------------------------------------
# 步骤
# --------------------------------------------------------------------------


def _step_payload(step: GenStep, calls: Sequence[ModelCall]) -> dict[str, Any]:
    payload = step.to_dict()
    # 权重是**声明**（`PIPELINE` 那张表）而不是行上的字段：步骤行只记了 type，
    # 权重随代码版本走。前端按它画那根六段进度条，与 `job_progress` 同一份来源。
    payload["weight"] = pipeline.weight_of(step.type)
    payload["percent"] = pipeline.percent_of(step)
    payload["calls"] = _call_stats(calls)
    return payload


def _call_stats(calls: Sequence[ModelCall]) -> dict[str, Any]:
    """这一步在账本上的样子：发了几次、失败几次、多少 token、多少钱。"""
    failed = [row for row in calls if not row.ok]
    return {
        "count": len(calls),
        # 失败的那几次**也在**（那是排障时最想看的一行）：成功的次数是
        # `count - failed`，前端要显示「重试了 2 次」时不必自己再去减。
        "failed": len(failed),
        "tokens": sum(int(row.tokens or 0) for row in calls),
        "estCost": round(sum(float(row.est_cost or 0.0) for row in calls), 6),
        "latencyMs": sum(int(row.latency_ms or 0) for row in calls),
        "errorCodes": _codes(failed),
        "models": _models(calls),
    }


def _codes(failed: Sequence[ModelCall]) -> list[str]:
    """失败过的错误码，按**首次出现的顺序**去重（不排序）。

    顺序就是事情发生的顺序：先超时后来变成限流，与反过来，是两种不同的故障。
    """
    out: list[str] = []
    for row in failed:
        code = row.error_code or ""
        if code and code not in out:
            out.append(code)
    return out


def _models(calls: Sequence[ModelCall]) -> list[str]:
    out: list[str] = []
    for row in calls:
        name = row.model or row.provider or ""
        if name and name not in out:
            out.append(name)
    return out[:_MAX_MODELS]


# --------------------------------------------------------------------------
# 合计
# --------------------------------------------------------------------------


def _totals(steps: Sequence[GenStep], buckets: dict[str, list[ModelCall]]) -> dict[str, Any]:
    """整个任务的合计。token / 金额走账本，与 `job.total_tokens` 同一来源。

    `stepMs`（各步耗时相加）与 `job.totalMs`（挂钟时间）是两个数，都留着：
    步骤是串行的，相加通常**略大于**挂钟 —— 差额是调度与两帧之间那些缝隙。
    差得离谱（比如两倍）说明有步骤在并发跑，那是另一件事，不是算错了。
    """
    mine = [row for step in steps for row in buckets.get(step.id, [])]
    orphans = [row for step_id, rows in buckets.items() if not step_id for row in rows]
    return {
        "steps": len(steps),
        "stepMs": sum(int(step.duration_ms or 0) for step in steps),
        "attempts": sum(int(step.attempts or 0) for step in steps),
        "retriedSteps": sum(1 for step in steps if int(step.attempts or 0) > 1),
        "failedSteps": sum(1 for step in steps if step.status == "failed"),
        "skippedSteps": sum(1 for step in steps if step.status == "skipped"),
        # 与每一步的 `calls` **同形**：前端一套渲染逻辑，步骤级与任务级各铺一次
        "calls": _call_stats([*mine, *orphans]),
        # 有 job_id 却没落到任何一步上的调用（认不出归属的那些）。
        # 正常跑不会出现，出现了一定是埋点漏了 step_id —— 与其把它悄悄丢掉，
        # 不如让它在合计里露出来：token 对不上账时，这是第一个该看的地方。
        "unattributed": _call_stats(orphans),
    }


# --------------------------------------------------------------------------
# 账本
# --------------------------------------------------------------------------


def _calls_of_job(job_id: str) -> list[ModelCall]:
    """这个任务的全部账本行。**一次查询**（见模块 docstring）。"""
    return list(
        ModelCall.query.filter(ModelCall.job_id == job_id)
        .order_by(ModelCall.created_at)
        .all()
    )


def _by_step(calls: Sequence[ModelCall]) -> dict[str, list[ModelCall]]:
    """按步骤分桶。`step_id` 为空的落进 `""` 桶（见 `_totals`）。"""
    out: dict[str, list[ModelCall]] = {}
    for row in calls:
        out.setdefault(row.step_id or "", []).append(row)
    return out


__all__ = ["NOTE", "build"]
