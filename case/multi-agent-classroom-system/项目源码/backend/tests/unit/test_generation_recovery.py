"""重启收拾「还在生成中」的任务（P1-C5）。

进程一重启，跑任务的线程就没了，可库里的状态还停在 `running` ——
前端会永远显示一个不动的进度环，而用户没有任何办法把它推下去。
所以启动时得有人把它们改成「失败了，可以重试」。

有两条容易做错的边界，各有用例盯着：
- **别动 paused**：等用户确认大纲的任务本来就该停在原地，不是残局
- **别删页面**：已经生成好的页面是花过钱的，重试时幂等检查会跳过它们
"""

from __future__ import annotations

import pytest

from app.common.dbw import db_write
from app.extensions import db
from app.models import Course, GenEvent, GenJob
from app.services.courses import store
from app.services.generation.pipeline import (
    DEFAULT_OPTIONS,
    RESTART_ERROR,
    recover_stuck_jobs,
    run_job,
    start_job,
    step_of,
)
from tests.unit.test_generation_pipeline import StubLLM

pytestmark = pytest.mark.unit


def _stuck(app, *, step_status: str = "running", job_status: str = "running"):
    """造一个「跑到一半进程没了」的现场。

    先真跑完一遍（页面是真的、版本是真的），再把它掰回「正在跑」的样子 ——
    这样才验得到「收拾状态时页面会不会跟着遭殃」。
    """
    course = store.create_course(title="机器学习入门", topic="机器学习入门", options=DEFAULT_OPTIONS)
    job = start_job(course, options=DEFAULT_OPTIONS)
    run_job(job.id, llm=StubLLM())
    ready = store.ready_pages(course)

    def _work() -> None:
        job.status = job_status
        job.error = ""
        course.status = "generating"
        if step_status:
            step_of(job, "write").status = step_status

    db_write(_work)
    return job, course, len(ready)


def test_a_job_left_running_by_a_restart_is_marked_failed(app):
    job, _course, _ready = _stuck(app)

    report = recover_stuck_jobs()

    db.session.expire_all()
    assert report["jobs"] == 1
    assert job.status == "failed"
    assert job.error == RESTART_ERROR, "要给出可重试的提示，而不是一句空错误"


def test_the_course_goes_with_it_but_keeps_its_pages(app):
    """课程一起置 failed，但页面留着 —— 重试时它们就是省下来的钱。"""
    _job, course, ready_count = _stuck(app)

    report = recover_stuck_jobs()

    db.session.expire_all()
    assert report["courses"] == 1
    assert course.status == "failed"
    assert len(store.ready_pages(course)) == ready_count > 0


def test_the_stuck_step_is_collected_too(app):
    """步骤停在 running 也要一起收，否则重试时它会从 wait 之外的地方开始。"""
    job, _course, _ready = _stuck(app)

    recover_stuck_jobs()

    db.session.expire_all()
    assert step_of(job, "write").status == "failed"


def test_the_recovery_is_written_to_the_event_log(app):
    """前端刷新页面时看到的是「失败了」，而不是永远等一个不会来的进度。"""
    job, _course, _ready = _stuck(app)

    recover_stuck_jobs()

    last = GenEvent.query.filter_by(job_id=job.id).order_by(GenEvent.seq.desc()).first()
    assert last.event == "job.failed"
    assert last.payload["recovered"] is True


def test_a_paused_job_is_left_alone(app):
    """等用户确认大纲的任务不是残局：它本来就该停着，用户点「继续」照样能跑。"""
    course = store.create_course(title="机器学习入门", topic="机器学习入门", options=DEFAULT_OPTIONS)
    job = start_job(course, options=DEFAULT_OPTIONS)
    db_write(lambda: setattr(job, "status", "paused"))

    assert recover_stuck_jobs() == {"jobs": 0, "courses": 0}

    db.session.expire_all()
    assert job.status == "paused"


def test_finished_jobs_are_untouched(app):
    _job, course, _ready = _stuck(app, step_status="", job_status="done")
    db_write(lambda: setattr(course, "status", "ready"))

    assert recover_stuck_jobs() == {"jobs": 0, "courses": 0}

    db.session.expire_all()
    assert course.status == "ready"


def test_running_it_twice_changes_nothing_the_second_time(app):
    _stuck(app)

    assert recover_stuck_jobs()["jobs"] == 1
    assert recover_stuck_jobs() == {"jobs": 0, "courses": 0}


def test_a_queued_job_is_collected_as_well(app):
    """排队中就被重启打断的任务同样不会自己动起来。"""
    _job, _course, _ready = _stuck(app, job_status="queued")

    assert recover_stuck_jobs()["jobs"] == 1


def test_the_app_factory_recovers_on_startup(app_factory):
    """收拾要挂在启动路径上 —— 没人会记得在部署脚本里手点一下。"""
    from tests.conftest import temp_database_uri

    uri = temp_database_uri()
    first = app_factory(database_uri=uri)
    job, _course, _ready = _stuck(first)
    job_id, course_id = job.id, _course.id
    assert db.session.get(GenJob, job_id).status == "running"
    db.session.remove()

    # 第二次启动（同一份数据文件）：进程重启的等价物
    app_factory(database_uri=uri)

    assert db.session.get(GenJob, job_id).status == "failed"
    assert db.session.get(Course, course_id).status == "failed"
