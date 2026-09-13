"""课堂里的「非讲稿」发言配一段声音（P3-A5）。

讲稿的音频是**预合成**的：开课前有人点过「合成语音」，每个 beat 在
`audio_assets` 里都有一行，`runtime._beat_audio` 只是把它读出来。教师答疑不一样
—— 问题在课上才被问出来，答案在课上才被写出来，没有「提前合成」这回事，
只能**当场合成**。这一层就是那一步。

**失败一律降级，绝不抛**。答疑是课堂主线上的一环：`_answer` 里一次 LLM 调用已经
花掉几秒，上游 TTS 再偶发一次超时，不该把整条发言弄没（学生等的是答案，
声音是加分项）。所以这里对外只有两个结果：一段音频，或者一个空 dict ——
调用方拿空 dict 就按「这条没有音频」走，`_speak_ms` 退回按字数估时。

**为什么不落 `audio_assets`**：那张表要求 `course_id` 指向一门真课，而一次答疑
属于**这一堂课**（同一句话在两个班里可能被问两遍，两堂课共用一个音频是好事，
但前提是那行资产有地方挂）。走 `assets.preview` 这条路，缓存键落在文件名里的
规格哈希上，和音色试听共用一套目录与清理口径 —— 代价是它不参与 `manifest`
的统计（清单只回答「讲稿有没有声」），而这正是我们要的：答疑音频不是讲稿资产。

**这里复用的是 `preview`，不是 `synthesize_beat`**：后者按 `(course, beat_id)`
落库落盘，本层的调用根本没有 beat。两者合成的是同一把嗓子 ——
`assets.preview` 与 `narration_settings` 取的是同一个音色档、同一档语速与语调，
唯一对不上的是**课程的纠音表**（`preview` 只认音色档自己的 `pronunciation`）。
这个差别是有意的：纠音表是给术语密集的讲稿用的，答疑里就算读出同一个术语，
读法也不该和讲稿不一样 —— 真要一致，得把 `preview` 的参数表也扩一份，
那是 P4 往后的事（现在扩，等于让试听接口也接受一个它用不上的参数）。
"""

from __future__ import annotations

from typing import Any

from app.common.logging import get_logger

logger = get_logger("app.classroom.speech")

#: 记账里的 `ref_id` 前缀。与试听的 `preview:` 分开，账本上要能看出
#: 「有人点了试听」和「课堂上老师答了一句」是两件事。
REF = "classroom"

#: 交给上游的最长字数。答疑文本本来就截到 `prompts.MAX_ANSWER_CHARS`，
#: 这里再夹一道是因为本层也会被别的路径调到（比如往后的测验讲评）——
#: 一次合成长文本既有上游长度限制，也是一笔不小的账。
MAX_CHARS = 600


def answer_audio(text: str) -> dict[str, Any]:
    """给一句话配一段声音。返回 `{url, durationMs}`，配不出来返回 `{}`。

    Args:
        text: 要说的话。空白会被收起（合成长串空格是白花钱）。

    Returns:
        `{"url": 可直接播的 URL, "durationMs": 毫秒}`；没配 TTS、音色没配好、
        上游失败、文本为空 —— 任何一种情况都是 `{}`。
    """
    sentence = " ".join(str(text or "").split())[:MAX_CHARS]
    if not sentence:
        return {}
    try:
        entry = _synthesize(sentence)
    except Exception as exc:  # 见模块注释：这一层绝不往上抛
        logger.info("课堂语音合成跳过（这条发言按纯文字走）：%s", type(exc).__name__)
        return {}

    url = str(entry.get("url") or "")
    if not url:
        return {}
    return {"url": url, "durationMs": max(0, _int_of(entry.get("durationMs")))}


def _synthesize(sentence: str) -> dict[str, Any]:
    """真的去合成一次（会抛）。**导入放在函数里**：本模块被 runtime 在 WS 线程里
    反复导入，而语音那条链会拉进 provider 注册表与模型层，导入浅一点好排查。"""
    from app.services.voice import assets, prefs

    profile = prefs.voice_profile()
    if profile is None:  # 一个音色都没配好：没有嗓子可借
        return {}

    # 语速与语调取设置页那一档，与讲稿同源 —— 老师换个语速，答疑也要跟着换。
    # 1.0 是「没调过」：交回音色档自己的 `speech_rate`（见 prefs 的说明），
    # 不能把每个老师的语速个性抹平。
    current = prefs.current_prefs()
    speed = None if current.speed == prefs.DEFAULT_SPEED else current.speed
    return assets.preview(
        profile,
        provider=prefs.tts_provider(),
        text=sentence,
        speed=speed,
        tone=current.tone,
        ref=REF,
    )


def _int_of(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = ["MAX_CHARS", "REF", "answer_audio"]
