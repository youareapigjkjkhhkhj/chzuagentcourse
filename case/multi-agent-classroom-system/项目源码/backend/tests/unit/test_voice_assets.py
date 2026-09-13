"""音频资产管线测试（P2-A2 / A5 / A6 / A11 / C1 / C2 / C4 / G3）。

这一层要防住的是**静默的错**，所以断言都往「错了会不会有人发现」上写：

- 缓存键漏了一维 → 换了音色/换了模型还命中旧文件。听得出，但**不报错**，
  而且只在人耳能分辨音色时才发现。所以哈希的每一维都单独验一遍。
- 失效判据松了 → 学生听到上一版讲稿的声音，看着这一版的字幕。比没声音更糟。
- 失败不落库 → 前端只能看到「清单里少了一条」，得自己数数才知道缺什么。
- 测试往 `backend/data/` 里写音频 → 污染开发机上的真实课堂音频（conftest 里把
  `AUDIO_DIR` 指到临时目录，这里再验一次它确实生效）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.extensions import db
from app.providers.base import UpstreamError
from app.providers.tts.mock import MockTTS

pytestmark = pytest.mark.unit

VOICE_ENV = {
    "VOLC_TTS_VOICE_TEACHER": "vendor-teacher-voice-id",
    "VOLC_TTS_VOICE_HISTORY": "vendor-history-voice-id",
    "VOLC_TTS_VOICE_SCIENCE": "vendor-science-voice-id",
}

DEMO_COURSE = "course_demo_ml"


class FlakyTTS(MockTTS):
    """会失败的上游。`fail_on` 只挂含这段话的那些，`fail_all` 全挂。"""

    def __init__(self, fail_on: str = "", *, fail_all: bool = False, **options):
        super().__init__(**options)
        self.fail_on = fail_on
        self.fail_all = fail_all

    def synthesize(self, text, **options):
        if self.fail_all or (self.fail_on and self.fail_on in text):
            raise UpstreamError("上游挂了")
        return super().synthesize(text, **options)


class UnconfiguredTTS(MockTTS):
    """没填 Key 的服务商。用来验 40201 的信封形状。"""

    name = "volc_tts"

    @property
    def configured(self) -> bool:
        return False

    def missing_config(self) -> list[str]:
        return ["API Key"]


# --- 夹具 ---


@pytest.fixture()
def seeded(app_factory):
    """两门示例课 + 三个音色（音色 ID 走配置注入）。"""
    return app_factory(seed=True, env=VOICE_ENV)


def _teacher(app):
    from app.models import VoiceProfile

    with app.app_context():
        return VoiceProfile.query.filter_by(name="沈老师").one()


def _course(app, course_id: str = DEMO_COURSE):
    from app.models import Course

    with app.app_context():
        return db.session.get(Course, course_id)


def _settings(app, *, speed: float | None = None, tone: str = ""):
    from app.services.voice import assets

    return assets.settings_for(_teacher(app), speed=speed, tone=tone)


def _simple_course(*, texts: list[str], title: str = "语音测试课"):
    """直接铺一门最小课程的页面行（不走生成管线）。"""
    from app.models import Course, CoursePage
    from app.services.generation.schema import estimate_sec

    course = Course(title=title, topic=title, status="ready")
    db.session.add(course)
    db.session.flush()
    for index, text in enumerate(texts, start=1):
        page = CoursePage(
            course_id=course.id,
            chapter_no=1,
            page_no=index,
            kind="concept",
            title=f"第 {index} 页",
            status="ready",
            rev=1,
        )
        page.dsl = {
            "title": f"第 {index} 页",
            "kind": "concept",
            "bullets": [{"text": "要点", "emphasis": []}],
            "narration": [
                {"beatId": f"p{index}-b1", "text": text, "estSec": estimate_sec(text)}
            ],
        }
        db.session.add(page)
    db.session.commit()
    return course


# --- 缓存键 ---


def test_spec_hash_is_stable_and_independent_of_dict_order(app):
    """同样的规格算两次必须一样 —— 否则每次调用都「不命中」，缓存形同虚设。"""
    from app.services.voice import assets

    with app.app_context():
        first = assets.spec_hash("你好", voice="v1", pronunciation={"卷积": "juǎn jī", "重塑": "chóng sù"})
        second = assets.spec_hash("你好", voice="v1", pronunciation={"重塑": "chóng sù", "卷积": "juǎn jī"})

    assert first == second, "字典顺序不该影响哈希（Python 的 dict 是保序的，别依赖它）"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", "你好呀"),
        ("voice", "v2"),
        ("rate", 20),
        ("tone", "温柔"),
        ("version", "seed-tts-3.0"),
        ("provider", "other_tts"),
        ("fmt", "wav"),
        ("sample_rate", 16000),
        ("pronunciation", {"卷积": "juǎn jī"}),
    ],
)
def test_every_synthesis_dimension_changes_the_hash(app, field: str, value):
    """九个维度各改一项，哈希都必须变。

    漏掉哪一维，那一维的变化就**不会**触发重合成：换音色后学生继续听旧嗓子、
    上游换模型后继续吃上一代的缓存。这类问题的共同点是「不报错」。
    """
    from app.services.voice import assets

    base = {
        "text": "你好",
        "provider": "mock",
        "version": "v1",
        "fmt": "mp3",
        "sample_rate": 24000,
        "voice": "v1",
        "rate": 0,
        "tone": "",
        "pronunciation": {},
    }
    with app.app_context():
        before = assets.spec_hash(base["text"], **{k: v for k, v in base.items() if k != "text"})
        after = assets.spec_hash(
            value if field == "text" else base["text"],
            **{**{k: v for k, v in base.items() if k != "text"}, **({field: value} if field != "text" else {})},
        )

    assert before != after, f"{field} 变了哈希却没变：缓存会命中旧音频"


def test_rate_comes_from_the_multiplier_and_the_voice_default(app):
    """倍速 → 上游语速的量程是 -50~100（100 = 2.0 倍速），超出要夹住。"""
    from app.services.voice import assets

    with app.app_context():
        assert assets.resolve_rate(None) == 0
        assert assets.resolve_rate(None, default_rate=8) == 8, "没给倍速就用音色自己的默认语速"
        assert assets.resolve_rate(1.0) == 0
        assert assets.resolve_rate(1.5) == 50
        assert assets.resolve_rate(0.5) == -50
        assert assets.resolve_rate(9.9) == 100, "越界要夹住，不能把 890 传给上游"


def test_settings_carry_the_profile_default_rate(seeded):
    """每个老师的默认语速是**音色的属性**，不该由调用方各写一份。"""
    from app.services.voice import assets

    with seeded.app_context():
        profile = _teacher(seeded)
        profile.speech_rate = 20
        db.session.commit()

        assert assets.settings_for(profile).rate == 20
        assert assets.settings_for(profile, speed=1.5).rate == 50
        assert assets.settings_for(profile, speed=1.5).speed == 1.5, "倍速原样转给上游"


# --- 路径（P2-C4）---


def test_paths_stay_under_the_configured_audio_dir(app):
    """库里存相对路径，盘上位置由 AUDIO_DIR 解出来。"""
    from app.services.voice import assets

    with app.app_context():
        rel = assets.rel_path(DEMO_COURSE, "p1-b1", "0123456789abcdef")
        assert rel == "data/assets/audio/course_demo_ml/p1-b1_01234567.mp3"

        path = assets.physical_path(rel)
        assert path is not None
        assert path.parent.name == DEMO_COURSE
        assert str(path).startswith(str(Path(app.config["AUDIO_DIR"])))


@pytest.mark.parametrize(
    "rel",
    [
        "/var/lib/a.mp3",
        "C:/Users/tom/a.mp3",
        "data/assets/audio/../../outside.mp3",
        "data/uploads/a.mp3",
        "",
    ],
)
def test_foreign_and_traversing_paths_resolve_to_nothing(app, rel: str):
    """解析不出物理路径就返回 None —— 不让一个被手改过的库读走任意文件。"""
    from app.services.voice import assets

    with app.app_context():
        assert assets.physical_path(rel) is None


def test_ids_are_neutralized_before_they_reach_the_path(app):
    """id 是外部输入的下游：`../` 顺着它进路径这件事在拼路径之前就要断掉。"""
    from app.services.voice import assets

    with app.app_context():
        rel = assets.rel_path("../../etc", "../../passwd", "a" * 64)
        assert ".." not in rel
        assert assets.physical_path(rel) is not None

        # 兜底：即便有谁绕过 safe_token 拼了个穿越路径，physical_path 也不认
        assert assets.physical_path("data/assets/audio/../../x/p1_00000000.mp3") is None


# --- 合成与缓存 ---


def test_first_synthesis_writes_an_indexed_file_and_an_ledger_entry(seeded):
    """合成一次：盘上有文件、库里有行、账上有一笔（P2-A1/C1）。"""
    from app.models import UsageRecord
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        provider = MockTTS()
        asset, hit = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)

        assert hit is False
        assert asset.status == "ready"
        assert asset.text_hash
        assert asset.size_bytes > 0
        assert asset.duration_ms > 0
        assert asset.available

        path = assets.physical_path(asset.file_path)
        assert path is not None and path.is_file()
        assert path.stat().st_size == asset.size_bytes

        # Mock 出的是 wav，文件名就必须是 .wav（按配置写 .mp3 会得到一个放不出声的 mp3）
        assert path.suffix == ".wav"

        rows = UsageRecord.query.filter_by(kind="tts", ref_id=course.id).all()
        assert len(rows) == 1
        assert rows[0].units == len(beat.text)
        assert rows[0].unit_name == "chars"


def test_synthesizing_the_same_beat_again_changes_nothing(seeded):
    """P2-C1：同样的文本 + 同样的参数 → 不产生新文件，也不产生新账。"""
    from app.models import UsageRecord
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        from app.services.courses import store

        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        provider = MockTTS()

        first, _ = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)
        before = assets.physical_path(first.file_path).stat().st_mtime_ns

        second, hit = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)

        assert hit is True
        assert second.id == first.id
        assert len(provider.calls) == 1, "命中缓存还调上游，就等于每次都花钱"
        assert assets.physical_path(second.file_path).stat().st_mtime_ns == before, "文件被重写了"
        assert UsageRecord.query.filter_by(kind="tts", ref_id=course.id).count() == 1


def test_changing_the_text_replaces_the_audio_without_touching_the_old_file(seeded):
    """讲稿改了就是另一段音频：新文件、新行内容，老文件先留着（可能还有人正在听）。"""
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        page = store.ready_pages(course)[0]
        beat = assets.beats_of_page(page)[0]
        provider = MockTTS()

        first, _ = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)
        old_path = assets.physical_path(first.file_path)
        # 先记成字符串：第二次合成改的是**同一行**（唯一键决定），
        # 拿着 ORM 对象去比会读到新值，比出来永远是「没变」
        old_hash, old_id = first.text_hash, first.id

        edited = assets.Beat(beat.page_no, beat.beat_id, beat.text + "（改过）", beat.est_sec)
        second, hit = assets.synthesize_beat(course, edited, _settings(seeded), provider=provider)

        assert hit is False
        assert second.text_hash != old_hash
        assert second.id == old_id, "同一个 (课, beat, 音色, 语速, 语气) 只有一行"
        assert old_path.is_file(), "老文件不该在合成中途被删 —— 可能还有人正在听"
        assert assets.physical_path(second.file_path) != old_path


def test_a_different_voice_does_not_hit_the_other_voices_cache(seeded):
    """换音色要真的换一把嗓子：这是缓存键里最容易被漏掉的一维。"""
    from app.models import VoiceProfile
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        provider = MockTTS()

        shen, _ = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)

        gu = VoiceProfile.query.filter_by(name="顾老师").one()
        other, hit = assets.synthesize_beat(
            course, beat, assets.settings_for(gu), provider=provider
        )

        assert hit is False
        assert other.id != shen.id
        assert other.voice_id == gu.id
        assert other.file_path != shen.file_path


def test_a_voice_without_an_upstream_id_refuses_instead_of_synthesizing(seeded):
    """没配音色 ID 就说没配，而不是拿着空 ID 去问上游（那会得到一把随机嗓子）。"""
    from app.common.errors import ValidationError
    from app.models import VoiceProfile
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        blank = VoiceProfile(name="没配的老师", provider="volc_tts", voice_type="")
        db.session.add(blank)
        db.session.commit()

        with pytest.raises(ValidationError):
            assets.synthesize_beat(course, beat, assets.settings_for(blank), provider=MockTTS())


def test_a_failed_synthesis_is_recorded_but_not_playable(seeded):
    """失败也落库（`status=failed`）：前端看到的是「这一句没声」，不是「少了一句」。"""
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        provider = FlakyTTS(fail_on=beat.text)

        with pytest.raises(UpstreamError):
            assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)

        row = assets.find_asset(course.id, beat.beat_id, settings=_settings(seeded))
        assert row is not None
        assert row.status == "failed"
        assert row.available is False, "失败的资产不能被播"


# --- 失效（P2-A6）---


def test_marking_a_page_stale_keeps_the_file_but_not_the_playability(seeded):
    """标 stale 不删文件：这次改坏了用户会点回去，而正在听的这一句不该消失。"""
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        page = store.ready_pages(course)[0]
        beat = assets.beats_of_page(page)[0]
        asset, _ = assets.synthesize_beat(course, beat, _settings(seeded), provider=MockTTS())
        path = assets.physical_path(asset.file_path)

        changed = assets.mark_stale(course.id, page_no=page.page_no)

        assert changed == 1
        row = assets.find_asset(course.id, beat.beat_id, settings=_settings(seeded))
        assert row.status == "stale"
        assert row.available is False
        assert path.is_file(), "文件还在 —— 重新合成时才知道要覆盖成什么"

        # 只标了这一页
        other = store.ready_pages(course)[1]
        assert assets.mark_stale(course.id, page_no=other.page_no) == 0


def test_rewriting_a_page_invalidates_its_audio_only(seeded):
    """P2-A6：重写第 N 页 → 该页音频失效，其余页的文件连 mtime 都不该动。

    挂在 `store.save_page` 上（所有写页路径的唯一出口），所以人工编辑也走同一条路。
    """
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        pages = store.ready_pages(course)[:2]
        provider = MockTTS()
        settings = _settings(seeded)

        before = {
            page.page_no: assets.synthesize_beat(
                course, assets.beats_of_page(page)[0], settings, provider=provider
            )[0]
            for page in pages
        }
        mtimes = {
            no: assets.physical_path(asset.file_path).stat().st_mtime_ns
            for no, asset in before.items()
        }

        target = pages[0]
        rewritten = dict(target.dsl)
        rewritten["narration"] = [{"text": "重写之后的讲稿。", "estSec": 3}]
        store.save_page(target, rewritten, reason="rewrite")

        assert (
            assets.find_asset(course.id, f"p{target.page_no}-b1", settings=settings).status == "stale"
        )
        untouched = before[pages[1].page_no]
        assert (
            assets.find_asset(course.id, f"p{pages[1].page_no}-b1", settings=settings).status
            == "ready"
        )
        assert assets.physical_path(untouched.file_path).stat().st_mtime_ns == mtimes[
            pages[1].page_no
        ], "没改的页音频被重写了"


def test_only_user_edits_queue_a_resynthesis(seeded, monkeypatch):
    """P2-A6 的「自动重合成」只管用户改的那两条路（`rewrite` / `manual`）。

    作废之后不重合成，学生听到的还是改之前那句讲稿，而屏幕上已经是新句子 ——
    这种不一致不会报错，只有人守着听才发现。

    反过来，**生成过程中不排**：那时课程正一页页写出来，管线的 `tts` 那一步
    本来就会整课合一次；每个中间状态都排一次，合的是半成品（这一页还没写完的
    那几个 beat），白花钱还留下几行很快就没人认领的资产。
    """
    from app.services.courses import store
    from app.services.voice import jobs

    queued: list[tuple[str, dict]] = []

    def _record(course_id: str, **kwargs) -> bool:
        queued.append((course_id, kwargs))
        return True

    monkeypatch.setattr(jobs, "submit", _record)

    with seeded.app_context():
        course = _course(seeded)
        page = store.ready_pages(course)[0]
        dsl = dict(page.dsl)

        store.save_page(page, dsl, reason="generate")
        assert queued == [], "生成过程中不该排队"

        store.save_page(page, dsl, reason="rewrite")
        assert queued == [(course.id, {"page_no": page.page_no})]

        store.save_page(page, dsl, reason="manual")
        assert len(queued) == 2, "人工编辑也走同一条路（挂点在 save_page 上）"


def test_a_stale_asset_is_synthesized_again_on_the_next_pass(seeded):
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        provider = MockTTS()

        assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)
        assets.mark_stale(course.id, page_no=beat.page_no)
        asset, hit = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)

        assert hit is False
        assert asset.status == "ready"
        assert len(provider.calls) == 2


def test_a_missing_file_behind_a_ready_row_is_rebuilt(seeded):
    """索引和产物对不上时，产物才是真相：文件没了就重合成，而不是报一个 404 给播放器。"""
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        provider = MockTTS()

        asset, _ = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)
        assets.physical_path(asset.file_path).unlink()

        again, hit = assets.synthesize_beat(course, beat, _settings(seeded), provider=provider)
        assert hit is False
        assert assets.physical_path(again.file_path).is_file()


# --- 整课预合成 ---


def test_narrating_a_whole_course_reports_hits_and_misses(seeded):
    """P2-A2：12 页整课的 beat 全部合成，第二次全部命中缓存。"""
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        provider = MockTTS()
        settings = _settings(seeded)

        first = assets.narrate(course, settings, provider=provider)
        assert first["enabled"] is True
        assert first["total"] > 10, "示例课至少有 10 句讲稿"
        assert first["synthesized"] == first["total"]
        assert first["cached"] == 0
        assert first["failed"] == []
        assert first["chars"] > 0

        second = assets.narrate(course, settings, provider=provider)
        assert second["cached"] == second["total"]
        assert second["synthesized"] == 0
        assert len(provider.calls) == first["total"], "第二次不该再调上游"


def test_one_bad_beat_does_not_stop_the_rest(seeded):
    """一句合成不了（上游偶发超时），不该让剩下十句都不合成。"""
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        page = store.ready_pages(course)[0]
        target = assets.beats_of_page(page)[0].text
        report = assets.narrate(
            course, _settings(seeded), provider=FlakyTTS(fail_on=target), page_no=page.page_no
        )

        assert len(report["failed"]) == 1
        assert report["failed"][0]["beatId"] == f"p{page.page_no}-b1"
        assert report["failed"][0]["reason"] == "UpstreamError"
        assert report["synthesized"] == report["total"] - 1


def test_a_whole_course_that_fails_reports_a_fallback(seeded):
    """全军覆没时给出降级路径，调用方不用自己判空（P2-B2 的口径）。"""
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        report = assets.narrate(course, _settings(seeded), provider=FlakyTTS(fail_all=True))

        assert len(report["failed"]) == report["total"] > 0
        assert report["synthesized"] == 0
        assert report["fallback"] == "text"
        assert report["reason"] == "all_failed"


def test_voice_disabled_turns_narration_into_a_no_op(app_factory):
    """P2-G3：关掉总开关后不报错、不合成、不落库 —— 只是没有声音。"""
    from app.models import AudioAsset
    from app.services.voice import assets

    app = app_factory(seed=True, env={**VOICE_ENV, "VOICE_ENABLED": "false"})
    with app.app_context():
        course = _course(app)
        provider = MockTTS()
        report = assets.narrate(course, _settings(app), provider=provider)

        assert report["enabled"] is False
        assert report["total"] == 0
        assert report["fallback"] == "text"
        assert report["reason"] == "voice_disabled"
        assert provider.calls == []
        assert AudioAsset.query.count() == 0


# --- 清单（P2-B3）---


def test_the_manifest_has_the_fields_the_player_needs(seeded):
    """清单是播放器唯一的输入：能播的带 url，不能播的带状态。"""
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        settings = _settings(seeded)

        empty = assets.manifest(course, settings, provider=MockTTS())
        assert empty["available"] is True
        assert empty["readyCount"] == 0, "还没合成，一条能播的都没有"
        assert all(item["url"] == "" for item in empty["beats"])
        assert all(item["status"] == "missing" for item in empty["beats"])
        assert all(item["text"] and item["estSec"] > 0 for item in empty["beats"])

        assets.narrate(course, settings, provider=MockTTS())
        filled = assets.manifest(course, settings, provider=MockTTS())

        assert filled["readyCount"] == filled["beatCount"] == len(filled["beats"])
        for item in filled["beats"]:
            # P2-B3 钉住的五字段
            for key in ("pageNo", "beatId", "textHash", "url", "durationMs"):
                assert key in item, f"清单缺字段 {key}"
            assert item["url"].startswith(f"/api/courses/{course.id}/audio/")
            assert "?v=" in item["url"], "URL 不带版本号，重合成后浏览器会接着放旧文件"
            assert item["durationMs"] > 0
            assert item["status"] == "ready"


def test_the_manifest_says_why_there_is_no_sound(seeded):
    """声音没了要能说清是哪一种：开关关着、没配音色、上游没配 —— 三条不同的路。"""
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)

        unconfigured = assets.manifest(course, assets.VoiceSettings(), provider=MockTTS())
        assert unconfigured["available"] is False
        assert unconfigured["reason"] == "voice_not_configured"
        assert unconfigured["fallback"] == "text"

        no_provider = assets.manifest(course, _settings(seeded), provider=None)
        assert no_provider["available"] is False
        assert no_provider["reason"] == "provider_not_configured"


def test_the_manifest_marks_the_offline_stand_in(seeded):
    """上游是 Mock 时要说出来：否则用户对着一段静音 WAV 找半天问题。"""
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        assert assets.manifest(course, _settings(seeded), provider=MockTTS())["simulated"] is True


# --- 字幕（P2-A3）---


def test_subtitles_are_written_next_to_the_audio(seeded):
    """字级时间戳存旁挂 JSON：它只跟这份音频有关，与业务查询无关。"""
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        asset, _ = assets.synthesize_beat(course, beat, _settings(seeded), provider=MockTTS())

        sidecar = assets.subtitle_path(asset.file_path)
        assert sidecar is not None and sidecar.is_file()

        # Mock 不给时间戳 → 空数组（前端据此退到整句切换），但文件必须在
        assert assets.subtitles_of(asset) == []


def test_a_broken_sidecar_costs_only_the_subtitles(seeded):
    """字幕坏了不该让音频播不出来。"""
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        beat = assets.beats_of_page(store.ready_pages(course)[0])[0]
        asset, _ = assets.synthesize_beat(course, beat, _settings(seeded), provider=MockTTS())

        assets.subtitle_path(asset.file_path).write_text("{坏掉的", encoding="utf-8")

        assert assets.subtitles_of(asset) == []
        assert asset.available is True


# --- 试听（P2-A5）---


def test_previewing_a_voice_is_cached_across_clicks(seeded):
    """重复点试听不重复计费：第二次连上游都不该调。"""
    from app.models import UsageRecord
    from app.services.voice import assets

    with seeded.app_context():
        profile = _teacher(seeded)
        provider = MockTTS()

        first = assets.preview(profile, provider=provider)
        assert first["cached"] is False
        assert first["url"].startswith(f"/api/voice/voices/{profile.id}/preview")
        assert "?v=" in first["url"], "试听改了文本/音色后要能刷新浏览器缓存"

        second = assets.preview(profile, provider=provider)
        assert second["cached"] is True
        assert len(provider.calls) == 1
        assert UsageRecord.query.filter_by(ref_id=f"preview:{profile.id}").count() == 1


def test_preview_audio_lives_under_its_own_pseudo_course(seeded):
    """试听不落 audio_assets（那张表要求 course_id 是真课），但要落在音频目录里。"""
    from app.models import AudioAsset
    from app.services.voice import assets

    with seeded.app_context():
        profile = _teacher(seeded)
        assets.preview(profile, provider=MockTTS())

        assert AudioAsset.query.count() == 0
        directory = Path(seeded.config["AUDIO_DIR"]) / assets.PREVIEW_OWNER
        assert directory.is_dir()
        assert list(directory.glob("*.wav")), "试听音频应该在 _preview/ 下"


def test_preview_refuses_when_voice_is_off(app_factory):
    """开关关着时试听要给 40302 + fallback，而不是 500。"""
    from app.services.voice import assets, policy

    app = app_factory(seed=True, env={**VOICE_ENV, "VOICE_ENABLED": "false"})
    with app.app_context():
        with pytest.raises(policy.VoiceDisabledError) as err:
            assets.preview(_teacher(app), provider=MockTTS())

        envelope = err.value.to_envelope()[0]
        assert envelope["code"] == 40302
        assert envelope["data"]["fallback"] == "text"


# --- 清理（P2-C2）---


def test_purging_a_course_removes_both_files_and_rows(seeded):
    """删课不留孤儿：行没了、文件也没了、目录也收掉了。"""
    from app.models import AudioAsset
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        assets.narrate(course, _settings(seeded), provider=MockTTS(), limit=3)

        directory = Path(seeded.config["AUDIO_DIR"]) / course.id
        assert directory.is_dir() and list(directory.iterdir())

        result = assets.purge_course(course)
        assert result["files"] > 0
        assert result["assets"] > 0
        assert not directory.exists()
        assert AudioAsset.query.filter_by(course_id=course.id).count() == 0


def test_purging_only_touches_its_own_course(seeded):
    """一门课的清理不能碰到另一门课的音频 —— 删的是目录，不是通配符。"""
    from app.services.voice import assets

    with seeded.app_context():
        other = _course(seeded, "course_demo_photosynthesis")
        assets.narrate(other, _settings(seeded), provider=MockTTS(), limit=2)
        before = sorted(p.name for p in (Path(seeded.config["AUDIO_DIR"]) / other.id).iterdir())
        assert before

        assets.purge_course(_course(seeded))

        after = sorted(p.name for p in (Path(seeded.config["AUDIO_DIR"]) / other.id).iterdir())
        assert after == before


# --- 术语表接线（P2-A20）---


def test_the_glossary_comes_from_the_course_content(seeded):
    """纠音表与热词表同源：都从课程内容里来。"""
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        table = assets.glossary_for(course)

        assert table["hotwords"], "页标题就是术语，不该是空的"
        assert set(table["pronunciation"]) <= set(table["hotwords"])
        assert all(len(term) <= 12 for term in table["hotwords"])


def test_the_glossary_can_be_limited_to_one_page(seeded):
    from app.services.courses import store
    from app.services.voice import assets

    with seeded.app_context():
        course = _course(seeded)
        page = store.ready_pages(course)[0]

        table = assets.glossary_for(course, page_no=page.page_no)
        assert table["hotwords"]
        assert len(table["hotwords"]) <= len(assets.glossary_for(course)["hotwords"])


# --- 降级口径（P2-B2）---


def test_every_voice_error_carries_a_fallback(app):
    """前端不得自行猜降级路径：服务端在错误里给出它。"""
    from app.common.errors import NotFoundError, ValidationError
    from app.providers.base import not_configured
    from app.services.voice import policy

    with app.app_context():
        disabled = policy.disabled()
        assert disabled.to_envelope()[0]["data"]["fallback"] == "text"

        # 真按 40201 的构造方式造一个（`not_configured` 才是它的唯一出口）
        missing = not_configured(UnconfiguredTTS(), "API Key")
        envelope = policy.with_fallback(missing).to_envelope()[0]
        assert envelope["data"]["fallback"] == "browser"
        assert envelope["data"]["error"] == "missing_api_key", "40201 的形状是钉死的"

        assert policy.fallback_for(ValidationError("x")) == "text"
        assert policy.fallback_for(NotFoundError("x")) == "text"
        assert policy.fallback_for(RuntimeError("x")) == "text", "不认识的失败也有退路"


def test_the_switch_defaults_to_on(app):
    """没配这个键的老部署不该突然没声音。"""
    from app.services.voice import policy

    with app.app_context():
        assert policy.voice_enabled() is True
