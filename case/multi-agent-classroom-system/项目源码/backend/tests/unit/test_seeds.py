"""种子数据测试（F0-11 / P0-C5 / P1-7）。

要求：
- 3 个内置音色 + 1 名教师 + 3 名 AI 同学 + **2 门**示例课程（P1-7）
- 幂等：反复灌不产生重复，也不重置用户改过的字段
- 音色 ID 来自配置，代码里不出现厂商字面量（AGENTS.md §4.1）
- 示例课与生成课**同形**：页面过 `schema.validate_page`，`dsl_json`
  由 `store.rebuild_dsl` 从页面行重算（P1-C1）
"""

from __future__ import annotations

import pytest

from app.extensions import db

pytestmark = pytest.mark.unit

#: P1-7 的两门官方示例课。写死 id 是有意的：课程 id 一改，
#: 用户本地库里就会多出一门重复的课（老 id 的那门还在）。
DEMO_COURSE_IDS = ("course_demo_ml", "course_demo_photosynthesis")


VOICE_ENV = {
    "VOLC_TTS_VOICE_TEACHER": "vendor-teacher-voice-id",
    "VOLC_TTS_VOICE_HISTORY": "vendor-history-voice-id",
    "VOLC_TTS_VOICE_SCIENCE": "vendor-science-voice-id",
}


@pytest.fixture()
def seeded(app_factory):
    """灌一遍种子，返回 app。音色 ID 在建 app 之前注入（配置是启动时快照）。"""
    from app.seeds import run_seed

    application = app_factory(env=VOICE_ENV)
    run_seed()
    return application


def test_seed_creates_one_teacher_and_three_classmates(seeded):
    from app.models import AgentRole

    with seeded.app_context():
        teachers = AgentRole.query.filter_by(role="teacher").all()
        students = AgentRole.query.filter_by(role="student").all()

    assert len(teachers) == 1, "只能有一位主讲老师"
    assert len(students) == 3, f"应有 3 名 AI 同学，实际 {len(students)}"

    names = {s.name for s in students}
    assert names == {"林晓", "陈默", "苏雨"}, names
    assert teachers[0].name == "沈老师"


def test_seed_creates_three_builtin_voices(seeded):
    from app.models import VoiceProfile

    with seeded.app_context():
        voices = VoiceProfile.query.filter_by(builtin=True).all()

    assert len(voices) == 3
    assert {v.name for v in voices} == {"沈老师", "顾老师", "陆老师"}

    for voice in voices:
        assert voice.provider, f"{voice.name} 缺少 provider"
        assert voice.gender in {"male", "female"}, voice.gender
        assert voice.style, f"{voice.name} 缺少风格描述"


def test_seed_reads_vendor_voice_ids_from_config(seeded):
    """音色 ID 一律配置化 —— 换一个火山账号只需改 .env，不改代码。"""
    from app.models import VoiceProfile

    with seeded.app_context():
        shen = VoiceProfile.query.filter_by(name="沈老师").one()
        gu = VoiceProfile.query.filter_by(name="顾老师").one()
        lu = VoiceProfile.query.filter_by(name="陆老师").one()

    assert shen.voice_type == "vendor-teacher-voice-id"
    assert gu.voice_type == "vendor-history-voice-id"
    assert lu.voice_type == "vendor-science-voice-id"


def test_seed_leaves_voice_id_blank_when_unconfigured(app_factory):
    """没配音色 ID 时要诚实留空，而不是塞一个占位值假装能用。"""
    from app.models import VoiceProfile
    from app.seeds import run_seed

    app_factory(unset=tuple(VOICE_ENV))
    run_seed()

    voices = VoiceProfile.query.all()
    assert len(voices) == 3
    assert all(v.voice_type == "" for v in voices)
    assert all(v.configured is False for v in voices)


def test_seed_links_roles_to_voice_profiles(seeded):
    """主讲老师必须有音色，否则课堂演示时第一句就哑了。"""
    from app.models import AgentRole, VoiceProfile

    with seeded.app_context():
        teacher = AgentRole.query.filter_by(role="teacher").one()
        assert teacher.voice_profile_id, "主讲老师未绑定音色"

        voice = db.session.get(VoiceProfile, teacher.voice_profile_id)
        assert voice is not None

        # 三名同学也必须各绑一个音色，否则讨论环节无法区分谁在说话
        for student in AgentRole.query.filter_by(role="student").all():
            assert student.voice_profile_id, f"{student.name} 未绑定音色"


def test_seed_creates_two_demo_courses(seeded):
    from app.models import Course, CoursePage

    with seeded.app_context():
        courses = Course.query.all()
        assert len(courses) == 2, f"示例课程应有 2 门，实际 {len(courses)}"
        assert {c.id for c in courses} == set(DEMO_COURSE_IDS)

        for course in courses:
            assert course.title, f"{course.id} 没有标题"
            assert course.topic, f"{course.id} 没有主题"
            assert course.status == "ready", "示例课程必须是可直接演示的状态"

            pages = CoursePage.query.filter_by(course_id=course.id).all()
            assert len(pages) >= 3, "示例课程至少要能翻几页"
            assert [p.page_no for p in sorted(pages, key=lambda p: p.page_no)] == list(
                range(1, len(pages) + 1)
            ), "页码必须从 1 开始连续"


def test_demo_course_has_an_owner(seeded):
    from app.models import Course, User

    with seeded.app_context():
        courses = Course.query.all()

        for course in courses:
            owner = db.session.get(User, course.owner_id)
            assert owner is not None, "课程必须归属某个用户，否则越权校验无从谈起"
            assert owner.role == "teacher"


def test_demo_course_page_count_matches_actual_pages(seeded):
    """冗余的 page_count 必须和真实页数一致，否则工作台列表会骗人。"""
    from app.models import Course, CoursePage

    with seeded.app_context():
        for course in Course.query.all():
            actual = CoursePage.query.filter_by(course_id=course.id).count()
            assert course.page_count == actual, course.id


def test_demo_courses_are_shaped_like_generated_ones(seeded):
    """示例课与生成课必须同形，否则前端得为「两种课」各写一套渲染。

    这条是 P1-7 的底线：页面正文走的是同一个 `validate_page`（所以有
    beat 编号、每页 3 条要点），`dsl_json` 走的是同一个 `rebuild_dsl`
    （所以 `chapters[].pages` 与页面行、`dsl.pages` 三者互相推得出来）。
    """
    from app.models import Course, CoursePage

    with seeded.app_context():
        for course in Course.query.all():
            pages = CoursePage.query.filter_by(course_id=course.id).order_by(
                CoursePage.page_no
            ).all()
            dsl = course.dsl or {}

            # 1) 每一页都有 beat（P0 的旧形状是整段字符串，前端渲染不出来）
            for page in pages:
                beats = page.dsl.get("narration") or []
                assert beats, f"{course.id} 第 {page.page_no} 页没有讲稿"
                assert all(beat.get("beatId") and beat.get("estSec") for beat in beats), (
                    f"{course.id} 第 {page.page_no} 页的 beat 没编号或没估时"
                )
                assert len(page.dsl.get("bullets") or []) >= 3, page.page_no

            # 2) 三处页号必须一致：章节 → 页面行 → dsl.pages
            assert [item["pageNo"] for item in dsl.get("pages") or []] == [
                page.page_no for page in pages
            ], f"{course.id} 的 dsl.pages 与页面行对不上"
            for chapter in dsl.get("chapters") or []:
                expected = [p.page_no for p in pages if p.chapter_no == chapter["no"]]
                assert chapter["pages"] == expected, (
                    f"{course.id} 第 {chapter['no']} 章的页号与页面行对不上"
                )

            # 3) 封面页写下的东西就是课程卡片上的东西
            assert course.cover.get("lecturer"), f"{course.id} 封面没有讲师"
            assert course.cover.get("durationMin"), f"{course.id} 封面没有时长"
            assert course.duration_min == course.cover["durationMin"], (
                "卡片时长与封面时长必须是同一个数"
            )


def test_demo_course_pages_have_a_seed_version(seeded):
    """每一页都要有 V1（reason=seed）：用户第一次重写它时才退得回去。

    `seed` 不是 generate 也不是 manual —— 这几页是手写的素材，
    记成那两个都会让版本表说谎。
    """
    from app.models import Course, CoursePage, CoursePageVersion

    with seeded.app_context():
        count = 0
        for course in Course.query.all():
            for page in CoursePage.query.filter_by(course_id=course.id).all():
                version = CoursePageVersion.query.filter_by(page_id=page.id).one()
                assert version.rev == page.rev == 1
                assert version.reason == "seed"
                assert version.dsl == page.dsl, "版本内容必须与页面一致"
                count += 1

    assert count == 24, f"两门示例课应有 24 页各有 1 条版本，实际 {count}"


def test_seed_is_idempotent(seeded):
    """反复灌种子不能产生重复行。"""
    from app.models import AgentRole, Course, CoursePage, User, VoiceProfile
    from app.seeds import run_seed

    with seeded.app_context():
        before = (
            AgentRole.query.count(),
            VoiceProfile.query.count(),
            Course.query.count(),
            CoursePage.query.count(),
            User.query.count(),
        )

    with seeded.app_context():
        run_seed()
        run_seed()

    with seeded.app_context():
        after = (
            AgentRole.query.count(),
            VoiceProfile.query.count(),
            Course.query.count(),
            CoursePage.query.count(),
            User.query.count(),
        )

    assert before == after, f"重复灌种子产生了重复数据：{before} → {after}"


def test_seed_preserves_user_edits(seeded):
    """用户改过的行不能被下一次 seed 覆盖回去。"""
    from app.models import AgentRole
    from app.seeds import run_seed

    with seeded.app_context():
        role = AgentRole.query.filter_by(code="xiaoxiao").one()
        role.name = "小林"
        db.session.commit()

    with seeded.app_context():
        run_seed()

    with seeded.app_context():
        assert AgentRole.query.filter_by(code="xiaoxiao").one().name == "小林"


def test_seed_does_not_rewrite_created_at(seeded):
    from app.models import AgentRole
    from app.seeds import run_seed

    with seeded.app_context():
        created = AgentRole.query.filter_by(code="shen").one().created_at

    with seeded.app_context():
        run_seed()

    with seeded.app_context():
        assert AgentRole.query.filter_by(code="shen").one().created_at == created


def test_seed_is_safe_on_empty_database(app_factory):
    """空库直接灌不能报错（首次部署路径）。"""
    from app.models import AgentRole
    from app.seeds import run_seed

    app_factory(env=VOICE_ENV)
    run_seed()

    assert AgentRole.query.count() == 4


def test_seed_returns_a_summary(seeded):
    """脚本与验收脚本要打印灌了什么，返回值必须可读。"""
    from app.seeds import run_seed

    with seeded.app_context():
        summary = run_seed()

    assert isinstance(summary, dict)
    assert summary["agentRoles"] == 4
    assert summary["voiceProfiles"] == 3
    assert summary["courses"] == 2
    assert summary["coursePages"] == 24


def test_seed_registers_flask_cli_command(app):
    """`flask seed` 必须可用（P0 §3 交付物 / Makefile 依赖它）。"""
    assert "seed" in app.cli.commands


def test_demo_course_pages_have_titles_and_kinds(seeded):
    from app.models import PAGE_KINDS, PAGE_STATUSES, Course, CoursePage

    with seeded.app_context():
        for course in Course.query.all():
            pages = CoursePage.query.filter_by(course_id=course.id).all()

            for page in pages:
                assert page.title, f"第 {page.page_no} 页没有标题"
                # 用常量而不是抄一份字面量：页型表从 P0 的四值扩到 P1 的九值时，
                # 抄来的那份不会跟着变 —— 于是测试开始为一个已经不存在的规定报警。
                assert page.kind in PAGE_KINDS, page.kind
                assert page.status in PAGE_STATUSES, page.status


def test_demo_courses_cover_the_renderable_kinds(seeded):
    """两门示例课加起来要踩到七种页型。

    P1 §3.2 有九种，缺的两种是有理由的：`debate` 只在研讨模式出现，而这两门
    都是讲授模式；`code` 属于课程内容 —— 光合作用那门不该有代码页，硬塞一页
    只是为了让页型表好看。要演示这两种，用离线桩生成一门对应的课即可
    （桩认得出 `debate` / `code` 两种页型的任务头）。
    """
    from app.models import Course, CoursePage

    with seeded.app_context():
        kinds: set[str] = set()
        for course in Course.query.all():
            kinds |= {
                page.kind for page in CoursePage.query.filter_by(course_id=course.id)
            }

    assert kinds == {
        "cover", "outline", "concept", "figure", "example", "quiz", "summary",
    }, f"示例课踩到的页型：{sorted(kinds)}"
