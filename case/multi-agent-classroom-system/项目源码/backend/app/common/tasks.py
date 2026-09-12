"""后台任务器（P1-B1 立即返回 / P1-F4 不留线程）。

生成是分钟级的事：接口层必须 < 500ms 返回 `{courseId, jobId}`，进度靠 SSE 推。
所以「跑」这一步得离开请求线程。这一层只管四件事：

1. **提交**：一个 job 同时只有一个线程在跑（重复提交返回 False，不排队）。
   这条不是优化而是正确性：两个线程同时写同一门课的页面，页码与版本号都会乱。
2. **上下文**：工作线程自己推 app context。Flask 的上下文是线程局部的，
   主线程里的 `current_app` 到了子线程就是空代理 —— 库还不等它访问就会炸。
3. **收尾**：跑完 remove 掉 session（放掉 SQLite 连接），并把异常关在线程里。
   管线自己会把失败写进 `gen_jobs.error`，所以这里只记日志、不往上抛：
   抛给谁呢？请求线程早就返回了。
4. **回收**：进程退出时关池。线程池是有界的（`GEN_WORKERS`），
   跑一百个任务也不会多出一百个线程 —— P1-F4 量的就是这条。

没用 Celery 之类的队列是刻意的：单机 SQLite 的部署形态下，进程内线程池
就是全部并发；要扩容时换的是这一层，管线不用动（它本来就只认「谁调我」）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from flask import Flask, has_app_context

from app.common.context import real_app
from app.common.logging import get_logger
from app.extensions import db

logger = get_logger("app.tasks")

#: 工作线程名前缀。测试与 `stats()` 靠它把「我们的线程」从别的线程里认出来。
THREAD_PREFIX = "eduagentx-gen"

#: 默认并发。比生成并发（默认 3）稍大：写页是 IO 等待型，
#: 真正压在 CPU/SQLite 上的只有落库那一瞬。P1-D5 要求 3 门课并行时不互相拖垮。
DEFAULT_WORKERS = 4

#: 存 TaskRunner 的地方（app.extensions 键名）。一个应用一个池。
EXTENSION_KEY = "task_runner"


class TaskRunner:
    """进程内线程池 + 「同一个 job 不并发」的登记表。"""

    def __init__(self, app: Flask, *, workers: int | None = None) -> None:
        self._app = app
        size = int(workers or app.config.get("GEN_WORKERS") or DEFAULT_WORKERS)
        self._workers = max(1, size)
        self._pool = ThreadPoolExecutor(
            max_workers=self._workers, thread_name_prefix=THREAD_PREFIX
        )
        self._lock = threading.Lock()
        #: key -> 该 key 跑完时被 set 的事件。存事件而不是 Future：
        #: 我们要的就是「等它跑完」，不需要结果（结果在库里）。
        self._running: dict[str, threading.Event] = {}
        self._closed = False

    # --- 提交与查询 ---

    def submit(self, key: str, fn: Callable[[], Any]) -> bool:
        """把 fn 丢进池子。已有同名任务在跑则返回 False（不排队、不覆盖）。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("任务器已关闭，无法提交新任务")
            if key in self._running:
                return False
            done = threading.Event()
            self._running[key] = done
        try:
            self._pool.submit(self._guard, key, fn, done)
        except RuntimeError:  # pragma: no cover - 池在极窄的窗口里被关掉
            with self._lock:
                self._running.pop(key, None)
            done.set()
            raise
        return True

    def is_running(self, key: str) -> bool:
        with self._lock:
            return key in self._running

    def running_keys(self) -> set[str]:
        with self._lock:
            return set(self._running)

    def wait(self, key: str, timeout: float | None = None) -> bool:
        """等某个 key 跑完（测试与「关闭时排空」用）。没在跑立刻返回 True。"""
        with self._lock:
            done = self._running.get(key)
        if done is None:
            return True
        return bool(done.wait(timeout))

    def stats(self) -> dict:
        with self._lock:
            running = sorted(self._running)
        return {
            "workers": self._workers,
            "running": running,
            "threads": thread_count(),
        }

    # --- 关闭 ---

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=wait)

    # --- 内部 ---

    def _guard(self, key: str, fn: Callable[[], Any], done: threading.Event) -> None:
        try:
            with self._app.app_context():
                try:
                    fn()
                except Exception:
                    # 堆栈只进服务端日志（AGENTS §19）：不带 locals，也不带提示词
                    logger.exception("后台任务失败 key=%s", key)
                finally:
                    db.session.remove()
        finally:
            with self._lock:
                self._running.pop(key, None)
            done.set()


def thread_count() -> int:
    """当前活着的生成线程数。P1-F4 的「线程数回落」量的是它。"""
    return sum(1 for thread in threading.enumerate() if thread.name.startswith(THREAD_PREFIX))


def get_runner(app: Flask | None = None) -> TaskRunner:
    """取当前应用的线程池，没有就建一个（懒建：create_app 不必碰线程）。"""
    target = app or real_app()
    runner = target.extensions.get(EXTENSION_KEY)
    if runner is None:
        runner = TaskRunner(target)
        target.extensions[EXTENSION_KEY] = runner
    return runner


def shutdown_runner(app: Flask | None = None, *, wait: bool = True) -> None:
    """关掉线程池（测试之间复位 / 进程退出）。没建过就什么都不做。"""
    target = app
    if target is None:
        if not has_app_context():  # pragma: no cover - 退出钩子里没有上下文
            return
        target = real_app()
    runner = target.extensions.pop(EXTENSION_KEY, None)
    if runner is not None:
        runner.shutdown(wait=wait)


# --- 生成任务的入口 ---


def submit_job(job_id: str, *, resume: bool = False, llm: Any = None) -> bool:
    """把一次生成丢到后台。返回 False 表示这个任务已经在跑了。"""
    from app.services.generation import pipeline

    return get_runner().submit(
        job_id, lambda: pipeline.run_job(job_id, llm=llm, resume=resume)
    )


def submit_retry(job_id: str, step_id: str, *, llm: Any = None) -> bool:
    """重试也走后台：重试要重写页面，照样是分钟级的事（P1-A8）。"""
    from app.services.generation import pipeline

    return get_runner().submit(job_id, lambda: pipeline.retry_step(job_id, step_id, llm=llm))


def wait_for(job_id: str, timeout: float | None = None) -> bool:
    """等这个任务跑完（测试与脚本用）。"""
    return get_runner().wait(job_id, timeout)


def active_jobs() -> set[str]:
    return get_runner().running_keys()


__all__ = [
    "DEFAULT_WORKERS",
    "EXTENSION_KEY",
    "THREAD_PREFIX",
    "TaskRunner",
    "active_jobs",
    "get_runner",
    "shutdown_runner",
    "submit_job",
    "submit_retry",
    "thread_count",
    "wait_for",
]
