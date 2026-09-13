"""账本、价目表、日界（P5-C2 / F5-7 / P5-A7）。

这一份守着**唯一的写入点**（`services/usage/ledger.py`）与**唯一的口径**
（金额永远是估算、非负、一条调用一行）。它测的是「写进去的数字能不能被信」，
不是「看板长什么样」—— 后者在 `test_api_usage.py`。

三件事在这里定死：

- 非负：负数一律夹成 0。`model_calls` 的 P5 扩列**没有** CHECK 约束
  （SQLite 加约束要整表重建，那是写热的账本），所以这条保证只在代码里，
  没有它就没有别的地方拦。
- 口径：`units` / `unit_name` 跟着 `kind` 走，金额从**同一张价目表**算出来。
- 日：日界是本地日（缺省东八区），不是 UTC 日。
"""

from __future__ import annotations

import pytest

from app.common.errors import ValidationError
from app.models import ModelCall
from app.services.usage import days, ledger, pricing

pytestmark = pytest.mark.unit


# --- 账本 ---


def test_a_call_lands_in_the_ledger_with_its_attribution(app):
    ledger.record(
        "llm",
        provider="deepseek", model="deepseek-chat",
        prompt_tokens=1200, completion_tokens=800,
        latency_ms=430, job_id="j_1", step_id="s_2", owner_id="u_1",
        ref_type="job", ref_id="j_1",
    )

    row = ModelCall.query.one()
    assert (row.kind, row.provider, row.model) == ("llm", "deepseek", "deepseek-chat")
    assert (row.prompt_tokens, row.completion_tokens, row.tokens) == (1200, 800, 2000)
    assert (row.job_id, row.step_id, row.owner_id) == ("j_1", "s_2", "u_1")
    assert (row.ref_type, row.ref_id) == ("job", "j_1")
    assert row.ok is True


def test_the_upstream_total_wins_over_the_sum_of_halves(app):
    """上游给了 total 就用它的（可能含缓存命中口径），自己加出来的会与账单差一截。"""
    ledger.record("llm", prompt_tokens=100, completion_tokens=50, tokens=180)

    assert ModelCall.query.one().tokens == 180


def test_negative_numbers_are_clamped_to_zero(app):
    """非负由这里保证，而不是 CHECK 约束 —— 见 `models/telemetry.py` 的注。

    夹成 0 而不是抛异常：一次调用已经发出去了，为了记账的一个负数把
    整页生成弄失败，是把「账不对」升级成「活干不成」。
    """
    ledger.record("llm", prompt_tokens=-10, completion_tokens=-5, units=-3, latency_ms=-1)

    row = ModelCall.query.one()
    assert (row.prompt_tokens, row.completion_tokens, row.tokens) == (0, 0, 0)
    assert (row.units, row.latency_ms) == (0, 0)


def test_units_follow_the_kind(app):
    """单位跟着 kind 走，不给调用方自由发挥 —— 传错一次不会报错，只会让数字没有意义。"""
    ledger.record("tts", units=1500)
    ledger.record("asr", units=42)

    rows = ModelCall.query.order_by(ModelCall.created_at).all()
    assert [(row.kind, row.units, row.unit_name) for row in rows] == [
        ("tts", 1500, "chars"),
        ("asr", 42, "seconds"),
    ]


def test_an_unknown_kind_is_a_programming_error(app):
    """写死在这里的 kind 是账本的口径，不是用户输入 —— 拼错必须当场炸，不能静默落库。"""
    with pytest.raises(ValueError):
        ledger.record("image", units=1)

    assert ModelCall.query.count() == 0


def test_a_failed_call_is_still_recorded(app):
    """失败也要留一行：「上游挂了三次」只在账本上看得到，而它正是排障要先看的。"""
    ledger.record("llm", ok=False, error_code="timeout", job_id="j_1")

    row = ModelCall.query.one()
    assert (row.ok, row.error_code) == (False, "timeout")


def test_a_write_failure_does_not_blow_up_the_caller(app, monkeypatch):
    """账写不进去只记日志：内容已经生成好了，为一次写库冲突把它丢掉更糟。"""
    def boom(fn):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("app.services.usage.ledger.db_write", boom)

    assert ledger.record("llm", tokens=10) is None


# --- 价目表 ---


def test_prices_default_to_not_configured(app):
    """没配单价时 `priced` 是 False —— 界面据此说「未配置单价」，
    而不是显示一个 `¥0.00` 让人以为这门课真的不要钱。"""
    assert pricing.estimate_llm("any-model", 1000, 1000) == 0.0
    assert pricing.priced("llm") is False
    assert pricing.priced("tts") is False


def test_llm_price_splits_prompt_and_completion(app_factory):
    app_factory(env={"LLM_PRICE_PROMPT_PER_1K": "1", "LLM_PRICE_COMPLETION_PER_1K": "3"})

    # 输入 1 元/千、输出 3 元/千：2k 输入 + 1k 输出 = 2 + 3
    assert pricing.estimate_llm("deepseek-chat", 2000, 1000) == 5.0
    assert pricing.priced("llm") is True


def test_an_unlisted_model_falls_back_to_the_wildcard(app_factory):
    """看板上出现一个没配价的模型是**常态**（用户随时能换），落到 0 会让整门课少一块。"""
    app_factory(env={"LLM_PRICE_PROMPT_PER_1K": "2"})

    assert pricing.estimate_llm("brand-new-model", 1000, 0) == 2.0


def test_voice_prices_carry_their_own_unit(app_factory):
    """TTS 按千字符、ASR 按分钟 —— 是两家上游各自的计费方式，不是我们选的。"""
    app_factory(env={"VOICE_TTS_PRICE_PER_KCHARS": "2", "VOICE_ASR_PRICE_PER_MINUTE": "3"})

    assert pricing.estimate_units("tts", 1500) == 3.0  # 1.5 千字符 × 2 元
    assert pricing.estimate_units("asr", 90) == 4.5  # 1.5 分钟 × 3 元
    assert pricing.priced("tts") is True


def test_the_settings_page_can_override_a_config_price(app_factory):
    """配置打底、设置覆盖 —— 合并只有一处，两边就不会算出不同的数。"""
    app_factory(env={"LLM_PRICE_PROMPT_PER_1K": "1"})

    pricing.update({"llm": {"deepseek-chat": {"promptPer1k": 5}}})

    assert pricing.estimate_llm("deepseek-chat", 1000, 0) == 5.0
    # 没被覆盖的模型仍然走配置里那个通配价
    assert pricing.estimate_llm("other-model", 1000, 0) == 1.0


def test_a_negative_or_non_numeric_price_is_rejected(app):
    """负单价会让账本出现负金额，而「花了 -3 元」会把别的链路花掉的钱抵掉一半。"""
    with pytest.raises(ValidationError):
        pricing.update({"llm": {"m": {"promptPer1k": -1}}})

    with pytest.raises(ValidationError):
        pricing.update({"llm": {"m": {"promptPer1k": "便宜"}}})


def test_the_price_rows_expose_the_unit_size(app):
    """前端要把「每千字符 / 每分钟」讲清楚，所以一份是多少个单位必须回给它。"""
    rows = {row["kind"]: row for row in pricing.rows()}

    assert rows["tts"]["unitSize"] == 1000
    assert rows["asr"]["unitSize"] == 60
    assert rows["asr"]["unitName"] == "seconds"


# --- 日界 ---


def test_a_day_is_a_local_day(app):
    """库里是 UTC，但「今天」是本地日：按 UTC 切，北京时间早上 8 点日预算就重置了。"""
    from app.common.timeutil import parse_iso

    # 2026-09-12T23:30Z 已经是东八区的 9 月 13 日 07:30
    assert days.local_day(parse_iso("2026-09-12T23:30:00.000000Z")) == "2026-09-13"
    # 而 UTC 的 9 月 12 日 15:59 还是东八区的 9 月 12 日 23:59
    assert days.local_day(parse_iso("2026-09-12T15:59:00.000000Z")) == "2026-09-12"


def test_the_offset_is_configurable_and_clamped(app_factory):
    """写错的偏移不会报错，只会让每一天都挪位 —— 所以夹在真实时区的范围内。"""
    app_factory(env={"USAGE_DAY_OFFSET_HOURS": "0"})
    assert days.offset_hours() == 0

    other = app_factory(env={"USAGE_DAY_OFFSET_HOURS": "999"})
    assert other is not None
    assert days.offset_hours() == 14  # 夹到 UTC+14，而不是照着一个不存在的时区算账


def test_bounds_cover_exactly_one_local_day(app):
    """`[start, end)` 是一整个本地日，两端的字符串比较与时间先后一致。"""
    start, end = days.bounds("2026-09-13")

    assert start == "2026-09-12T16:00:00.000000Z"  # 东八区的 9-13 00:00
    assert end == "2026-09-13T16:00:00.000000Z"
    assert days.day_of(start) == "2026-09-13"
    assert days.day_of(end) == "2026-09-14"


def test_a_bad_date_falls_back_instead_of_erroring(app):
    """看板打开时不带参数是常态；手输的日期格式不对，用户要的是默认值而不是报错。"""
    assert days.clean("昨天") == ""
    assert days.clean("2026-13-40") == ""
    assert days.clean("") == ""

    # 两头都认不出来 → 退回缺省窗口（最近 30 天），而不是一条都查不出来
    span = days.window("昨天", "也看不懂")
    assert (span.last, len(span.days)) == (days.today(), 30)


def test_a_sloppy_but_readable_date_is_normalised(app):
    """`2026-9-3` 与带时间的 ISO 都收：前端日期控件回的就是这两种。"""
    assert days.clean("2026-9-3") == "2026-09-03"
    assert days.clean("2026-09-13T00:00:00Z") == "2026-09-13"


def test_reversed_dates_are_swapped(app):
    """填反了就对调：少一次 400，多一次能看的图。"""
    span = days.window("2026-09-13", "2026-09-11")

    assert (span.first, span.last) == ("2026-09-11", "2026-09-13")
    assert span.days == ["2026-09-11", "2026-09-12", "2026-09-13"]


def test_the_default_window_is_the_last_thirty_days(app):
    span = days.window()

    assert len(span.days) == 30
    assert span.last == days.today()
