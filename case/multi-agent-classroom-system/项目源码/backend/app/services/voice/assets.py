"""音频资产管线：合成、缓存、失效、清单、清理（P2-A2/A5/A6/A11/C1/C2/C4）。

这一层只做一件事：**让「讲稿里的一句话」对应到「磁盘上的一个文件」**，
并让这件事在重复调用下是幂等的。其余四件事都从这条主线派生：

1. **缓存键是合成规格的哈希**，不只是文本（`spec_hash`）。文本一样、音色换了，
   是另一段音频 —— 只哈希文本会让教师换音色后学生继续听到上一个音色的声音，
   而且不报任何错。上游换代模型（`TTSProvider.version`）同理：
   同一个音色 ID 在两代模型下是两把嗓子。
2. **一个字变了就整句重来**，不做「部分重合成」：音频是连续波形，
   掐头去尾拼接会留爆音。代价是这一句多花一次钱，换来的是不用解释为什么有杂音。
3. **路径一律相对**（P2-C4）：库里存 `data/assets/audio/...`，盘上位置由
   `AUDIO_DIR` 解出来。换机器只改一个配置，不用改数据。
4. **索引与产物对不上时，产物才是真相**。行在而文件不在（有人清了 `data/`），
   判为失效并重合成，而不是报错。

三条与「谁负责什么」有关的约定：

- **失败也落库**（`status=failed`）：前端能从清单里看到这一句没声，
  而不是「清单里没有这一条」—— 后者要靠前端自己数数才知道缺了什么。
- **字幕存旁挂 JSON**，不落库：它只跟这份音频文件有关，音频换了它就换，
  与业务查询无关（表里也没有它的位置）。
- **试听不落 `audio_assets`**：那条路要求 `course_id` 指向一门真课，
  试听属于音色而不是课程。它靠文件名里的哈希做缓存（`preview`）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from flask import current_app

from app.common.dbw import db_write
from app.common.errors import NotFoundError, ValidationError
from app.common.logging import get_logger
from app.extensions import db
from app.models import AUDIO_SUBDIR, AudioAsset, Course, CoursePage, VoiceProfile
from app.providers.base import TTSProvider, TTSResult, not_configured
from app.services.generation.schema import estimate_sec

# 同级模块一律用「从模块里取名字」的形式，不写 `from app.services.voice import policy`：
# 后者要读包对象上的属性，而包正在初始化时那个属性还没挂上（`__init__` 也在导入本模块）。
from app.services.voice.glossary import glossary_of
from app.services.voice.policy import FALLBACK_TEXT, voice_enabled
from app.services.voice.policy import disabled as voice_disabled
from app.services.voice.usage import model_of, record_failure
from app.services.voice.usage import record as record_usage

logger = get_logger("app.voice.assets")

#: 上游语速的量程（与 `VolcTTS` 同一条：100 即 2.0 倍速）。DB 的 `speed` 列
#: 存的就是这个整数 —— 缓存键不能依赖某个 Provider 实例的量程。
RATE_MIN, RATE_MAX = -50, 100

#: 试听音频的「课程」占位目录。它不进 `audio_assets`（那条路要求 course_id
#: 是真课），只用这个目录名把文件归堆。下划线开头，与 `course_*` 不会撞。
PREVIEW_OWNER = "_preview"

#: 配置缺失时的试听句（与 `.env.example` 的 `VOICE_PREVIEW_TEXT` 同源，这里是兜底）。
DEFAULT_PREVIEW_TEXT = "同学们好，我是这节课的老师。"

#: 文件名/目录名的白名单。course_id 与 beat_id 都是我们自己生成的，但它们是
#: **外部输入的下游**（接口层接过来的课程 id）：一旦哪天允许自定义 id，
#: `../` 就顺着它进了路径。在这里拦一道，比在每个调用点记得拦便宜。
_UNSAFE = re.compile(r"[^0-9A-Za-z_-]+")


# --- 讲稿 beat ---


@dataclass(frozen=True)
class Beat:
    """要合成的一句话。`beat_id` 是缓存键的一半，所以它必须与讲稿里的编号一致。"""

    page_no: int
    beat_id: str
    text: str
    est_sec: int = 0


@dataclass(frozen=True)
class VoiceSettings:
    """一次合成要用的全部参数。

    装在一起的理由：**传给上游的**与**算进缓存哈希的**必须是同一组值。
    两组各攒一遍，迟早有一组漏掉一项，而那正是「参数变了却命中旧缓存」。
    """

    voice_id: str = ""  # voice_profiles.id（弱引用的那一头）
    voice_type: str = ""  # 上游音色 ID（算进哈希的那一头）
    rate: int = 0  # 上游语速（DB 的 speed 列）
    speed: float | None = None  # 倍速原样转给上游；None = 用上游自己的默认
    tone: str = ""
    pronunciation: Mapping[str, str] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """能不能真的合成。没有上游音色 ID 就是个空壳。"""
        return bool(self.voice_type)


def resolve_rate(speed: float | None, *, default_rate: int = 0) -> int:
    """倍速 → 上游语速整数。

    与 `VolcTTS._speech_rate` 是同一条量程。这里再算一遍不是重复劳动：
    DB 的 `speed` 列是整数（有 CHECK 约束），而它是缓存键的一部分 ——
    缓存键不能依赖一个可能没被构造出来的 Provider 实例。
    """
    if speed is None:
        return max(RATE_MIN, min(RATE_MAX, int(default_rate or 0)))
    return max(RATE_MIN, min(RATE_MAX, round((float(speed) - 1.0) * 100)))


def settings_for(
    profile: VoiceProfile,
    *,
    speed: float | None = None,
    tone: str = "",
    pronunciation: Mapping[str, str] | None = None,
) -> VoiceSettings:
    """音色档 + 覆盖参数 → 一次合成的参数。

    `speed` 传 None 时用音色档自己的 `speech_rate`：每个老师的默认语速是
    **音色的属性**（陆老师讲得快、顾老师慢一点），不该由调用方各写一份。
    """
    return VoiceSettings(
        voice_id=profile.id,
        voice_type=(profile.voice_type or "").strip(),
        rate=resolve_rate(speed, default_rate=profile.speech_rate),
        speed=speed,
        tone=str(tone or ""),
        pronunciation=dict(pronunciation or {}),
    )


def beats_of_page(page: CoursePage) -> list[Beat]:
    """一页讲稿的 beat 列表。

    `beatId` 缺失时按页序补一个（与 `normalize_beats` 同一条规则）：讲稿是
    从模型来的，而模型会漏编号 —— 漏了就补，不能让「没有编号」变成「不合成」。
    """
    rows = (page.dsl or {}).get("narration") or []
    out: list[Beat] = []
    for index, row in enumerate(rows, start=1):
        if isinstance(row, Mapping):
            text = str(row.get("text") or "").strip()
            beat_id = str(row.get("beatId") or "").strip() or f"p{page.page_no}-b{index}"
            est = int(row.get("estSec") or 0)
        else:
            text = str(row or "").strip()
            beat_id = f"p{page.page_no}-b{index}"
            est = 0
        if not text:
            continue  # 空 beat 不合成：合成一段空音频只会得到一段静音
        out.append(
            Beat(
                page_no=int(page.page_no),
                beat_id=beat_id,
                text=text,
                est_sec=est or estimate_sec(text),
            )
        )
    return out


def course_beats(course: Course, *, page_no: int | None = None) -> list[Beat]:
    """整门课（或某一页）的 beat，按页序与页内序号排列。"""
    from app.services.courses import store

    pages = store.ready_pages(course)
    if page_no is not None:
        pages = [page for page in pages if int(page.page_no) == int(page_no)]
    out: list[Beat] = []
    for page in pages:
        out.extend(beats_of_page(page))
    return out


# --- 路径 ---


def safe_token(value: str, *, limit: int = 48) -> str:
    """目录名 / 文件名片段：只留可移植字符（见 `_UNSAFE` 的说明）。

    开头的下划线**保留**：`_preview` 这类伪课程靠它把自己与 `course_*` 区分开。
    """
    return _UNSAFE.sub("_", str(value or "")).strip()[:limit] or "x"


def audio_root() -> Path:
    """音频根目录（物理路径）。"""
    configured = current_app.config.get("AUDIO_DIR")
    if configured:
        return Path(str(configured))
    from app.config import BACKEND_DIR

    return BACKEND_DIR / "data" / "assets" / "audio"


def rel_dir(course_id: str) -> str:
    return f"{AUDIO_SUBDIR}/{safe_token(course_id)}"


def rel_path(course_id: str, beat_id: str, digest: str, ext: str = "mp3") -> str:
    """落库用的**逻辑**相对路径（P2-C4）。`digest` 传完整哈希或前 8 位都行。"""
    return f"{rel_dir(course_id)}/{safe_token(beat_id)}_{digest[:8]}.{ext.lstrip('.')}"


def physical_path(rel: str) -> Path | None:
    """逻辑相对路径 → 物理路径。落在音频根目录之外的一律判无效（返回 None）。

    有效性在这里判，而不是信任库里那一列：CHECK 约束管得住我们写的行，
    管不住有人拿 sqlite3 手改。多一次判断，换来的是「不会被读到一个任意文件」。
    """
    rel = str(rel or "")
    prefix = AUDIO_SUBDIR + "/"
    if not rel.startswith(prefix) or ".." in rel:
        return None
    root = audio_root().resolve()
    target = (root / rel[len(prefix) :]).resolve()
    if root != target and root not in target.parents:
        return None
    return target


def subtitle_path(rel: str) -> Path | None:
    """音频的旁挂字幕文件（同目录、同名前缀，后缀换 `.json`）。"""
    audio = physical_path(rel)
    return None if audio is None else audio.with_suffix(".json")


def audio_url(course_id: str, beat_id: str, digest: str = "") -> str:
    """前端播放器用的 URL。

    带 `v=` 版本号不是装饰：重合成之后 URL 不变（同一个 beat）、内容变了，
    浏览器会拿缓存里的旧文件继续播 —— 学生听到的是上一版讲稿的声音。
    """
    base = f"/api/courses/{course_id}/audio/{beat_id}"
    return f"{base}?v={digest[:8]}" if digest else base


# --- 缓存键 ---


def spec_hash(
    text: str,
    *,
    provider: str = "",
    version: str = "",
    fmt: str = "mp3",
    sample_rate: int = 24000,
    voice: str = "",
    rate: int = 0,
    tone: str = "",
    pronunciation: Mapping[str, str] | None = None,
) -> str:
    """合成规格的哈希 —— 缓存键的**内容**部分。

    少算任何一项，都会让「参数变了却命中旧缓存」变成静默的：界面显示这一版的
    字幕，学生听到的是上一版的声音。所以这里宁可多算，不可漏算。
    """
    payload = {
        "text": str(text or ""),
        "provider": str(provider or ""),
        "version": str(version or ""),
        "fmt": str(fmt or ""),
        "sampleRate": int(sample_rate or 0),
        "voice": str(voice or ""),
        "rate": int(rate or 0),
        "tone": str(tone or ""),
        # 纠音表：同一个词换个读法就是另一段音频（P2-A20）
        "pronunciation": dict(sorted((pronunciation or {}).items())),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def spec_hash_of(
    beat: Beat, settings: VoiceSettings, *, provider: TTSProvider | None = None
) -> str:
    """一个 beat 在当前参数下的哈希。Provider 缺席时按「未知上游」算 ——
    算出来的键会与有 Provider 时不同，于是重合成一次，这是安全的那个方向。
    """
    return spec_hash(
        beat.text,
        provider=getattr(provider, "name", "") or "",
        version=getattr(provider, "version", "") or "",
        fmt=getattr(provider, "audio_format", "") or "mp3",
        sample_rate=int(getattr(provider, "sample_rate", 0) or 0),
        voice=settings.voice_type,
        rate=settings.rate,
        tone=settings.tone,
        pronunciation=settings.pronunciation,
    )


# --- 资产行 ---


def find_asset(
    course_id: str, beat_id: str, *, settings: VoiceSettings
) -> AudioAsset | None:
    """按唯一键找缓存行。键就是建表时那条唯一索引的五个字段。"""
    return AudioAsset.query.filter_by(
        course_id=course_id,
        beat_id=beat_id,
        voice_id=settings.voice_id,
        speed=settings.rate,
        tone=settings.tone,
    ).first()


def _file_present(asset: AudioAsset | None) -> bool:
    if asset is None or not asset.file_path:
        return False
    path = physical_path(asset.file_path)
    return bool(path and path.is_file())


def is_fresh(asset: AudioAsset | None, digest: str) -> bool:
    """这一行能不能直接拿去播：状态是 ready、内容对得上、文件还在。"""
    return bool(asset and asset.available and asset.text_hash == digest and _file_present(asset))


def _ext_of(result: TTSResult, provider: TTSProvider) -> str:
    """文件后缀跟着**实际拿到的**格式走，而不是配置里写的那个。

    Mock 出的是 wav，配置里写的是 mp3 —— 按配置写后缀会得到一个后缀是 mp3
    的 wav 文件，浏览器按 mp3 解，直接不响（而且不报错，只是没声音）。
    文档里写死的 `.mp3` 是「生产环境长这样」，不是「任何情况下都长这样」。
    """
    fmt = str(getattr(result, "fmt", "") or getattr(provider, "audio_format", "") or "mp3")
    return re.sub(r"[^0-9A-Za-z]", "", fmt).lower() or "mp3"


def _units_of(result: TTSResult, text: str) -> int:
    """这次合成按多少字计费。

    优先用上游回传的计量口径（火山是 `text_words`，含标点）—— 那才是账单上的
    那个数。上游没给（Mock 就不给）才退回文本长度，并且只用于「估」。
    """
    for key in ("text_words", "words", "chars"):
        value = result.usage.get(key) if isinstance(result.usage, Mapping) else None
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return len(text)


def _elapsed_ms(started: float) -> int:
    """一次上游往返花了多久。进账本（`model_calls.latency_ms`），
    回答的是「这一句合成慢不慢」—— 与 `duration_ms`（音频多长）是两回事。"""
    return int((perf_counter() - started) * 1000)


# --- 合成 ---


def synthesize_beat(
    course: Course,
    beat: Beat,
    settings: VoiceSettings,
    *,
    provider: TTSProvider,
    force: bool = False,
) -> tuple[AudioAsset, bool]:
    """合成一个 beat。返回 `(资产行, 是否命中缓存)`。

    只对**真的调了上游**的那一次记账（P2-C1）：命中缓存还记一笔，用量看板
    就会把「花了多少钱」说成「合成过多少次」——两个数从此再也对不上。
    """
    if not settings.usable:
        raise ValidationError("这个音色还没有配置上游音色 ID，无法合成")
    if not provider.configured:
        raise not_configured(provider)

    digest = spec_hash_of(beat, settings, provider=provider)
    existing = find_asset(course.id, beat.beat_id, settings=settings)
    if not force and is_fresh(existing, digest):
        logger.debug("语音缓存命中 course=%s beat=%s", course.id, beat.beat_id)
        return existing, True  # type: ignore[return-value]

    started = perf_counter()
    try:
        result = provider.synthesize(
            beat.text,
            voice=settings.voice_type,
            speed=settings.speed,
            # tone 是「语调起伏」那一档。它在缓存键里，就必须真的传下去 ——
            # 只进哈希不上下游的话，用户拖完滑杆听到的是**一模一样**的声音。
            tone=settings.tone,
            pronunciation=dict(settings.pronunciation) or None,
        )
    except BaseException as exc:
        # 失败也要留痕：前端从清单里看到这一句没声，而不是看不到这一句
        _save_failed(course, beat, settings, digest, exc)
        # 账本也留一行（P5-C2）：「上游挂了几次」只在账本上看得到，
        # 而它是排障时最先要看的。用量表那边**不写** —— 没有用量可记。
        record_failure(
            "tts",
            provider=provider.name,
            # 失败的那次也要说得出是哪一嗓子：同一段文字换个音色重试，
            # 是「换了个设置」还是「同一个设置又挂了一次」，账本上要分得开。
            model=model_of(provider, voice=settings.voice_type),
            error_code=type(exc).__name__,
            ref_type="course",
            ref_id=course.id,
            latency_ms=_elapsed_ms(started),
        )
        raise

    asset = _save_ready(course, beat, settings, digest, result=result, provider=provider)
    record_usage(
        "tts",
        provider=result.provider or provider.name,
        model=model_of(provider, voice=settings.voice_type),
        units=_units_of(result, beat.text),
        ref_type="course",
        ref_id=course.id,
        latency_ms=_elapsed_ms(started),
    )
    return asset, False


def _save_ready(
    course: Course,
    beat: Beat,
    settings: VoiceSettings,
    digest: str,
    *,
    result: TTSResult,
    provider: TTSProvider,
) -> AudioAsset:
    """把合成结果落盘、落库。**先落盘再落库**：库里有一行而盘上没有文件，
    比盘上有个没人认领的文件更难处理（前者会让播放器 404）。"""
    ext = _ext_of(result, provider)
    rel = rel_path(course.id, beat.beat_id, digest, ext)
    path = physical_path(rel)
    if path is None:  # pragma: no cover - 路径是我们自己拼的，到不了
        raise ValidationError("音频路径非法")

    _write_bytes(path, result.audio)
    _write_subtitles(path.with_suffix(".json"), beat, result, settings)

    def _work() -> AudioAsset:
        row = find_asset(course.id, beat.beat_id, settings=settings)
        if row is None:
            row = AudioAsset(
                course_id=course.id,
                page_no=beat.page_no,
                beat_id=beat.beat_id,
                voice_id=settings.voice_id,
                speed=settings.rate,
                tone=settings.tone,
            )
            db.session.add(row)
        row.page_no = beat.page_no
        row.text_hash = digest
        row.file_path = rel
        row.duration_ms = int(result.duration_ms or 0)
        row.size_bytes = len(result.audio or b"")
        row.status = "ready"
        return row

    return db_write(_work)


def _save_failed(
    course: Course,
    beat: Beat,
    settings: VoiceSettings,
    digest: str,
    exc: BaseException,
) -> None:
    """记一次失败。不抛：调用方正在处理真正的那个异常，这里再抛就把它盖掉了。"""

    def _work() -> AudioAsset:
        row = find_asset(course.id, beat.beat_id, settings=settings)
        if row is None:
            row = AudioAsset(
                course_id=course.id,
                page_no=beat.page_no,
                beat_id=beat.beat_id,
                voice_id=settings.voice_id,
                speed=settings.rate,
                tone=settings.tone,
            )
            db.session.add(row)
        row.text_hash = digest
        row.status = "failed"
        return row

    try:
        db_write(_work)
    except Exception:  # 兜底：见 docstring
        logger.exception("语音失败状态落库失败 course=%s beat=%s", course.id, beat.beat_id)
    else:
        logger.warning(
            "语音合成失败 course=%s beat=%s type=%s", course.id, beat.beat_id, type(exc).__name__
        )


def _write_bytes(path: Path, data: bytes) -> None:
    """原子落盘：先写同目录的临时文件再 `os.replace`。

    直接写目标文件时，进程在写一半时挂掉会留下一个**半截的 mp3**：它的大小
    和时长都像那么回事，播放器放到一半断掉。同目录的临时文件保证了
    `replace` 是同分区改名，是原子操作。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_subtitles(
    path: Path, beat: Beat, result: TTSResult, settings: VoiceSettings
) -> None:
    """旁挂字幕 JSON（P2-A3）。没有字级时间戳时写空数组 —— 前端据此退到整句切换。

    写空数组而不是不写文件：文件在不在，是「这份音频的字幕是什么」与
    「这份音频还没生成完」的区别。两者都读成「没有字幕」会让排查少一条线索。
    """
    payload = {
        "beatId": beat.beat_id,
        "pageNo": beat.page_no,
        "durationMs": int(result.duration_ms or 0),
        "voiceId": settings.voice_id,
        "provider": result.provider or "",
        "subtitles": [
            {"text": item.text, "startMs": int(item.start_ms), "endMs": int(item.end_ms)}
            for item in (result.subtitles or ())
        ],
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:  # pragma: no cover - 字幕写不进去不该让合成失败
        logger.warning("字幕写入失败：%s", path.name)


def subtitles_of(asset: AudioAsset | None) -> list[dict[str, Any]]:
    """读旁挂字幕。文件不在 / 坏掉都返回空表：字幕是锦上添花，不是播放的前提。"""
    if asset is None or not asset.file_path:
        return []
    path = subtitle_path(asset.file_path)
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("字幕文件损坏：%s", path.name)
        return []
    rows = payload.get("subtitles") if isinstance(payload, Mapping) else None
    return list(rows) if isinstance(rows, list) else []


# --- 失效 ---


def mark_stale(
    course_id: str, *, page_no: int | None = None, beat_ids: Sequence[str] | None = None
) -> int:
    """把资产标成 `stale`（P2-A6）。返回改了几行。

    **不删文件**：这次改坏了用户还会点回去，而学生正在听的这一句不该因为
    下一次编辑就播不出来。文件由 `purge_course` 在删课时统一清。
    """
    query = AudioAsset.query.filter_by(course_id=course_id)
    if page_no is not None:
        query = query.filter_by(page_no=int(page_no))
    if beat_ids:
        query = query.filter(AudioAsset.beat_id.in_(list(beat_ids)))
    rows = query.filter(AudioAsset.status != "stale").all()
    if not rows:
        return 0

    def _work() -> int:
        for row in rows:
            row.status = "stale"
        return len(rows)

    return db_write(_work)


# --- 整课预合成 ---


def narrate(
    course: Course,
    settings: VoiceSettings,
    *,
    provider: TTSProvider,
    page_no: int | None = None,
    force: bool = False,
    limit: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """整课（或一页）预合成（P2-A2）。

    **顺序合成**，不是并发：`VolcTTS` 复用一条连接、整段合成期间持有锁
    （见 `providers/tts/volc_tts.py`），起四个线程只会让四个请求排队，
    却把「上游同一时刻收到几个请求」这件事变得说不清 —— 限流是按账号算的。
    真要并行，得先让 Provider 支持连接池，那是另一件事。

    合成失败**不中断整课**：一句合成不了（上游偶发超时、某个音色不认），
    不该让剩下十句都不合成。失败进 `failed` 列表，其余照常。

    `on_progress(已完成, 总数)` 给**进度条**用（生成管线那一步，权重 5%）。
    按钮那条路不需要它：清单里的 `readyCount` 就是进度，前端轮询即可。
    """
    report: dict[str, Any] = {
        "courseId": course.id,
        "voiceId": settings.voice_id,
        "provider": provider.name,
        "enabled": True,
        "pageNo": page_no,
        "total": 0,
        "cached": 0,
        "synthesized": 0,
        "failed": [],
        "durationMs": 0,
        "chars": 0,
        "fallback": "",
    }
    if not voice_enabled():
        # 不是错误，是一次「什么都不做」：调用方（管线 / 接口）据此说明原因
        report["enabled"] = False
        report["fallback"] = FALLBACK_TEXT
        report["reason"] = "voice_disabled"
        return report

    beats = course_beats(course, page_no=page_no)
    if limit is not None:
        beats = beats[: max(0, int(limit))]
    report["total"] = len(beats)

    for index, beat in enumerate(beats, start=1):
        if on_progress is not None:
            on_progress(index - 1, len(beats))
        try:
            asset, hit = synthesize_beat(course, beat, settings, provider=provider, force=force)
        except Exception as exc:  # 单句失败不拖垮整课
            report["failed"].append(
                {
                    "beatId": beat.beat_id,
                    "pageNo": beat.page_no,
                    "reason": type(exc).__name__,
                    "message": str(exc)[:200],
                }
            )
            continue
        if hit:
            report["cached"] += 1
        else:
            report["synthesized"] += 1
            report["chars"] += len(beat.text)
        report["durationMs"] += int(asset.duration_ms or 0)

    # 一段都没成时给出降级路径，让调用方不用自己判空
    if report["total"] and len(report["failed"]) == report["total"]:
        report["fallback"] = FALLBACK_TEXT
        report["reason"] = "all_failed"
    return report


# --- 清单 ---


def manifest(
    course: Course,
    settings: VoiceSettings | None = None,
    *,
    provider: TTSProvider | None = None,
) -> dict[str, Any]:
    """音频清单（P2-B3）—— 前端播放器的唯一输入。

    每一条都回答两个问题：「这一句该不该有声音」和「现在有没有声音」。
    没有声音时带上 `status`（`missing` / `stale` / `failed`）与整课的 `reason`，
    前端据此显示「未合成」而不是一个点了没反应的播放键。
    """
    beats = course_beats(course)
    enabled = voice_enabled()
    # 收成一个「有上游音色 ID 才算数」的变量：下面每一处都要按它分叉，
    # 分散写 `settings and settings.usable` 迟早有一处漏判
    chosen: VoiceSettings | None = settings if (settings and settings.usable) else None
    usable = chosen is not None
    asset_provider = provider is not None and bool(provider.configured)

    reason = ""
    if not enabled:
        reason = "voice_disabled"
    elif not usable:
        reason = "voice_not_configured"
    elif not asset_provider:
        reason = "provider_not_configured"

    items: list[dict[str, Any]] = []
    ready = 0
    for beat in beats:
        asset = (
            find_asset(course.id, beat.beat_id, settings=chosen) if chosen is not None else None
        )
        fresh = False
        if asset is not None and asset.available:
            if chosen is not None and provider is not None and asset_provider:
                fresh = is_fresh(asset, spec_hash_of(beat, chosen, provider=provider))
            else:
                # 重算不了哈希（没音色 / 上游没配）就以库里的状态为准：
                # 至少让用户看到「这一句合成过」，而不是把所有已有音频都报成缺的
                fresh = True
        if fresh:
            ready += 1
        items.append(_beat_entry(course.id, beat, fresh_asset=asset if fresh else None, asset=asset))

    return {
        "courseId": course.id,
        "voiceId": settings.voice_id if settings else "",
        "speed": settings.speed if settings else None,
        "rate": settings.rate if settings else 0,
        "tone": settings.tone if settings else "",
        "provider": provider.name if provider else "",
        # 上游是离线替身时要说出来：否则用户对着一段静音 WAV 找半天问题
        "simulated": bool(provider is not None and provider.name == "mock"),
        "enabled": enabled,
        "available": bool(enabled and usable and asset_provider),
        "fallback": FALLBACK_TEXT if (not enabled or not usable) else "",
        "reason": reason,
        "beatCount": len(items),
        "readyCount": ready,
        "beats": items,
    }


def _beat_entry(
    course_id: str,
    beat: Beat,
    *,
    fresh_asset: AudioAsset | None,
    asset: AudioAsset | None,
) -> dict[str, Any]:
    """清单里的一条。`fresh_asset` 是可播的那一行，`asset` 是库里的那一行。

    `fresh_asset` 是不是 None 决定「能不能播」，所以下面每处都直接问它 ——
    中间再存一个 `playable` 布尔，等于让每个字段各记一次这个事实。
    """
    digest = str(asset.text_hash or "") if asset else ""
    return {
        # P2-B3 契约钉住的五个字段 —— 前端播放器按它们写
        "pageNo": beat.page_no,
        "beatId": beat.beat_id,
        "textHash": digest,
        # 有 url 才代表能播：少一个字段，前端就要多写一处判断
        "url": audio_url(course_id, beat.beat_id, digest) if fresh_asset is not None else "",
        "durationMs": int(fresh_asset.duration_ms or 0) if fresh_asset is not None else 0,
        # 播放器还要的三样：字幕文本、没音频时的节奏基准、状态
        "text": beat.text,
        "estSec": int(beat.est_sec),
        "status": "ready" if fresh_asset is not None else (asset.status if asset else "missing"),
        "subtitles": subtitles_of(fresh_asset) if fresh_asset is not None else [],
    }


# --- 试听 ---


def preview(
    profile: VoiceProfile,
    *,
    provider: TTSProvider,
    text: str = "",
    speed: float | None = None,
    tone: str = "",
    force: bool = False,
    ref: str = "preview",
) -> dict[str, Any]:
    """音色试听 / 单句合成（P2-A5 / A1）。重复点击不重复计费 —— 命中缓存直接返回已有文件。

    试听**不进 `audio_assets`**：那张表的 `course_id` 是外键，而试听属于音色、
    不属于任何一门课。缓存就落在文件名里的哈希上：参数一样 → 路径一样 →
    文件在就是命中。少了这张表的「跨重启查询」能力，换来的是不必给试听
    造一门假课。

    `speed` / `tone` 是 `POST /api/voice/tts` 契约里的字段（P2 §4.1），
    所以它们**必须真的进合成**、也**必须进缓存键**：只改一个的话，
    用户拖完滑杆点合成，得到的是和上次一模一样的声音，而且不报错。
    两个默认值都等于「不调整」，历史缓存键因此不变。

    `ref` 只改记账里的 `ref_id` 前缀：`/api/voice/tts` 的单句合成走的是**同一条**
    路（同一个音色、按文本哈希缓存、返回可直接播的 URL），差别只是调用者的
    意图 —— 账本上要能分清「有人点了试听」与「业务合成了这一句」。
    """
    if not voice_enabled():
        raise voice_disabled()
    if not profile.voice_type:
        raise ValidationError("这个音色还没有配置上游音色 ID，无法试听")
    if not provider.configured:
        raise not_configured(provider)

    sentence = str(text or current_app.config.get("VOICE_PREVIEW_TEXT") or DEFAULT_PREVIEW_TEXT)
    tone = str(tone or "")
    rate = resolve_rate(speed, default_rate=profile.speech_rate)
    digest = spec_hash(
        sentence,
        provider=provider.name,
        version=getattr(provider, "version", ""),
        fmt=provider.audio_format,
        sample_rate=int(provider.sample_rate or 0),
        voice=profile.voice_type,
        rate=rate,
        tone=tone,
    )
    rel = rel_path(PREVIEW_OWNER, profile.id, digest, provider.audio_format)
    path = physical_path(rel)
    if path is None:  # pragma: no cover - 路径是我们自己拼的
        raise ValidationError("试听音频路径非法")

    if not force and path.is_file():
        return {
            "voiceId": profile.id,
            "url": _preview_url(profile.id, digest),
            "cached": True,
            "durationMs": _probe_duration(path),
            "text": sentence,
            "provider": provider.name,
        }

    started = perf_counter()
    result = provider.synthesize(
        sentence,
        voice=profile.voice_type,
        speed=speed,
        tone=tone,
        pronunciation=dict(profile.params.get("pronunciation") or {})
        if isinstance(profile.params, Mapping)
        else None,
    )
    _write_bytes(path, result.audio)
    _write_subtitles(
        path.with_suffix(".json"),
        Beat(page_no=0, beat_id=profile.id, text=sentence),
        result,
        VoiceSettings(
            voice_id=profile.id, voice_type=profile.voice_type, rate=rate, speed=speed, tone=tone
        ),
    )
    record_usage(
        "tts",
        provider=result.provider or provider.name,
        model=model_of(provider, voice=profile.voice_type),
        units=_units_of(result, sentence),
        ref_type="session",
        ref_id=f"{safe_token(ref, limit=16)}:{profile.id}",
        latency_ms=_elapsed_ms(started),
    )
    return {
        "voiceId": profile.id,
        "url": _preview_url(profile.id, digest),
        "cached": False,
        "durationMs": int(result.duration_ms or 0),
        "text": sentence,
        "provider": result.provider or provider.name,
    }


def _preview_url(voice_id: str, digest: str) -> str:
    return f"/api/voice/voices/{voice_id}/preview?v={digest[:8]}"


def preview_file(voice_id: str, digest: str = "") -> Path | None:
    """试听音频的**读盘侧**：合成（POST）与播放（GET）是两次请求，中间只靠 URL 传递。

    不按「哈希 → 扩展名」反推路径：扩展名跟着上游给的格式走（Mock 出 wav、
    生产出 mp3），拿配置去猜会猜出一个不存在的文件名。这里按名字前缀找 ——
    前缀里有哈希，找到哪一个就是哪一个。找不到返回 None（由接口层 404）。

    同一对 (音色, 哈希) 只会有一个文件（写的时候就是按它命名的），
    所以「取最新的一个」不是在做取舍，只是在有残留（.part 之类）时挑对的那个。

    文件名是 `{音色}_{哈希前8位}.{后缀}`（见 `rel_path`）—— 哈希与后缀之间是
    **点**。按下划线去找会一个也找不到，而那正是「合成成功、试听 404」。
    """
    directory = physical_path(rel_dir(PREVIEW_OWNER))
    if directory is None or not directory.is_dir():
        return None
    token = safe_token(voice_id)
    # 给了哈希就锁到那一段（后缀跟着上游给的格式走，不能写死）；
    # 没给就在这个音色的全部试听音频里找。
    pattern = f"{token}_{safe_token(digest)[:8]}.*" if digest else f"{token}_*"
    candidates = [
        item
        for item in directory.glob(pattern)
        if item.is_file() and item.suffix not in {".json", ".part"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _probe_duration(path: Path) -> int:
    """从旁挂字幕里读时长。读不到就是 0 —— 试听键要不要显示秒数，不该由一个读文件失败决定。"""
    sidecar = path.with_suffix(".json")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    value = payload.get("durationMs") if isinstance(payload, Mapping) else 0
    return int(value or 0)


# --- 清理 ---


def purge_files(course_id: str) -> int:
    """删掉一门课的音频目录，返回删掉的文件数。**只碰自己那一层目录**。

    删课走的是 `courses.store.purge_course`（真删）；软删不动文件 ——
    用户手滑删了课要能撤回，撤回之后重听一遍还要再花一次合成的钱。
    """
    directory = physical_path(rel_dir(course_id))
    if directory is None or not directory.is_dir():
        return 0
    count = 0
    for item in directory.iterdir():
        if item.is_file():
            try:
                item.unlink()
                count += 1
            except OSError:  # pragma: no cover - 被占用/权限，记一笔继续
                logger.warning("音频文件删除失败：%s", item.name)
    try:
        directory.rmdir()  # 只删空目录：里面还有东西就说明不是我们的文件
    except OSError:
        logger.warning("音频目录非空，保留：%s", directory.name)
    return count


def purge_course(course: Course) -> dict[str, Any]:
    """删课时的音频清理（P2-C2）：先删文件，再删行。

    顺序是有讲究的：反过来的话，删完行、删文件失败，这些文件就再也没人认得
    它们属于哪门课了（`audio_assets` 就是那张「谁是谁」的表）。
    """
    files = purge_files(course.id)

    def _work() -> int:
        return AudioAsset.query.filter_by(course_id=course.id).delete()

    rows = db_write(_work)
    if files or rows:
        logger.info("清理课程音频 course=%s 文件=%d 行=%d", course.id, files, rows)
    return {"courseId": course.id, "files": files, "assets": rows}


def glossary_for(course: Course, *, page_no: int | None = None) -> dict[str, Any]:
    """课程的术语表（P2-A20）：TTS 的纠音表与 ASR 的热词表从同一份投出来。"""
    from app.services.courses import store

    pages = store.ready_pages(course)
    if page_no is not None:
        pages = [page for page in pages if int(page.page_no) == int(page_no)]
    dsl = course.dsl or {}
    return glossary_of(dsl.get("meta"), pages)


def voice_or_404(voice_id: str) -> VoiceProfile:
    """取音色档，没有就 404（越权与不存在同一条口径，AGENTS §4.1）。"""
    profile = db.session.get(VoiceProfile, voice_id)
    if profile is None:
        raise NotFoundError("音色不存在")
    return profile


__all__ = [
    "DEFAULT_PREVIEW_TEXT",
    "PREVIEW_OWNER",
    "RATE_MAX",
    "RATE_MIN",
    "Beat",
    "VoiceSettings",
    "audio_root",
    "audio_url",
    "beats_of_page",
    "course_beats",
    "find_asset",
    "glossary_for",
    "is_fresh",
    "manifest",
    "mark_stale",
    "narrate",
    "physical_path",
    "preview",
    "preview_file",
    "purge_course",
    "purge_files",
    "rel_dir",
    "rel_path",
    "resolve_rate",
    "safe_token",
    "settings_for",
    "spec_hash",
    "spec_hash_of",
    "subtitles_of",
    "synthesize_beat",
    "voice_or_404",
]
