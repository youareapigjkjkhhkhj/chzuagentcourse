"""P2 数据模型测试（P2 §5 / P2-C1 / P2-C2 / P2-C4）。

两张表各管一件事，断言也照这两件事写：

- `audio_assets` 是**缓存索引**：键错了会重复合成（花两份钱、出两份文件），
  失效判据错了会让学生听到与字幕对不上的声音 —— 后者比没声音更糟。
- `usage_records` 是**账**：它不在业务数据的级联链上，删课不能把钱也删了。

外加 P2-C4 的路径约束与音色档案的两列新字段（试听缓存 / 合成参数）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db

pytestmark = pytest.mark.unit

VOICE_TABLES = {"audio_assets", "usage_records"}


def test_voice_tables_exist(app):
    with app.app_context():
        names = set(inspect(db.engine).get_table_names())

    missing = VOICE_TABLES - names
    assert not missing, f"缺少表：{missing}"


def test_every_voice_table_has_timestamps(app):
    with app.app_context():
        inspector = inspect(db.engine)

        for table in sorted(VOICE_TABLES):
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert "created_at" in columns, f"{table} 缺少 created_at"
            assert "updated_at" in columns, f"{table} 缺少 updated_at"


# --- audio_assets：缓存索引 ---


def test_same_beat_and_params_have_exactly_one_asset(app):
    """(course, beat, voice, speed, tone) 唯一（P2 §5）—— 否则同一句话会合成两遍。"""
    from app.models import AudioAsset

    with app.app_context():
        course = _course()
        db.session.add(_asset(course.id))
        db.session.commit()

        db.session.add(_asset(course.id))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        assert AudioAsset.query.count() == 1


def test_a_different_speed_is_a_different_asset(app):
    """换个语速就是另一份文件，不该被唯一约束误伤 —— 证明拒的是重复而不是任何修改。"""
    from app.models import AudioAsset

    with app.app_context():
        course = _course()
        db.session.add(_asset(course.id))
        db.session.add(_asset(course.id, speed=20))
        db.session.add(_asset(course.id, voice_id="vp_teacher_gu"))
        db.session.commit()

        assert AudioAsset.query.filter_by(course_id=course.id).count() == 3


def test_hash8_is_the_filename_fragment(app):
    """文件名用的是哈希前 8 位：文字没变时重算也是同一个名字（缓存的前提）。"""

    with app.app_context():
        asset = _asset(_course().id, text_hash="0123456789abcdef")
        assert asset.hash8 == "01234567"

        # 文字改了 → 哈希变了 → 文件名也换一个，不会覆盖正在播的那份
        asset.text_hash = "fedcba9876543210"
        assert asset.hash8 == "fedcba98"


def test_only_a_ready_asset_with_a_file_is_available(app):
    """`available` 是给播放器看的判据：三个状态里只有「文件在、内容对」能播。"""

    with app.app_context():
        ready = _asset(_course().id)
        assert ready.available

        stale = _asset(_course().id, beat_id="p1-b2", status="stale")
        assert not stale.available, "stale 说明内容对不上，不能拿去播"

        failed = _asset(_course().id, beat_id="p1-b3", status="failed", file_path="")
        assert not failed.available, "合成失败过的没有文件可播"

        # ready 但文件路径空着（人工改库/写到一半崩了）也不能播
        ready.file_path = ""
        assert not ready.available


def test_unknown_status_is_rejected(app):

    with app.app_context():
        db.session.add(_asset(_course().id, status="done"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


@pytest.mark.parametrize(
    "path",
    [
        "/var/lib/eduagentx/a.mp3",  # POSIX 绝对路径
        "C:/Users/tom/audio/a.mp3",  # Windows 绝对路径：反向的「不以 / 开头」拦不住它
        "data/assets/audio/../outside.mp3",  # 相对，但指向音频目录之外
        "data/uploads/a.mp3",  # 相对，但在别的目录里
    ],
)
def test_absolute_or_foreign_paths_are_rejected(app, path: str):
    """P2-C4：路径必须落在音频目录下且相对 —— 换机器只需改 AUDIO_DIR。"""

    with app.app_context():
        db.session.add(_asset(_course().id, file_path=path))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_negative_duration_or_size_is_rejected(app):

    with app.app_context():
        db.session.add(_asset(_course().id, duration_ms=-1))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(_asset(_course().id, size_bytes=-1))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_deleting_a_course_takes_its_assets_but_not_the_usage_ledger(app):
    """P2-C2 与「账本不随业务数据消失」是两条相反的规则，这里一次验完。"""
    from app.models import AudioAsset, Course, UsageRecord

    with app.app_context():
        course = _course()
        db.session.add(_asset(course.id))
        db.session.add(
            UsageRecord(
                kind="tts",
                provider="volc_tts",
                units=42,
                unit_name="chars",
                ref_type="course",
                ref_id=course.id,
            )
        )
        db.session.commit()

        db.session.delete(course)
        db.session.commit()

        assert AudioAsset.query.count() == 0, "缓存索引该随课程一起清掉（P2-C2）"
        assert Course.query.count() == 0
        assert UsageRecord.query.count() == 1, "课删了，这几次合成的钱也是真花了"


# --- usage_records：账 ---


def test_units_always_come_with_their_unit(app):
    """1200 个字符还是 1200 秒，价差是数量级的 —— 数值与单位必须一起存。"""
    from app.models import UsageRecord

    with app.app_context():
        db.session.add(
            UsageRecord(kind="tts", provider="volc_tts", units=1200, unit_name="chars")
        )
        db.session.add(
            UsageRecord(kind="realtime", provider="volc_realtime", units=120, unit_name="seconds")
        )
        db.session.commit()

        kinds = {row.kind: row.unit_name for row in UsageRecord.query.all()}
        assert kinds == {"tts": "chars", "realtime": "seconds"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "llm"),  # token 走 model_calls，不进这张表
        ("unit_name", "tokens"),
        ("ref_type", "page"),
    ],
)
def test_enum_columns_are_enforced(app, field: str, value: str):
    from app.models import UsageRecord

    with app.app_context():
        db.session.add(UsageRecord(**{"kind": "tts", "unit_name": "chars", field: value}))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_negative_units_or_cost_is_rejected(app):
    from app.models import UsageRecord

    with app.app_context():
        db.session.add(UsageRecord(kind="tts", units=-1))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(UsageRecord(kind="tts", est_cost=-0.01))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_usage_is_queryable_by_ref(app):
    """P2-C3：按 course / session 关联查得动 —— 设置页「本次课堂用量」靠它。"""
    from app.models import UsageRecord

    with app.app_context():
        db.session.add(
            UsageRecord(kind="tts", units=100, unit_name="chars", ref_type="course", ref_id="c1")
        )
        db.session.add(
            UsageRecord(
                kind="realtime", units=30, unit_name="seconds", ref_type="session", ref_id="s1"
            )
        )
        db.session.commit()

        by_course = UsageRecord.query.filter_by(ref_type="course", ref_id="c1").all()
        by_session = UsageRecord.query.filter_by(ref_type="session", ref_id="s1").all()
        assert [r.units for r in by_course] == [100]
        assert [r.units for r in by_session] == [30]


def test_to_dict_strips_the_float_tail(app):
    """金额是估算值，出参时收敛到 6 位小数 —— `0.30000000000000004` 不该出现在接口里。

    代价是小于 1e-6 元的金额会被抹成 0，这个量级（十万分之一分）本来就没有意义。
    """
    from app.models import UsageRecord

    with app.app_context():
        db.session.add(UsageRecord(kind="tts", units=3, unit_name="chars", est_cost=0.1 + 0.2))
        db.session.commit()

        assert UsageRecord.query.one().to_dict()["estCost"] == 0.3


# --- voice_profiles：P2 新列 ---


def test_voice_profile_keeps_preview_cache_and_params(app):
    """试听缓存（P2-A5）与合成参数：一个存 URL，一个存 dict。"""
    from app.models import VoiceProfile

    with app.app_context():
        voice = VoiceProfile(
            id="vp_teacher_shen",
            name="沈老师",
            provider="volc_tts",
            voice_type="zh_male_x",
            params={"pronunciation": {"卷积": "juǎn jī"}},
        )
        db.session.add(voice)
        db.session.commit()

        db.session.expire_all()
        stored = db.session.get(VoiceProfile, "vp_teacher_shen")
        assert stored.preview_url is None, "还没试听过，不该有一个指向不存在文件的 URL"
        assert stored.params == {"pronunciation": {"卷积": "juǎn jī"}}
        assert stored.to_dict()["params"]["pronunciation"]["卷积"] == "juǎn jī"
        assert stored.to_dict()["previewUrl"] == ""

        stored.preview_url = "/api/voice/voices/vp_teacher_shen/preview.mp3"
        db.session.commit()
        assert db.session.get(VoiceProfile, "vp_teacher_shen").to_dict()["previewUrl"].endswith(
            "preview.mp3"
        )


def test_corrupt_params_json_degrades_instead_of_raising(app):
    """一条脏 JSON 只该让这个字段变空，不该让整个设置页 500（JSONField 的口径）。"""
    from app.models import VoiceProfile

    with app.app_context():
        voice = VoiceProfile(id="vp_teacher_gu", name="顾老师", provider="volc_tts")
        db.session.add(voice)
        db.session.commit()

        db.session.execute(
            db.text("UPDATE voice_profiles SET params_json = '{坏掉的' WHERE id = 'vp_teacher_gu'")
        )
        db.session.commit()
        db.session.expire_all()

        assert db.session.get(VoiceProfile, "vp_teacher_gu").params is None


def _course():
    """建一门最小可用的课，返回已提交的 Course。"""
    from app.models import Course

    course = Course(title="机器学习入门", topic="机器学习入门", status="generating")
    db.session.add(course)
    db.session.commit()
    return course


def _asset(
    course_id: str,
    *,
    beat_id: str = "p1-b1",
    text_hash: str = "0123456789abcdef",
    voice_id: str = "vp_teacher_shen",
    speed: int = 0,
    tone: str = "",
    file_path: str = "data/assets/audio/c1/p1-b1_01234567.mp3",
    duration_ms: int = 3200,
    size_bytes: int = 51200,
    status: str = "ready",
):
    from app.models import AudioAsset

    return AudioAsset(
        course_id=course_id,
        page_no=1,
        beat_id=beat_id,
        text_hash=text_hash,
        voice_id=voice_id,
        speed=speed,
        tone=tone,
        file_path=file_path,
        duration_ms=duration_ms,
        size_bytes=size_bytes,
        status=status,
    )
