"""课堂里的「非讲稿」发言配一段声音（P3-A5）。

讲稿的音频是**预合成**的：开课前有人点过「合成语音」，每个 beat 在
`audio_assets` 里都有一行，`runtime._beat_audio` 只是把它读出来。别的发言不
一样 —— 老师答的那句在课上才被问出来，AI 同学说的那句在课上才被写出来，
没有「提前合成」这回事，只能**当场合成**。这一层就是那一步。

**失败一律降级，绝不抛**。答疑是课堂主线上的一环：`_answer` 里一次 LLM 调用已经
花掉几秒，上游 TTS 再偶发一次超时，不该把整条发言弄没（学生等的是答案，
声音是加分项）。所以这里对外只有两个结果：一段音频，或者一个空 dict ——
调用方拿空 dict 就按「这条没有音频」走，`_speak_ms` 退回按字数估时。

**谁说话就用谁的嗓子**（`turn_audio`）。角色库里的每一位都挂着 `voice_profile_id`
（种子按 `voice` 配好了，见 `seeds/roles.py`），老师一把、同学各一把 —— 拿老师的
嗓子替同学提问，学生会以为老师在自问自答，比没有声音更糟。所以**同学借不到
自己的音色档时干脆不合成**，宁可这条按纯文字走。

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

from typing import Any, Mapping

from app.common.logging import get_logger

logger = get_logger("app.classroom.speech")

#: 记账里的 `ref_id` 前缀。与试听的 `preview:` 分开，账本上要能看出
#: 「有人点了试听」和「课堂上老师答了一句/同学说了一句」是两件事。
REF = "classroom"

#: 交给上游的最长字数。答疑文本本来就截到 `prompts.MAX_ANSWER_CHARS`，
#: 这里再夹一道是因为本层也会被别的路径调到（比如往后的测验讲评）——
#: 一次合成长文本既有上游长度限制，也是一笔不小的账。
MAX_CHARS = 600


def answer_audio(
    text: str,
    *,
    voice_id: str = "",
    rate_offset: int = 0,
) -> dict[str, Any]:
    """给一句话配一段声音。返回 `{url, durationMs}`，配不出来返回 `{}`。

    Args:
        text: 要说的话。空白会被收起（合成长串空格是白花钱）。
        voice_id: 用哪个音色档（`VoiceProfile.id`）。空 = 走默认那把嗓子
            （设置页的老师音色 → 角色库里的老师音色），也就是答疑的口径。
            **显式给了一个查不到的音色档时不回退**：那说明说话的人自己没有
            嗓子，见 `turn_audio`。
        rate_offset: 语速偏移，与音色档自己的 `speech_rate` 同一条量程
            （上游的百分数整数）。0 = 不调，用音色档自己的语速。

    Returns:
        `{"url": 可直接播的 URL, "durationMs": 毫秒}`；没配 TTS、音色没配好、
        上游失败、文本为空 —— 任何一种情况都是 `{}`。
    """
    sentence = " ".join(str(text or "").split())[:MAX_CHARS]
    if not sentence:
        return {}
    try:
        entry = _synthesize(sentence, voice_id=voice_id, rate_offset=rate_offset)
    except Exception as exc:  # 见模块注释：这一层绝不往上抛
        logger.info("课堂语音合成跳过（这条发言按纯文字走）：%s", type(exc).__name__)
        return {}

    url = str(entry.get("url") or "")
    if not url:
        return {}
    return {"url": url, "durationMs": max(0, _int_of(entry.get("durationMs")))}


def turn_audio(
    text: str,
    *,
    voice_id: str = "",
    role: str = "student",
    persona: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """给**某一位**发言人的话配声音：他自己的音色档 + 他自己的人设语速。

    与 `answer_audio` 只差一条规矩 —— **同学借不到自己的音色档就不合成**。
    角色库里没配音色的同学，`prefs.voice_profile` 会退到默认那把（老师），
    于是讨论区里会响起一句老师的声音说「我觉得这里应该…」。宁可这条没有
    声音：前端本来就按「没音频就只显示文字、等 `speak_end` 收尾」写好了。

    老师不退：师生本来就共用那把默认嗓子，退回去是正确的。角色库空着时
    `roster.DEFAULT_TEACHER` 连 `voiceProfileId` 都没有，走的正是这条路。

    Args:
        text: 要说的话。
        voice_id: 发言人的 `AgentRole.voice_profile_id`。空字符串 = 他没有。
        role: `teacher` / `student`。只用来决定「借不到嗓子时退不退」。
        persona: 角色的人设（`AgentRole.persona`）。里面那个 `speechRate`
            是**上游量程的整数**，几位同学共用同一个音色档时靠它拉开区分度
            （种子里林晓与苏雨都是顾老师）。
    """
    if not voice_id and role != "teacher":
        return {}
    return answer_audio(
        text,
        voice_id=voice_id,
        rate_offset=_int_of((persona or {}).get("speechRate")),
    )


def _synthesize(sentence: str, *, voice_id: str, rate_offset: int) -> dict[str, Any]:
    """真的去合成一次（会抛）。**导入放在函数里**：本模块被 runtime 在 WS 线程里
    反复导入，而语音那条链会拉进 provider 注册表与模型层，导入浅一点好排查。"""
    from app.services.voice import assets, prefs

    profile = prefs.voice_profile(voice_id)
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
        speed=_speed_with_offset(profile, speed, rate_offset),
        tone=current.tone,
        ref=REF,
    )


def _speed_with_offset(
    profile: Any,
    base: float | None,
    rate_offset: int,
) -> float | None:
    """把「上游语速整数的偏移」换算成 `preview` 收的那个倍速。

    `persona.speechRate` 与音色档自己的 `speech_rate` 是**同一条量程**（上游的
    百分数整数），而 `assets.preview` 收的是倍速 —— `assets.resolve_rate` 反着算
    `(speed - 1) * 100`。所以先把设置页那个倍速（没调过就是音色档自己的语速）
    落成一个整数，加上偏移，再换回倍速。量程越界由 `resolve_rate` 夹住。
    """
    if not rate_offset:
        return base

    from app.services.voice import assets

    current = assets.resolve_rate(base, default_rate=int(getattr(profile, "speech_rate", 0) or 0))
    return 1.0 + (current + int(rate_offset)) / 100.0


def _int_of(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = ["MAX_CHARS", "REF", "answer_audio", "turn_audio"]
