"""后台任务器（P1-B1 立即返回 / P1-F4 不留线程）。

这一层不生成内容，只负责「把活儿丢给谁」。所以断言的都是**没能变成功能的那类错**：

- 同一个 job 起两个线程 → 页码与版本号写乱（不是慢，是错）
- 工作线程没有 app context → 第一个 `db.session` 就炸
- 线程跟着任务数一起涨 → 跑一晚上就把进程耗死（P1-F4 量的就是这条）
"""

from __future__ import annotations

import threading
import time

import pytest

from app.common import tasks
from app.extensions import db

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_runner(app):
    """测试之间关掉池：线程是进程级资源，不跟着 app 夹具消失。"""
    yield
    tasks.shutdown_runner(app)


def test_submit_runs_the_callable_in_a_worker_thread(app):
    runner = tasks.get_runner(app)
    seen: dict = {}
    gate = threading.Event()

    runner.submit("k1", lambda: (seen.update(thread=threading.current_thread().name),
                                 gate.set()))
    assert gate.wait(5), "任务没跑起来"
    assert seen["thread"].startswith(tasks.THREAD_PREFIX)


def test_the_same_key_is_never_run_twice_at_once(app):
    """同一门课的两次生成同时跑，会把页码和版本号写乱 —— 拒绝，而不是排队。"""
    runner = tasks.get_runner(app)
    release = threading.Event()
    started = threading.Event()

    assert runner.submit("job-1", lambda: (started.set(), release.wait(5))) is True
    assert started.wait(5)

    assert runner.submit("job-1", lambda: None) is False, "第二次提交必须被拒绝"
    assert runner.is_running("job-1")

    release.set()
    assert runner.wait("job-1", 5)
    assert not runner.is_running("job-1")
    assert runner.submit("job-1", lambda: None) is True, "跑完之后可以再接新的"


def test_worker_gets_an_app_context(app):
    """Flask 的上下文是线程局部的：工作线程不自己推一个，库根本进不去。"""
    from flask import current_app

    runner = tasks.get_runner(app)
    box: dict = {}
    done = threading.Event()

    def work() -> None:
        box["app"] = current_app.name
        box["db"] = db.session is not None
        db.session.execute(db.text("SELECT 1"))
        done.set()

    runner.submit("k2", work)

    assert done.wait(5)
    assert box["app"] == app.name
    assert box["db"] is True


def test_a_failing_task_does_not_kill_the_pool(app):
    """管线自己会把失败写进 gen_jobs.error；线程不能带着异常退出。"""
    runner = tasks.get_runner(app)
    after = threading.Event()

    runner.submit("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    runner.submit("good", after.set)
    assert runner.wait("bad", 5), "异常的任务也要有个终点"

    assert after.wait(5), "一个任务失败不该拖住后面的任务"
    assert runner.running_keys() == set()


def test_threads_do_not_grow_with_the_number_of_jobs(app):
    """P1-F4：跑了很多任务之后，活着的线程数回到池子上限以内。"""
    runner = tasks.get_runner(app)
    assert runner.stats()["workers"] >= 1

    for index in range(12):
        assert runner.submit(f"job-{index}", lambda: None) is True
        assert runner.wait(f"job-{index}", 5)

    # 给线程池一点时间把工作线程收回空闲态
    for _ in range(50):
        time.sleep(0.02)
        if tasks.thread_count() <= runner.stats()["workers"]:
            break
    assert tasks.thread_count() <= runner.stats()["workers"], "线程数跟着任务数涨了"
    assert runner.running_keys() == set()


def test_worker_count_comes_from_the_environment(app_factory):
    application = app_factory(env={"GEN_WORKERS": "2"})
    try:
        assert tasks.get_runner(application).stats()["workers"] == 2
    finally:
        tasks.shutdown_runner(application)


def test_shutdown_is_idempotent(app):
    runner = tasks.get_runner(app)
    runner.shutdown()
    tasks.shutdown_runner(app)  # 再关一次不该炸

    with pytest.raises(RuntimeError):
        runner.submit("after-close", lambda: None)


# --- 生成任务的两个入口（P1-B1 / P1-A8）---


def test_submit_job_runs_the_pipeline_in_the_background(app):
    """`POST /api/courses/generate` 要立刻返回，跑的是这里起的那条线程。"""
    from app.services.courses import store
    from app.services.generation.pipeline import DEFAULT_OPTIONS, start_job
    from tests.unit.test_generation_pipeline import StubLLM

    course = store.create_course(title="机器学习入门", topic="机器学习入门", options=DEFAULT_OPTIONS)
    job = start_job(course, options=DEFAULT_OPTIONS)

    assert tasks.submit_job(job.id, llm=StubLLM()) is True
    assert tasks.wait_for(job.id, 30), "任务没跑完"

    db.session.expire_all()
    assert job.status == "done"
    assert job.progress == 100
    assert store.pages_of(course), "页面是工作线程写进去的"


def test_submit_retry_reruns_the_failed_step_in_the_background(app):
    from app.services.courses import store
    from app.services.generation.pipeline import DEFAULT_OPTIONS, start_job, step_of
    from tests.unit.test_generation_pipeline import StubLLM

    course = store.create_course(title="机器学习入门", topic="机器学习入门", options=DEFAULT_OPTIONS)
    job = start_job(course, options=DEFAULT_OPTIONS)
    assert tasks.submit_job(job.id, llm=StubLLM(fail_pages={3})) is True
    assert tasks.wait_for(job.id, 30)

    db.session.expire_all()
    assert job.status == "failed"
    write = step_of(job, "write")
    assert write.status == "failed"

    assert tasks.submit_retry(job.id, write.id, llm=StubLLM()) is True
    assert tasks.wait_for(job.id, 30)

    db.session.expire_all()
    assert job.status == "done", "重试之后整条管线跑完"
    assert all(page.status == "ready" for page in store.pages_of(course))
