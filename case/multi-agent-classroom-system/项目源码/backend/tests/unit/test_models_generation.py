"""P1 数据模型测试（P1 §5 / P1-C3 / AGENTS §4.5）。

P1 新增六张表：生成任务（gen_jobs）、任务步骤（gen_steps）、SSE 事件留档
（gen_events）、页面版本（course_page_versions），以及两张跨阶段记账表
model_calls 与 audit_logs —— 后者不在 P1 §5 的表里，但 AGENTS §4.5
「每一笔外部调用都必须写 model_calls」与 P1-F2「命中敏感词记 audit_logs」
要求它们在**第一次调用发生之前**就存在。表建在 P1，成本看板与配额留给 P5。

这些断言盯着三件容易悄悄退化的事：
- 唯一约束：seq 一旦重号，SSE 续传（Last-Event-ID）就补发错事件；
- 级联：删课留孤儿，是「删了还能查到」这类幽灵 bug 的来源；
- kind 九值：P0 的 CHECK 只认四个占位值，加页型必须同步迁移。
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db

pytestmark = pytest.mark.unit

GENERATION_TABLES = {
    "gen_jobs",
    "gen_steps",
    "gen_events",
    "course_page_versions",
    "model_calls",
    "audit_logs",
}

#: P1 §3.2 的九种页型
PAGE_KINDS = (
    "cover",
    "outline",
    "concept",
    "figure",
    "example",
    "code",
    "quiz",
    "summary",
    "debate",
)


def test_generation_tables_exist(app):
    with app.app_context():
        names = set(inspect(db.engine).get_table_names())

    missing = GENERATION_TABLES - names
    assert not missing, f"缺少表：{missing}"


def test_every_generation_table_has_timestamps(app):
    with app.app_context():
        inspector = inspect(db.engine)

        for table in sorted(GENERATION_TABLES):
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert "created_at" in columns, f"{table} 缺少 created_at"
            assert "updated_at" in columns, f"{table} 缺少 updated_at"


def test_seq_uniqueness_is_enforced(app):
    """同一 job 内 seq 必须唯一 —— SSE 的续传与回放全靠它。"""
    from app.models import Course, GenEvent, GenJob, GenStep

    with app.app_context():
        job = GenJob(course_id=_course().id, status="running")
        db.session.add(job)
        db.session.commit()

        db.session.add(GenStep(job_id=job.id, seq=1, type="parse", title="解析需求"))
        db.session.add(GenEvent(job_id=job.id, seq=1, event="job.start", payload_json="{}"))
        db.session.commit()

        db.session.add(GenStep(job_id=job.id, seq=1, type="outline", title="重复序号"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(GenEvent(job_id=job.id, seq=1, event="step.start", payload_json="{}"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        # 换个 seq 就能写进去，证明上面拒绝的是「重号」而不是别的
        db.session.add(GenStep(job_id=job.id, seq=2, type="outline", title="大纲"))
        db.session.commit()
        assert GenStep.query.filter_by(job_id=job.id).count() == 2
        assert Course.query.count() == 1


def test_page_version_rev_uniqueness(app):
    """同一页的 rev 唯一：版本链一旦重号，回滚就会回错版本（P1-C4）。"""
    from app.models import CoursePage, CoursePageVersion

    with app.app_context():
        course = _course()
        page = CoursePage(course_id=course.id, page_no=1, kind="concept", title="第一页")
        db.session.add(page)
        db.session.commit()

        db.session.add(CoursePageVersion(page_id=page.id, rev=1, reason="generate", dsl_json="{}"))
        db.session.commit()

        db.session.add(CoursePageVersion(page_id=page.id, rev=1, reason="rewrite", dsl_json="{}"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(CoursePageVersion(page_id=page.id, rev=2, reason="rewrite", dsl_json="{}"))
        db.session.commit()
        assert CoursePageVersion.query.filter_by(page_id=page.id).count() == 2


def test_all_nine_page_kinds_are_accepted(app):
    """P1 §3.2 的九种页型都要能落库 —— P0 的 CHECK 只认四个占位值。"""
    from app.models import CoursePage

    with app.app_context():
        course = _course()
        for index, kind in enumerate(PAGE_KINDS, start=1):
            db.session.add(
                CoursePage(course_id=course.id, page_no=index, kind=kind, title=f"{kind} 页")
            )
        db.session.commit()

        stored = {p.kind for p in CoursePage.query.all()}
        assert stored == set(PAGE_KINDS)


def test_unknown_page_kind_is_rejected(app):
    """放宽到九值不等于不校验：不在表里的页型仍要被数据库挡下。"""
    from app.models import CoursePage

    with app.app_context():
        course = _course()
        db.session.add(CoursePage(course_id=course.id, page_no=1, kind="not-a-kind", title="瞎写"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_deleting_course_leaves_no_orphans(app):
    """P1-C3：删课之后 pages / versions / steps / events / jobs 全部不留孤儿。"""
    from app.models import (
        CoursePage,
        CoursePageVersion,
        GenEvent,
        GenJob,
        GenStep,
    )

    with app.app_context():
        course = _course()
        page = CoursePage(course_id=course.id, page_no=1, kind="concept", title="第一页")
        db.session.add(page)
        db.session.commit()

        job = GenJob(course_id=course.id, status="done", progress=100, total_tokens=18320)
        db.session.add(job)
        db.session.commit()

        db.session.add(CoursePageVersion(page_id=page.id, rev=1, reason="generate", dsl_json="{}"))
        db.session.add(GenStep(job_id=job.id, seq=1, type="parse", title="解析"))
        db.session.add(GenEvent(job_id=job.id, seq=1, event="job.start", payload_json="{}"))
        db.session.commit()

        db.session.delete(course)
        db.session.commit()

        for model in (CoursePage, CoursePageVersion, GenJob, GenStep, GenEvent):
            assert model.query.count() == 0, f"{model.__name__} 留下了孤儿记录"


def test_model_call_records_every_field_the_cost_board_needs(app):
    """AGENTS §4.5：provider / model / tokens / latency / ok / error_code 一个都不能少。"""
    from app.models import ModelCall

    with app.app_context():
        call = ModelCall(
            kind="llm",
            provider="deepseek",
            model="deepseek-chat",
            tokens=1832,
            latency_ms=2410,
            ok=True,
        )
        db.session.add(call)
        db.session.commit()

        stored = ModelCall.query.one()
        assert (stored.kind, stored.provider, stored.model) == ("llm", "deepseek", "deepseek-chat")
        assert (stored.tokens, stored.latency_ms, stored.ok) == (1832, 2410, True)
        assert stored.error_code is None

        failed = ModelCall(
            kind="llm",
            provider="deepseek",
            model="deepseek-chat",
            latency_ms=60000,
            ok=False,
            error_code="upstream_timeout",
        )
        db.session.add(failed)
        db.session.commit()
        assert ModelCall.query.filter_by(ok=False).one().error_code == "upstream_timeout"


def test_job_progress_stays_in_range(app):
    """进度是百分比：越界的值进库后前端进度环会画出鬼来。"""
    from app.models import GenJob

    with app.app_context():
        job = GenJob(course_id=_course().id, status="running", progress=101)
        db.session.add(job)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_job_status_enum_is_enforced(app):
    from app.models import GenJob

    with app.app_context():
        job = GenJob(course_id=_course().id, status="finished")
        db.session.add(job)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def _course():
    """建一门最小可用的课，返回已提交的 Course。"""
    from app.models import Course

    course = Course(title="机器学习入门", topic="机器学习入门", status="generating")
    db.session.add(course)
    db.session.commit()
    return course
