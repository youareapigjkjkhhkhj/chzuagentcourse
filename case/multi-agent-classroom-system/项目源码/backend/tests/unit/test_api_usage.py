"""成本看板、日缓存与预算（P5 §4.2 / F5-7 / F5-8 / P5-A7 / P5-A8）。

这一份从 **HTTP 这一层**取证据：看板的每个数都要能从 `model_calls` 与
`usage_records` 里的行加出来（P5-A7 的「对账」），预算要真的**拦住**一次生成
（P5-A8），而不是只在服务层返回一个布尔值。

三条最容易被写错、也最难在界面上看出来的口径，各有一个用例守着：

1. **不重复计价**：`model_calls` 里也有语音那几条（P5-C2 要求账本覆盖四种调用），
   但它们**不进金额** —— 否则一次 TTS 在看板上被算两遍，而且前后端都看不出错。
2. **缓存不撒谎**：过去的日子算一次存下来（零用量的也写四条 0），今天永远现算。
   「那天没花过钱」与「那天还没算过」必须是两件能分开的事。
3. **0 = 不限**：预算里 0 不是「限额为零」。写成「限额为零」的话，
   用户设完日预算会发现连一门课都开不了，而设置页上显示的是「0 元」。
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest

from app.common.errors import StateError
from app.common.identity import OWNER_HEADER
from app.common.timeutil import parse_iso, to_iso
from app.extensions import db
from app.models import Budget, Course, DailyUsage, ModelCall, UsageRecord
from app.services.usage import aggregate, budget, days, pricing

pytestmark = pytest.mark.unit

TOPIC = "机器学习入门"

#: 本机的归属人。接口那边的 `current_owner_id()` 取的是第一个用户
#: （`local_owner_id`），所以造账时要挂在同一个人名下 —— 否则
#: 「按人筛」那一层会把测试自己造的每一行都挡在外面，而失败现象是
#: 「看板全 0」，看着像聚合写错了。
ME = "u_1"


@pytest.fixture(autouse=True)
def accounts(app):
    """这台机器上的老师。

    `courses.owner_id` 是指向 `users` 的外键（SQLite 这边开着 `PRAGMA foreign_keys`），
    所以「别人的课」必须真有一个别人 —— 随手编一个 id 会被外键挡下来。
    """
    from app.models import User

    db.session.add(User(id=ME, name="沈老师", role="teacher"))
    db.session.commit()


# --- 造账 ---


#: 每造一行账就走一分钟。**不能每行都给同一个时刻**：明细按时间倒序排，
#: 时刻全相同时「新的排在前面」这条断言永远成立 —— 它就不再守着任何东西了。
_CLOCK = itertools.count()


def _at(day: str, hour: int = 12) -> str:
    """本地日 + 某小时 → 库里的 UTC 时刻。默认中午，离两头的日界都远。"""
    start, _ = days.bounds(day)
    return to_iso(parse_iso(start) + timedelta(hours=hour, minutes=next(_CLOCK)))


def _llm(
    *, day: str = "", tokens: int = 0, prompt: int = 0, completion: int = 0,
    cost: float = 0.0, course_id: str = "", owner_id: str = ME, job_id: str = "",
    ref_type: str = "course", kind: str = "llm",
) -> ModelCall:
    """往账本里塞一次调用。`cost` 显式给 —— 测试不该依赖当时配的价目表。"""
    row = ModelCall(
        kind=kind,
        provider="deepseek",
        model="deepseek-chat",
        tokens=tokens or prompt + completion,
        prompt_tokens=prompt,
        completion_tokens=completion,
        est_cost=cost,
        job_id=job_id,
        owner_id=owner_id,
        ref_type=ref_type if (course_id or ref_type) else "",
        ref_id=course_id,
        created_at=_at(day or days.today()),
    )
    db.session.add(row)
    return row


def _voice(
    kind: str = "tts", *, day: str = "", units: int = 0, cost: float = 0.0,
    course_id: str = "",
) -> UsageRecord:
    row = UsageRecord(
        kind=kind,
        provider="volc",
        units=units,
        unit_name={"tts": "chars", "asr": "seconds", "realtime": "seconds"}[kind],
        est_cost=cost,
        ref_type="course",
        ref_id=course_id,
        created_at=_at(day or days.today()),
    )
    db.session.add(row)
    return row


def _course(course_id: str = "c_1", *, owner_id: str = ME, title: str = TOPIC) -> Course:
    row = Course(id=course_id, owner_id=owner_id, title=title, topic=title, status="ready")
    db.session.add(row)
    return row


def _commit() -> None:
    db.session.commit()


# --- 看板（F5-7）---


def test_the_board_totals_match_the_ledger(app, client):
    """P5-A7：看板的数**就是从两张账加出来的**，不是另算一遍。

    这个断言是这一整块功能的底线：看板一旦自己算一套，用户就再也没有
    办法判断「看板说 3 块、账单说 5 块」时该信哪个。
    """
    _llm(prompt=1000, completion=500, cost=1.5)
    _llm(prompt=2000, completion=0, cost=2.0)
    _voice("tts", units=3000, cost=0.6)
    _commit()

    data = client.get("/api/usage/summary").get_json()["data"]

    assert data["totals"]["estCost"] == pytest.approx(4.1)
    assert data["totals"]["calls"] == 3
    assert data["totals"]["totalTokens"] == 3500
    # 语音两个单位（字符 / 秒）加起来没有意义，但同一个 kind 的合计要能对得上
    assert data["totals"]["totalUnits"] == 3000
    assert data["groupBy"] == "day"
    assert data["note"] == "估算值，以账单为准"


def test_a_voice_call_in_the_ledger_is_not_counted_twice(app, client):
    """口径的分工（P5 文档 §10.2）：语音的**金额只从 `usage_records` 来**。

    `model_calls` 里那条语音行是为「调了几次、多慢、成没成」留的。
    把它也算进金额，一次合成会被计两遍 —— 而且看板、明细、预算三处
    会一起错，看不出任何异常。
    """
    _voice("tts", units=3000, cost=0.6)
    # 账本里那次调用的 est_cost 故意给一个大得多的数：它一个零头都不该进合计
    _llm(kind="tts", tokens=0, cost=99.0, ref_type="", course_id="")
    _commit()

    data = client.get("/api/usage/summary").get_json()["data"]
    by_kind = {item["kind"]: item for item in data["byKind"]}

    assert data["totals"]["estCost"] == pytest.approx(0.6)
    assert by_kind["tts"]["totalUnits"] == 3000
    assert by_kind["tts"]["estCost"] == pytest.approx(0.6)


def test_the_board_groups_by_day_course_and_kind(app, client):
    _course("c_1")
    _course("c_2", title="另一门课")
    _commit()
    _llm(prompt=100, cost=1.0, course_id="c_1")
    _llm(prompt=100, cost=2.0, course_id="c_2")
    _voice("tts", units=500, cost=0.5, course_id="c_1")
    _commit()

    by_day = client.get("/api/usage/summary?groupBy=day").get_json()["data"]["items"]
    by_course = client.get("/api/usage/summary?groupBy=course").get_json()["data"]["items"]
    by_kind = client.get("/api/usage/summary?groupBy=kind").get_json()["data"]["items"]

    # 横轴是**连续**的 30 天：没花钱的那些天也在（值是 0），不是缺席 ——
    # 折线图少一天与「那天花了 0 元」在图上长得完全不一样
    assert len(by_day) == 30
    assert (by_day[0]["key"], by_day[0]["estCost"]) == (days.today(), pytest.approx(3.5))
    assert all(item["estCost"] == 0.0 for item in by_day[1:])
    assert {item["key"]: item["estCost"] for item in by_course} == {
        "c_1": pytest.approx(1.5),
        "c_2": pytest.approx(2.0),
    }
    # 四条链路一条都不少（没量的那条是 0），顺序固定按声明序 —— 图例的条数
    # 不该随这个月的用量变
    assert [item["kind"] for item in by_kind] == ["llm", "tts", "realtime", "asr"]
    assert by_kind[2]["calls"] == 0
    # 「按链路分组」的 items 与 `byKind` 是同一份东西（同一个函数出的），
    # 前端不必为同一种分组写两套解包
    assert by_kind == client.get("/api/usage/summary").get_json()["data"]["byKind"]


def test_an_unknown_group_by_falls_back_to_day(app, client):
    """看板是打开的第一屏：为拼错的参数把它变成一页报错，不如给一份能看的图。"""
    data = client.get("/api/usage/summary?groupBy=month").get_json()["data"]

    assert data["groupBy"] == "day"


def test_each_kind_carries_its_own_unit_name(app, client):
    """四条链路的「用了多少」单位不同，回给前端的每一行都得自带单位名。

    llm 是 token、tts 是字符、asr/realtime 是秒 —— 前端拿到的每一行
    都自带 `unitName`，不必在页面里再写一份「哪个链路配哪个单位」的映射
    （那种映射迟早与后端不一致，而且不会报错，只会显示错单位）。
    """
    _llm(prompt=100, cost=0.1)
    _voice("tts", units=300, cost=0.1)
    _voice("asr", units=90, cost=0.1)
    _voice("realtime", units=30, cost=0.1)
    _commit()

    data = client.get("/api/usage/summary").get_json()["data"]

    assert {item["kind"]: item["unitName"] for item in data["byKind"]} == {
        "llm": "tokens",
        "tts": "chars",
        "asr": "seconds",
        "realtime": "seconds",
    }


def test_the_board_says_when_no_price_is_configured(app, client):
    """没配单价时合计是**少报**的 —— 界面要能说出来，而不是显示一个 0.00。"""
    _llm(prompt=1000, cost=0.0)
    _commit()

    data = client.get("/api/usage/summary").get_json()["data"]

    assert data["priced"] is False
    assert data["totals"]["estCost"] == 0.0


def test_prices_are_estimates_and_say_so_in_every_response(app, client):
    """每个响应都带 `note`：本机价目表乘出来的数，与上游账单不会逐分对上。"""
    assert client.get("/api/usage/summary").get_json()["data"]["note"] == "估算值，以账单为准"
    assert client.get("/api/usage/models").get_json()["data"]["note"] == "估算值，以账单为准"


# --- 单课明细（P5 §4.2）---


def test_course_detail_lists_every_call_of_that_course(app, client):
    _course("c_1")
    _course("c_2")
    _commit()
    _llm(prompt=1000, completion=200, cost=1.2, course_id="c_1")
    _llm(prompt=1000, cost=9.9, course_id="c_2")
    _voice("tts", units=300, cost=0.3, course_id="c_1")
    _commit()

    data = client.get("/api/usage/courses/c_1").get_json()["data"]

    assert data["total"] == 2
    assert {item["kind"] for item in data["items"]} == {"llm", "tts"}
    assert data["items"][0]["at"] > data["items"][1]["at"], "新的排在前面"


def test_the_detail_adds_up_to_the_same_number_as_the_board(app, client):
    """明细与看板必须是同一个口径 —— 加不起来的那两个数，用户没法选该信谁。"""
    _course("c_1")
    _commit()
    _llm(prompt=1000, completion=500, cost=1.5, course_id="c_1")
    _voice("tts", units=1000, cost=0.4, course_id="c_1")
    _commit()

    detail = client.get("/api/usage/courses/c_1").get_json()["data"]

    assert sum(item["estCost"] for item in detail["items"]) == pytest.approx(1.9)


def test_the_detail_of_someone_elses_course_is_a_404(app, client):
    """P3-F4：越权与不存在同一个答案 —— 403 等于承认「这个 id 存在，只是不给你看」。"""
    from app.models import User

    db.session.add(User(id="u_other", name="别的老师", role="teacher"))
    _commit()
    _course("c_1", owner_id="u_other")
    _commit()

    assert client.get("/api/usage/courses/c_1").status_code == 404
    assert client.get("/api/usage/courses/c_不存在").status_code == 404


def test_the_detail_limit_is_clamped(app, client):
    """`limit=0` 不是「一次回全部」（那是分页最常见的一个坑：
    手滑传 0 就把整张账本甩给前端，量大的时候页面直接卡死）。

    夹到 1 —— 「你要 0 条」与「你要 1 条」在界面上没有区别，
    而多回一条不会撑爆任何东西。负偏移则夹回 0。
    """
    _course("c_1")
    _commit()
    for _ in range(3):
        _llm(prompt=10, cost=0.1, course_id="c_1")
    _commit()

    assert len(client.get("/api/usage/courses/c_1?limit=0").get_json()["data"]["items"]) == 1
    assert len(client.get("/api/usage/courses/c_1?limit=2").get_json()["data"]["items"]) == 2
    assert len(client.get("/api/usage/courses/c_1?offset=9").get_json()["data"]["items"]) == 0
    assert len(client.get("/api/usage/courses/c_1?offset=-5").get_json()["data"]["items"]) == 3


# --- 价目表接口 ---


def test_the_models_endpoint_carries_the_price_list_and_the_live_models(app, client):
    data = client.get("/api/usage/models").get_json()["data"]

    assert {row["kind"] for row in data["pricing"]} == {"llm", "tts", "asr", "realtime"}
    assert data["unit"] == "CNY"
    # 每个模型都带着「配了价没有」：价目表里有个没人用的模型，
    # 与「有个模型没配价」是两件事，界面要能分别提示
    assert all("priced" in row for row in data["pricing"])


# --- 日缓存（F5-7）---


def test_a_past_day_is_cached_and_today_never_is(app, client):
    """今天随时在变，存下来下一秒就是错的；过去的日子只算一次。"""
    yesterday = days.window().days[-2]
    _llm(day=yesterday, prompt=1000, cost=1.0)
    _commit()

    client.get("/api/usage/summary").get_json()

    cached = {row.date for row in DailyUsage.query.all()}
    assert yesterday in cached
    assert days.today() not in cached


def test_a_day_with_no_spend_still_gets_four_zero_rows(app, client):
    """缓存完整性的判据是「四个 kind 的行都在」。

    少写这几条 0 行，读的那边就会把「没花过钱」误判成「没缓存」，
    于是每次都重算 —— 缓存形同虚设，而且是静默的。
    """
    yesterday = days.window().days[-2]
    _llm(day=yesterday, prompt=100, cost=0.5)
    _commit()

    client.get(f"/api/usage/summary?from={yesterday}&to={yesterday}").get_json()

    rows = DailyUsage.query.filter_by(date=yesterday).all()
    assert sorted(row.kind for row in rows) == ["asr", "llm", "realtime", "tts"]
    assert sum(row.total_tokens for row in rows) == 100
    assert sum(row.est_cost for row in rows) == pytest.approx(0.5)


def test_the_cache_reads_back_the_same_number(app, client):
    """先看一次（写缓存），再看一次（读缓存）—— 两次的合计必须一样。

    `monkeypatch` 那段这里刻意没有：读缓存这件事看的是**结果**，
    两次响应对不上就说明缓存这条路自己算了一遍别的数。
    """
    yesterday = days.window().days[-2]
    _llm(day=yesterday, prompt=1000, completion=500, cost=1.75)
    _voice("tts", day=yesterday, units=800, cost=0.2)
    _commit()

    first = client.get(f"/api/usage/summary?from={yesterday}&to={yesterday}").get_json()["data"]
    second = client.get(f"/api/usage/summary?from={yesterday}&to={yesterday}").get_json()["data"]

    assert DailyUsage.query.count() == 4, "第二天再来应该直接读缓存，不该又写一遍"
    assert first["totals"] == second["totals"] == {
        "totalTokens": 1500,
        "totalUnits": 800,
        "estCost": pytest.approx(1.95),
        "calls": 2,
    }


def test_refresh_recomputes_a_day_whose_ledger_arrived_late(app, client):
    """跨日迟到的账：后台线程在午夜后写完的那一行落在昨天，而昨天的缓存已经生成。

    重算（而不是累加）是这里的关键：累加会把上一次已经算过的再算一遍。
    """
    yesterday = days.window().days[-2]
    _llm(day=yesterday, prompt=1000, cost=1.0)
    _commit()
    client.get(f"/api/usage/summary?from={yesterday}&to={yesterday}").get_json()

    # 迟到的一笔
    _llm(day=yesterday, prompt=500, cost=0.5)
    _commit()
    report = aggregate.refresh(day=yesterday)

    rows = DailyUsage.query.filter_by(date=yesterday, kind="llm").all()
    assert report["rows"] == 4
    assert len(rows) == 1, "同一天同一链路只有一行（唯一约束）"
    assert rows[0].total_tokens == 1500
    assert rows[0].est_cost == pytest.approx(1.5)


def test_refreshing_today_writes_nothing(app):
    """今天那份只算不存 —— 报告里照样说「处理过」，否则运维以为脚本漏了今天。"""
    report = aggregate.refresh(day=days.today())

    assert report["days"] == [days.today()]
    assert DailyUsage.query.count() == 0


def test_the_refresh_cli_is_registered(app):
    """命令要能被 `flask usage-refresh` 调到（部署方挂 cron 的那个入口）。"""
    from app.services.usage.aggregate import register_cli

    assert callable(register_cli)


# --- 预算（F5-8 / P5-A8）---


def _set_budget(client, **body) -> dict:
    response = client.put("/api/settings/budget", json=body)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def test_the_two_fixed_scopes_are_always_returned(app, client):
    """`global` / `day` 没设过也返回一条默认的（0 = 不限）—— 设置页才有东西可填。"""
    data = client.get("/api/settings/budget").get_json()["data"]

    assert {row["scope"] for row in data["budgets"]} == {"global", "day"}
    assert all(row["limitCost"] == 0 for row in data["budgets"]), "缺省 = 不限"
    # 单课那一档在「当前用量」里有个位置（说的是「哪门课都还没指定」），
    # 但没设过就没有那一行 —— 一条 refId 为空的单课预算就是 global 的意思
    assert set(data["current"]) == {"global", "course", "day"}


def test_a_course_budget_carries_its_own_courses_usage(app, client):
    """设置页列出几条单课预算时，每一行比的必须是**各自那门课**花掉的钱。

    拿一个全局的数铺在三行上是另一种意思，而且看起来完全正常：
    「这门课已用 9.9 元」其实说的是全部课程，用户据此调预算会调错。
    """
    _course("c_1")
    _course("c_2")
    _commit()
    _llm(course_id="c_1", prompt=100, cost=4.5)
    _llm(course_id="c_2", prompt=100, cost=9.9)
    _commit()
    _set_budget(client, scope="course", refId="c_1", limitCost=5.0)
    _set_budget(client, scope="course", refId="c_2", limitCost=50.0)

    rows = {
        row["refId"]: row
        for row in client.get("/api/settings/budget").get_json()["data"]["budgets"]
        if row["scope"] == "course"
    }

    assert rows["c_1"]["usedCost"] == pytest.approx(4.5), "c_1 的数别把 c_2 的算进来"
    assert rows["c_2"]["usedCost"] == pytest.approx(9.9)
    assert rows["c_1"]["alert"] is True, "4.5 / 5 已经过了 80% 的告警线"
    assert rows["c_1"]["over"] is False, "告警不等于超限"
    assert rows["c_2"]["alert"] is False


def test_zero_means_unlimited_and_blocks_nothing(app, client):
    """0 是「不限」，不是「限额为零」—— 写成后者的话，设完日预算一门课都开不了。"""
    _set_budget(client, scope="day", limitCost=0, limitTokens=0)
    _llm(prompt=10**6, cost=999.0)
    _commit()

    assert budget.check()["allowed"] is True


def test_a_cost_overrun_refuses_with_the_scope_and_the_number(app, client):
    _llm(prompt=1000, cost=3.0)
    _commit()
    _set_budget(client, scope="day", limitCost=2.0)

    verdict = budget.check()

    assert verdict["allowed"] is False
    assert (verdict["scope"], verdict["by"]) == ("day", "cost")
    assert "2" in verdict["reason"], "文案要说清超的是哪一条、超了多少"


def test_a_token_overrun_is_reported_as_a_token_overrun(app, client):
    """「你超了 0.3 元」和「你超了 12 万 token」是两个不同的动作
    （去改预算 / 少生成几页），报出来的必须是撞上的那一个。"""
    _llm(prompt=5000, completion=1000, cost=0.01)
    _commit()
    _set_budget(client, scope="global", limitTokens=3000, limitCost=999)

    verdict = budget.check()

    assert (verdict["scope"], verdict["by"]) == ("global", "tokens")
    assert verdict["usedTokens"] == 6000


def test_a_course_budget_only_counts_that_course(app, client):
    _course("c_1")
    _course("c_2")
    _commit()
    _llm(course_id="c_1", prompt=100, cost=1.0)
    _llm(course_id="c_2", prompt=100, cost=50.0)
    _commit()
    _set_budget(client, scope="course", refId="c_1", limitCost=5.0)

    assert budget.check(course_id="c_1")["allowed"] is True
    assert budget.check(course_id="c_2")["allowed"] is True, "别的课贵不该拦这一门"
    assert budget.check()["allowed"] is True, "不指定课程时不判单课"


def test_the_alert_ratio_warns_without_blocking(app, client):
    """用量到告警线只让界面变黄，**不拦任何事**。

    提前拦住一个还没超预算的请求，用户看到的是「我明明还有额度，它却说超了」。
    """
    _llm(prompt=100, cost=8.0)
    _commit()
    _set_budget(client, scope="day", limitCost=10.0, alertRatio=0.8)

    status = client.get("/api/settings/budget").get_json()["data"]["current"]["day"]

    assert status["alert"] is True
    assert budget.check()["allowed"] is True


def test_a_disabled_budget_is_ignored(app, client):
    _llm(prompt=100, cost=100.0)
    _commit()
    _set_budget(client, scope="day", limitCost=1.0, enabled=False)

    assert budget.check()["allowed"] is True


def test_ensure_allowed_raises_a_40902_with_a_machine_readable_reason(app, client):
    _llm(prompt=100, cost=100.0)
    _commit()
    _set_budget(client, scope="day", limitCost=1.0)

    with pytest.raises(StateError) as caught:
        budget.ensure_allowed()

    assert caught.value.code == 40902
    assert caught.value.details["error"] == "budget_exceeded"
    assert caught.value.details["scope"] == "day"


def test_a_course_budget_must_name_a_course(app, client):
    """不带 refId 的单课预算就是「所有课程」，而那是 global 的意思 ——
    让它悄悄退化成全局，用户会以为设的是单课。"""
    response = client.put("/api/settings/budget", json={"scope": "course", "limitCost": 1})

    assert response.status_code == 400
    assert response.get_json()["code"] == 40001


def test_a_bad_scope_is_a_40001(app, client):
    response = client.put("/api/settings/budget", json={"scope": "weekly", "limitCost": 1})

    assert response.status_code == 400
    assert response.get_json()["code"] == 40001


def test_a_negative_limit_is_a_40001(app, client):
    response = client.put("/api/settings/budget", json={"scope": "day", "limitCost": -1})

    assert response.status_code == 400
    assert response.get_json()["code"] == 40001


def test_the_budget_response_carries_the_used_amount(app, client):
    """设置页要显示「日预算 10 元，今天已用 3.2 元」——
    分两次请求去拼，两半数字会来自不同时刻。"""
    _llm(prompt=1000, cost=3.2)
    _commit()
    _set_budget(client, scope="day", limitCost=10.0)

    row = next(
        item
        for item in client.get("/api/settings/budget").get_json()["data"]["budgets"]
        if item["scope"] == "day"
    )

    assert row["usedCost"] == pytest.approx(3.2)
    assert row["limitCost"] == pytest.approx(10.0)


def test_the_budget_is_enforced_before_a_course_is_created(app, client):
    """P5-A8：超预算的任务**建都不该建**。

    先建课再拒的话，用户的课程列表里会多出一门永远停在 `generating` 的课，
    而它自己不会消失 —— 每一次生成都会再被拒一次。
    """
    from app.models import GenJob

    _llm(prompt=1000, cost=9.0)
    _commit()
    _set_budget(client, scope="day", limitCost=1.0)

    response = client.post("/api/courses/generate", json={"topic": TOPIC})

    assert response.status_code == 409
    assert response.get_json()["code"] == 40902
    # details 在 data.details 里（4 键信封不变，见 `common/response.py`）
    details = response.get_json()["data"]["details"]
    assert details["error"] == "budget_exceeded"
    assert details["scope"] == "day"
    assert Course.query.count() == 0, "被拒的请求不该留下课程"
    assert GenJob.query.count() == 0, "也不该留下任务"


def test_a_job_started_under_the_limit_runs_and_records_its_cost(app, client, monkeypatch):
    """预算没超时生成照常跑，而且每一步的调用都带着 `step_id` 进账本 ——
    「钱花在哪一步」是任务时间线（F5-10）唯一的数据来源。"""
    from app.services.generation import pipeline
    from tests.unit.test_generation_pipeline import StubLLM

    monkeypatch.setattr(pipeline, "_provider", lambda: StubLLM(chapters=1, pages_per_chapter=1))
    _set_budget(client, scope="day", limitCost=100.0)

    started = client.post("/api/courses/generate", json={"topic": TOPIC}).get_json()["data"]
    from app.common import tasks

    assert tasks.wait_for(started["jobId"], 30)

    calls = ModelCall.query.filter_by(kind="llm").all()
    assert calls, "生成期的模型调用必须进账本（P5-C2）"
    assert all(call.step_id for call in calls), "每一笔都该记着它在哪一步上"
    assert all(call.owner_id for call in calls)
    # 账本里那些行的 token 合计要与任务自己报的一致（P1-D4 已经在按 job_id 求和）
    from app.models import GenJob

    job = db.session.get(GenJob, started["jobId"])
    assert job is not None
    assert sum(call.tokens for call in calls) == job.total_tokens


def test_the_settings_page_can_maintain_the_price_list(app, client):
    """§4.2 说价格表「可在设置页维护」—— 读在 `/api/usage/models`，写在这里。

    改完立刻生效（不必重启），而且**打底的那些配置价还在**：整段覆盖的是
    用户写的那一层，不是把 `.env` 里运维配的那一层也抹掉。
    """
    app.config["LLM_PRICE_PROMPT_PER_1K"] = 1.0

    response = client.put(
        "/api/settings/pricing",
        json={"llm": {"deepseek-chat": {"promptPer1k": 4, "completionPer1k": 6}}},
    )

    assert response.status_code == 200
    assert pricing.estimate_llm("deepseek-chat", 1000, 1000) == pytest.approx(10.0)
    assert pricing.estimate_llm("别的模型", 1000, 0) == pytest.approx(1.0), "通配价还在打底"


def test_a_bad_price_list_is_a_40001(app, client):
    response = client.put("/api/settings/pricing", json={"llm": {"m": {"promptPer1k": -1}}})

    assert response.status_code == 400
    assert response.get_json()["code"] == 40001


def test_the_budget_of_a_missing_course_is_rejected(app, client):
    response = client.put("/api/settings/budget", json={"scope": "course", "refId": "c_不存在"})

    assert response.status_code == 400
    assert response.get_json()["code"] == 40001


def test_a_voice_row_with_no_course_is_still_on_the_board(app, client):
    """**认不出归属的账不能从看板上消失**：钱是真花了的。

    `POST /api/voice/asr` 就是这一类 —— 它是一次没有课程的调用，
    P2 给它记的 `ref_id` 是 `"asr"`（端点的名字，不是任何一节课的 id）。
    「按人筛」那一步如果只认「这个人的课程 / 课堂」，这笔钱会**静默地**
    从看板上消失：界面照常显示，只是少了一块，而且没有任何东西提示。
    """
    _voice("asr", units=180, cost=0.9)  # ref_id 空 —— 认不出归属
    _commit()

    mine = client.get("/api/usage/summary", headers={OWNER_HEADER: ME}).get_json()["data"]

    assert mine["totals"]["estCost"] == pytest.approx(0.9)
    assert mine["totals"]["totalUnits"] == 180


def test_another_teachers_course_still_is_not_yours(app, client):
    """但**别人的课**必须还是别人的：`ref_id` 认得出归属时按归属算。

    上一条放宽的是「认不出归属」，不是「不认归属」——
    这两件事差一个字，混起来就是越权式的漏账。
    """
    from app.models import User

    db.session.add(User(id="u_other", name="别的老师", role="teacher"))
    _commit()
    _course("c_theirs", owner_id="u_other")
    _commit()
    _voice("tts", units=500, cost=3.0, course_id="c_theirs")
    _commit()

    mine = client.get("/api/usage/summary", headers={OWNER_HEADER: ME}).get_json()["data"]

    assert mine["totals"]["estCost"] == 0.0


def test_the_owner_header_does_not_leak_another_teachers_costs(app, client):
    """按人筛：别人的课与课堂用量不该出现在我的看板上。

    语音那半**不是**按行上那个 owner 筛的（`usage_records` 没有 owner 列），
    而是先查「这个人名下的课程 / 课堂」再按 ref 过滤 —— 两步都要对：
    少一步就会把别人的课算进我的「今天花了多少」，而预算正是拿它判的。
    """
    from app.models import User

    # 先落 `users` 再建课：课程对 users 有外键，同一个 flush 里的顺序
    # 由 SQLAlchemy 排，测试不该依赖它 —— 显式分两次提交最省心
    db.session.add(User(id="u_other", name="别的老师", role="teacher"))
    _commit()
    _course("c_mine")
    _course("c_theirs", owner_id="u_other")
    _commit()
    _llm(course_id="c_mine", prompt=100, cost=1.0, owner_id=ME)
    _llm(course_id="c_theirs", prompt=100, cost=7.0, owner_id="u_other")
    _voice("tts", course_id="c_theirs", units=100, cost=3.0)
    _commit()

    mine = client.get("/api/usage/summary", headers={OWNER_HEADER: ME}).get_json()["data"]
    theirs = client.get(
        "/api/usage/summary", headers={OWNER_HEADER: "u_other"}
    ).get_json()["data"]

    assert mine["totals"]["estCost"] == pytest.approx(1.0)
    assert theirs["totals"]["estCost"] == pytest.approx(10.0), "别人的账要算在他自己头上"


def test_a_course_budget_only_bites_that_course(app, client):
    """单课预算只拦它自己那门课：不指定课程时它一条都不判。

    「不指定就按所有课程判」看起来更严，实际是**误拒**：任何一个不带课程 id 的
    入口（工作台开新话题、单页重写）都会被某门课的余额拦住，而用户改那门课的
    预算根本解决不了问题。
    """
    _course("c_1")
    _course("c_2")
    db.session.add(Budget(scope="course", ref_id="c_1", limit_cost=0.01, enabled=True))
    _commit()
    _llm(course_id="c_1", prompt=1000, cost=5.0)
    _llm(course_id="c_2", prompt=1000, cost=5.0)
    _commit()

    assert budget.check(course_id="c_1")["allowed"] is False, "c_1 已经花超了"
    assert budget.check(course_id="c_2")["allowed"] is True, "c_2 的账不该算在 c_1 的限额上"
    assert budget.check(course_id="")["allowed"] is True, "不指定课程时不判单课"
