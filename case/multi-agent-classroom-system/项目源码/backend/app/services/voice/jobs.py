"""整课预合成的后台任务（P2-A2 / §4.1 的 narrate 端点）。

一次整课合成是分钟级的事（十几句、每句一次上游往返），所以接口层必须立刻返回、
把活丢给线程池 —— 与 P1 的写页同一个理由（P1-B1）。复用 P1 的 `TaskRunner`：

**没有新表。** 进度不落库，而是从音频资产里**推**出来：`readyCount / beatCount`
（见 `assets.manifest`）。这条路能成立是因为合成是**幂等**的 —— 每个 beat 一份
资产、按规格哈希认缓存，所以「已经有了几句」就是「进度到哪儿了」，
不需要另记一个计数器去跟资产对账（两处记同一件事，迟早对不上）。
进程重启、任务被取消、用户手动补合成几句，进度照样是对的。

**同一门课同时只跑一个。** `TaskRunner.submit` 按 key 去重：重复点击返回 False，
不排队也不覆盖 —— 两个线程同时写同一批 `audio_assets` 行，会因为唯一键撞车
而出现「这一句谁写的」这种没法查的问题。

失败写在哪：`audio_assets.status = failed`（那一句没有声音），**不写任务表**。
用户看的是清单里哪几句没声，而不是某个任务对象的错误字符串。
"""

from __future__ import annotations

from typing import Any, Callable

from app.common.logging import get_logger
from app.common.tasks import get_runner
from app.extensions import db
from app.models import Course
from app.services.voice import assets
from app.services.voice import prefs as voice_prefs

logger = get_logger("app.voice.jobs")

#: 任务 key 的前缀。看 `TaskRunner.running_keys()` 时能认出这是我们丢的活。
KEY_PREFIX = "narrate"


def task_key(course_id: str) -> str:
    return f"{KEY_PREFIX}:{course_id}"


def is_running(course_id: str) -> bool:
    return get_runner().is_running(task_key(course_id))


def submit(
    course_id: str, *, force: bool = False, page_no: int | None = None
) -> bool:
    """把一门课的预合成丢到后台。返回 False 表示这门课已经在合成了。"""
    return get_runner().submit(
        task_key(course_id),
        lambda: run(course_id, force=force, page_no=page_no),
    )


def run(
    course_id: str,
    *,
    force: bool = False,
    page_no: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """合成整课（或某一页）。**在后台线程里执行**，异常由 TaskRunner 收尾。

    参数在这里现取（而不是由接口层传进来）：线程里已经推好了 app context
    （见 `TaskRunner._guard`），而设置页与注册表都可能在这期间被改过 ——
    拿请求线程的快照反而是旧的。

    `on_progress` 只有生成管线用（它得往上一步的进度条上报）；按钮那条路不传 ——
    前端看清单里的 `readyCount` 就够，不必为此多开一条通道。
    """
    course = db.session.get(Course, course_id)
    if course is None:
        logger.warning("预合成：课程不存在或已删除 course=%s", course_id)
        return {"enabled": False, "reason": "course_not_found", "courseId": course_id}

    settings = voice_prefs.narration_settings(course)
    if not settings.usable:
        # 不是错误：这个部署根本没配音色。接口层已经用清单说过原因了。
        logger.info("预合成：没有可用音色，跳过 course=%s", course_id)
        return {"enabled": False, "reason": "voice_not_configured", "courseId": course_id}

    provider = voice_prefs.tts_provider()
    report: dict[str, Any] = assets.narrate(
        course,
        settings,
        provider=provider,
        page_no=page_no,
        force=force,
        on_progress=on_progress,
    )
    logger.info(
        "预合成结束 course=%s 共%d句 新合成%d 命中缓存%d 失败%d",
        course_id,
        report.get("total", 0),
        report.get("synthesized", 0),
        report.get("cached", 0),
        len(report.get("failed") or []),
    )
    return report


__all__ = ["KEY_PREFIX", "is_running", "run", "submit", "task_key"]
