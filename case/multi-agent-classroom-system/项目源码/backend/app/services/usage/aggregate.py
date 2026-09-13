"""用量聚合与日缓存（P5 §4.2 / F5-7）。

### 两个账本，一个口径

金额与用量**逐链路各认一个来源**：

| 链路 | 用量与金额来自 | 为什么 |
|------|---------------|--------|
| `llm` | `model_calls`（kind='llm'） | P0 起 LLM 就记在这里，P5 补了输入输出拆分与金额 |
| `tts` / `asr` / `realtime` | `usage_records` | P2-A11 的「本次课堂花了多少」建在它上面，不改已验收的口径 |

`model_calls` 里也有语音那三条的行（P5-C2 要求账本覆盖全部四种调用），
但那些行**只进「调用次数 / 成败 / 耗时」的口径，不进金额与用量** ——
否则一次 TTS 会在金额里被算两遍。这条分工写在 P5 文档 §10.2，
也是 `ledger.py` 与 `usage_record.py` 两份 docstring 的共同落点。

### `daily_usage` 缓存：只缓存**已经过去**的日子

- **今天**随时在变 → 每次现算，也不写缓存（免得刚存下就过期）。
- **过去的日子**账已经不会再动 → 第一次用到时算一次、存下来，之后直接读。

缓存完整性的判据是「**四个 kind 的行都在**」：`_refresh_day` 连零用量的那天
也写四条 0（见那里的注释），所以「这天没有行」只可能是「还没算过」，
不可能与「这天没花过钱」混淆。唯一的例外是跨日迟到的账：后台线程在午夜后
写完的那一行落在昨天，而昨天的缓存已经生成 —— `refresh()` 就是为它准备的
（`flask usage-refresh`），它不做增量，直接把区间重算一遍。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.common.dbw import db_write
from app.common.identity import local_owner_id
from app.common.logging import get_logger
from app.extensions import db
from app.models import ClassroomSession, Course, DailyUsage, GenJob, ModelCall, UsageRecord, User
from app.models.budget import DAILY_KINDS
from app.models.telemetry import CALL_REF_TYPES
from app.models.usage_record import USAGE_KINDS
from app.services.usage import days, pricing

logger = get_logger("app.usage.aggregate")

#: 看板能按什么分组（P5 §4.2 的 `?groupBy=`）
GROUP_BYS = ("day", "course", "kind")

#: 每条链路的计量单位。看板上「12 次调用」这类数字要有来源，所以每个桶都带 `calls`
KIND_UNITS: Mapping[str, str] = {
    "llm": "tokens",
    "tts": "chars",
    "asr": "seconds",
    "realtime": "seconds",
}

#: 一次查询最多回多少条明细（`GET /api/usage/courses/{id}`）。
#: 它不是分页接口 —— 单课明细是给「这门课到底花在哪了」用的，几百条足够定位问题。
DETAIL_LIMIT = 200

#: `refresh()` 缺省重算几天。**2 而不是 1**：今天那一份只算不落库
#: （见 `refresh`），所以「最近 1 天」等于什么都没写。
#: 2 = 昨天 + 今天，正好覆盖「昨晚跨日迟到的账」这个唯一要补的场景。
DEFAULT_REFRESH_DAYS = 2

#: 求和时用的「上限」：不是分页，只是 SQL 的 limit 得给个数。
#: 单课预算要的是**全部**明细的和，取一个够大的数字比另写一条 COUNT/SUM 语句省事，
#: 也不会与明细页的求和口径分叉。
_ALL_ROWS = 10**6


@dataclass
class Entry:
    """一条**已经归一化**的用量记录。

    两个账本的行长得完全不一样（一个按 token、一个按字符/秒），
    聚合之前先把它们拍成同一个形状，后面分组的代码就只有一份。
    """

    kind: str
    day: str
    course_id: str
    tokens: int = 0
    units: int = 0
    cost: float = 0.0
    calls: int = 1

    def bucket(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "totalTokens": self.tokens,
            "totalUnits": self.units,
            "unitName": KIND_UNITS.get(self.kind, ""),
            "estCost": round(self.cost, 6),
            "calls": self.calls,
        }


def summary(
    *,
    date_from: str = "",
    date_to: str = "",
    group_by: str = "day",
    owner_id: str = "",
) -> dict[str, Any]:
    """成本看板的数（F5-7）。`groupBy` 决定 `items` 按什么分。

    返回里同时有一份 `byKind`：不管按什么分组，「四条链路各花了多少」
    都是看板上最该先看到的一行。分组是第二层。
    """
    if group_by not in GROUP_BYS:
        group_by = "day"
    span = days.window(date_from, date_to)
    entries = _entries(span, group_by, owner_id)

    return {
        "from": span.first,
        "to": span.last,
        "groupBy": group_by,
        "currency": "CNY",
        "items": _group(entries, group_by),
        # 与「按链路分组」是同一个形状（`_group` 在 kind 上直接走 `_by_kind`）：
        # 同一份数据在 `items` 与 `byKind` 里长得不一样，前端就得写两套解包
        "byKind": _by_kind(entries),
        "totals": _sum_of([entry.bucket() for entry in entries]),
        # 只要有一条链路没配单价，合计就是**少报**的 —— 界面得说出来
        "priced": all(pricing.priced(kind) for kind in DAILY_KINDS),
        # 这句话每个响应都带着走：它要在界面上出现，而不是只写在文档里
        "note": "估算值，以账单为准",
    }


def course_detail(course_id: str, *, limit: int = DETAIL_LIMIT, offset: int = 0) -> dict[str, Any]:
    """单课明细：这门课的每一次 LLM / 语音调用（P5 §4.2）。

    与看板的口径一致 —— 这里也是「LLM 取账本、语音取用量表」，
    所以把明细的 `estCost` 加起来，等于看板上这门课那个数。
    """
    rows = [_llm_row(call) for call in _llm_calls_of_course(course_id)]
    rows += [_voice_row(row) for row in _voice_rows_of_course(course_id)]
    rows.sort(key=lambda item: str(item["at"]), reverse=True)

    start = max(0, int(offset))
    page = rows[start : start + max(1, int(limit))]
    return {
        "courseId": course_id,
        "items": page,
        "total": len(rows),
        "byKind": _by_kind(_entry_of_row(row) for row in rows),
        "note": "估算值，以账单为准",
    }


def totals(
    *,
    course_id: str = "",
    date_from: str = "",
    date_to: str = "",
    owner_id: str = "",
) -> dict[str, Any]:
    """一段时间 / 一门课花了多少：金额 + token + 各单位量。

    **预算判超限走的就是它**，不另写一份求和：预算与看板对不上时，
    用户没有任何办法判断该信哪个（见 `budget.py` 的模块 docstring）。

    金额与 token 一起给，是因为预算的两个上限（`limitCost` / `limitTokens`）
    是**或**的关系（见 `models/budget.py`）—— 分成两次查询取同一批行，
    只是多扫一遍库，还有可能两次之间又来了新的调用、两个数对不上。

    日期**两个都不给 = 不限时间**（不是「最近 30 天」）：`global` 预算问的是
    「从有账以来一共花了多少」，套上看板的那个 30 天缺省值就成了另一种意思。
    只给一头时另一头才按今天补齐。给了 `course_id` 就只看那门课。
    """
    if course_id:
        detail = course_detail(course_id, limit=_ALL_ROWS)
        entries = [_entry_of_row(row) for row in detail["items"]]
    else:
        if not date_from and not date_to:
            start = end = ""
        else:
            span = days.window(date_from, date_to)
            start, end = span.start, span.end
        entries = _range_entries(start, end, owner_id)

    by_kind: dict[str, dict[str, Any]] = {}
    for entry in entries:
        slot = by_kind.setdefault(
            entry.kind,
            {"kind": entry.kind, "totalTokens": 0, "totalUnits": 0, "estCost": 0.0, "calls": 0},
        )
        slot["totalTokens"] += entry.tokens
        slot["totalUnits"] += entry.units
        slot["estCost"] = round(slot["estCost"] + entry.cost, 6)
        slot["calls"] += entry.calls

    return {
        "kinds": [by_kind[kind] for kind in DAILY_KINDS if kind in by_kind],
        **_sum_of(list(by_kind.values())),
        "courseId": course_id,
    }


def spend(
    *,
    course_id: str = "",
    date_from: str = "",
    date_to: str = "",
    owner_id: str = "",
) -> float:
    """`totals()` 里那个金额。单独留一个函数是因为「花了多少元」被问得最多。"""
    return float(
        totals(course_id=course_id, date_from=date_from, date_to=date_to, owner_id=owner_id)[
            "estCost"
        ]
    )


def refresh(
    day: str = "", *, days_back: int = DEFAULT_REFRESH_DAYS, owner_id: str | None = None
) -> dict[str, Any]:
    """重算 `daily_usage`（F5-7 的缓存，`flask usage-refresh` 调它）。

    给了 `day` 就只重算那一天；不给就重算「最近 `days_back` 天（含今天）」。
    **重算而不是累加**：派生数据累加两次就是把账算两遍，而重算永远不会错。

    今天那一份照常算、但**不落库**（它随时在变，存下来下一秒就是错的）。
    它在报告里照样算「处理过」，否则运维会以为是脚本漏了今天 ——
    也正因为它不算数，缺省值才不是 1：`days_back=1` 覆盖的只有今天，
    也就是说这次调用一行都不会写。

    **默认重算所有人的缓存**（`_owners`）：缓存是「天 × 链路 × 归属人」，
    看板读的是**当前这个人**的那一份。只算空串的话，单机默认那个老师
    （有 id）读到的还是旧缓存 —— 命令打印「已重算 4 行」，界面上一个数都没变。
    """
    chosen = days.clean(day)
    recent = days.window("", days.today()).days
    targets = [chosen] if chosen else recent[-max(1, int(days_back)) :]
    owners = [owner_id] if owner_id is not None else _owners()

    today = days.today()
    written = 0
    for target in targets:
        for owner in owners:
            written += len(_refresh_day(target, owner_id=owner, cache=target < today))
    return {"days": targets, "owners": owners, "rows": written}


def _owners() -> list[str]:
    """账本里出现过的归属人，外加空串这个「还没归属」的桶。

    三处都扫：用户表（**谁在读缓存就是谁**，哪怕他一行账都还没有）、
    LLM 账（带 `owner_id`）、语音账（按课程归属，`usage_records` 没有 owner 列）。
    少扫一处，那个人的那一份缓存就永远不重算 —— 而看板读的正是它。
    """
    seen = {str(row[0] or "") for row in db.session.query(User.id).all()}
    seen |= {str(row[0] or "") for row in db.session.query(ModelCall.owner_id).distinct().all()}
    seen |= {str(row[0] or "") for row in db.session.query(Course.owner_id).distinct().all()}
    return sorted(seen)


def _refresh_day(day: str, *, owner_id: str, cache: bool) -> list[DailyUsage]:
    """把某一天的聚合写回 `daily_usage`（`cache=False` 时只算不写，见 `refresh`）。

    **四个 kind 都写，零用量的写 0。** 这一条是缓存能不能被信任的关键：
    只有「这天有行」与「这天算过」是同一件事，读的时候才敢用「没有行」表示
    「还没算」。少写一条 0 行，读的那边就会把「没花过钱」误判成「没缓存」，
    于是每次都重算 —— 缓存形同虚设，而且是静默的。
    """
    start, end = days.bounds(day)
    grouped: dict[str, Entry] = {}
    for entry in _range_entries(start, end, owner_id):
        current = grouped.get(entry.kind)
        if current is None:
            grouped[entry.kind] = Entry(
                kind=entry.kind, day=day, course_id="",
                tokens=entry.tokens, units=entry.units, cost=entry.cost, calls=entry.calls,
            )
        else:
            current.tokens += entry.tokens
            current.units += entry.units
            current.cost += entry.cost
            current.calls += entry.calls

    rows: list[DailyUsage] = []
    for kind in DAILY_KINDS:
        bucket = grouped.get(kind)
        rows.append(
            DailyUsage(
                date=day,
                owner_id=owner_id,
                kind=kind,
                total_tokens=bucket.tokens if bucket else 0,
                total_units=bucket.units if bucket else 0,
                est_cost=round(bucket.cost, 6) if bucket else 0.0,
                calls=bucket.calls if bucket else 0,
            )
        )

    if cache:
        def _work() -> None:
            # 整天的行一起换掉（不是逐条 upsert）：重算的结果就是这一天的事实，
            # 先删后加不需要假设「上次写过哪几条」。
            DailyUsage.query.filter_by(date=day, owner_id=owner_id).delete()
            for row in rows:
                db.session.add(row)

        db_write(_work)
    return rows


def _cached_days(span: days.Range, owner_id: str) -> dict[str, list[Entry]]:
    """过去那些天的缓存。缺的那天现算一次并写进去。

    今天**不读缓存也不写** —— 见模块 docstring。
    """
    today = days.today()
    ready: dict[str, list[Entry]] = {}
    for day in [item for item in span.days if item < today]:
        entries = _read_cache(day, owner_id)
        if entries is None:
            entries = _entries_of(_refresh_day(day, owner_id=owner_id, cache=True))
        ready[day] = entries
    return ready


def _read_cache(day: str, owner_id: str) -> list[Entry] | None:
    """某一天的缓存。四个 kind 不齐就给 None（= 没算过），见 `_refresh_day`。"""
    rows = DailyUsage.query.filter_by(date=day, owner_id=owner_id).all()
    by_kind = {row.kind: row for row in rows}
    if len(by_kind) < len(DAILY_KINDS):
        return None
    return [
        Entry(
            kind=kind,
            day=day,
            course_id="",
            tokens=int(getattr(by_kind[kind], "total_tokens", 0) or 0),
            units=int(getattr(by_kind[kind], "total_units", 0) or 0),
            cost=float(getattr(by_kind[kind], "est_cost", 0.0) or 0.0),
            calls=int(getattr(by_kind[kind], "calls", 0) or 0),
        )
        for kind in DAILY_KINDS
    ]


def _entries_of(rows: Sequence[DailyUsage]) -> list[Entry]:
    """缓存行 → 条目。`course_id` 是空的：`daily_usage` 按天 × 链路聚合，
    它回答不了「哪门课」（那要走 `group_by="course"` 的现算路径，见 `_entries`）。"""
    return [
        Entry(
            kind=row.kind,
            day=row.date,
            course_id="",
            tokens=int(row.total_tokens or 0),
            units=int(row.total_units or 0),
            cost=float(row.est_cost or 0.0),
            calls=int(row.calls or 0),
        )
        for row in rows
    ]


# --------------------------------------------------------------------------
# 取数：按天走缓存，其余现算
# --------------------------------------------------------------------------


def _entries(span: days.Range, group_by: str, owner_id: str) -> list[Entry]:
    """全窗口的条目。

    **只有按天分组时才走缓存**：`daily_usage` 的主键是「天 × 链路」，
    它天然回答不了「哪门课花了多少」。按课程分组本来就得扫两个账本，
    再把缓存拼进来只会让口径多一条分叉。
    """
    if group_by != "day":
        return _range_entries(span.start, span.end, owner_id)

    today = days.today()
    entries: list[Entry] = []
    for day_entries in _cached_days(span, owner_id).values():
        entries += day_entries
    if today in span.days:
        # 今天现算：它每分钟都在变，缓存下来下一秒就是错的
        start, end = days.bounds(today)
        entries += _range_entries(start, end, owner_id)
    return entries


def _range_entries(start: str, end: str, owner_id: str) -> list[Entry]:
    return [
        *(_llm_entry(row) for row in _llm_rows(start, end, owner_id)),
        *(_voice_entry(row) for row in _voice_rows(start, end, owner_id)),
    ]


def _between(column: Any, start: str, end: str) -> list[Any]:
    """`created_at` 的区间条件。**空串 = 不限那一头**（`spend` 要「从有账以来」）。

    不能直接把空串塞进比较里：`created_at < ''` 在 SQLite 的字符串序里恒为假，
    于是「不限结束时间」会变成「一条都不要」—— 一个安静地少报全部的 bug。
    """
    conditions = []
    if start:
        conditions.append(column >= start)
    if end:
        conditions.append(column < end)
    return conditions


def _llm_rows(start: str, end: str, owner_id: str) -> list[ModelCall]:
    # kind='llm' 之外的行也在表里（语音那三条，见模块 docstring）——
    # 它们不进金额，所以这里就把它们挡在外面，而不是留给下游去过滤。
    query = ModelCall.query.filter(ModelCall.kind == "llm", *_between(ModelCall.created_at, start, end))
    if owner_id:
        if owner_id == local_owner_id():
            # 没有归属的行（P0 时期建的课、拿不到请求上下文的后台线程写的行）
            # 算本机主人的 —— 与 `_orphan_refs` 同一条理由：钱是真花了的，
            # 让它从看板上消失比让它多算一笔更糟。别人的行仍有 owner_id，不受影响。
            query = query.filter(
                db.or_(ModelCall.owner_id == owner_id, ModelCall.owner_id == "")
            )
        else:
            query = query.filter(ModelCall.owner_id == owner_id)
    return list(query.all())


def _voice_rows(start: str, end: str, owner_id: str) -> list[UsageRecord]:
    """窗口内的语音用量。

    `usage_records` 没有 owner 列（P2 的账挂在课程或课堂上，见它的模型 docstring），
    所以「按人筛」要先把这个人名下的课程与课堂查出来，再按 ref 过滤。
    这个条件只在**真的传了 owner** 时才走：单机部署下 owner 只有一个，
    路径本来就不会经过这里。

    两条筛选规则，第二条是补第一条的漏：
    1. 这个人的课程 / 课堂名下的账；
    2. **认不出归属的账**（`_orphan_refs`）算本机主人头上 ——
       没有它，独立 ASR 那种没有课程可挂的花费在看板上永远不出现，
       而用户明明在付这笔钱。
    """
    query = UsageRecord.query.filter(*_between(UsageRecord.created_at, start, end))
    if owner_id:
        course_ids = [row.id for row in Course.query.filter_by(owner_id=owner_id).all()]
        session_ids = (
            [
                row.id
                for row in ClassroomSession.query.filter(
                    ClassroomSession.course_id.in_(course_ids)
                ).all()
            ]
            if course_ids
            else []
        )
        conditions = _present(
            [
                _ref_in(UsageRecord.ref_id, course_ids, wrap=UsageRecord.ref_type == "course"),
                _ref_in(UsageRecord.ref_id, session_ids, wrap=UsageRecord.ref_type == "session"),
            ]
        )
        if owner_id == local_owner_id():
            conditions.append(_orphan_refs())
        if not conditions:
            # 这个人名下什么都没有，也没有一行账能算在他头上。
            # **不能把空条件交给 `filter()`** —— 那等于不加条件，把全库的账都算给他，
            # 而「刚注册、什么都还没有」正是每个账号的第一天。
            return []
        # or：一门课的账与一节课的账是两条并列的归属路径（见 `_voice_rows_of_course`）
        query = query.filter(db.or_(*conditions))
    return list(query.all())


def _orphan_refs() -> Any:
    """`ref` 认不出归属的那些行：`ref_id` 为空，或者指着一个不存在的课程 / 课堂。

    独立 ASR（`POST /api/voice/asr`）就是这一类：它是一次**没有课程的调用**，
    P2 给它记的是 `ref_type="session", ref_id="asr"` —— 那是「这个端点」的标记，
    不是任何一节课的 id。它答不出「这笔钱算谁的」，但钱是真花了。

    算给**本机主人**（谁问就给谁？不是 —— 只在问的人就是本机主人时才算）：
    这些行全库只有一份，多用户联调时给每个账号都算一遍就是重复计数。
    宁可让本机主人多认几笔，也不要让它们从看板上凭空消失。
    """
    known = [row.id for row in Course.query.all()]
    known += [row.id for row in ClassroomSession.query.all()]
    return ~UsageRecord.ref_id.in_(known)


# --------------------------------------------------------------------------
# 归属：这条账算在哪门课上
# --------------------------------------------------------------------------


def _llm_entry(row: ModelCall) -> Entry:
    return Entry(
        kind="llm",
        day=days.day_of(row.created_at),
        course_id=_course_of(row),
        tokens=int(row.tokens or 0),
        cost=float(row.est_cost or 0.0),
    )


def _voice_entry(row: UsageRecord) -> Entry:
    return Entry(
        kind=row.kind if row.kind in USAGE_KINDS else "tts",
        day=days.day_of(row.created_at),
        course_id=_course_of_ref(row.ref_type, row.ref_id),
        units=int(row.units or 0),
        cost=float(row.est_cost or 0.0),
    )


def _course_of(row: ModelCall) -> str:
    """账本里的一条调用属于哪门课。

    先看 ref_type 直接给没给出课程，再顺着 job 查一次 —— 两条路都要走：
    生成期的调用挂 `course`，课堂里补的那一页挂在 job 上（那时并没有新的课程）。
    """
    found = _course_of_ref(row.ref_type, row.ref_id)
    if found or not row.job_id:
        return found
    job = db.session.get(GenJob, row.job_id)
    return job.course_id if job is not None else ""


def _course_of_ref(ref_type: str, ref_id: str) -> str:
    """`(ref_type, ref_id)` → course_id。认不出来给空串（账仍进总数，只是不归属某课）。"""
    text = str(ref_id or "")
    if not text:
        return ""
    if ref_type in ("course", "chat"):
        return text
    if ref_type == "session":
        session = db.session.get(ClassroomSession, text)
        return session.course_id if session is not None else ""
    if ref_type == "job":
        job = db.session.get(GenJob, text)
        return job.course_id if job is not None else ""
    if ref_type in CALL_REF_TYPES:  # pragma: no cover - 四个值上面都认过了
        return ""
    # ref_type 是空串（P5 之前写下的老账）：ref_id 可能是课程 id，也可能不是。
    # 当课程试一次 —— 认不出来就给空串，不会把账挂到别人的课上。
    return text if db.session.get(Course, text) is not None else ""


def _llm_calls_of_course(course_id: str) -> list[ModelCall]:
    """这门课的 LLM 调用。

    归属有三条路（`ref_type` 各不同），**按课程取的时候三条都要认**：
    生成走 `course`，工作台改课走 `chat`（ref_id 就是课程 id），
    课堂里点「补一页」走的是 job。漏掉一条，这门课的明细就会少一块。
    """
    conditions = [
        (ModelCall.ref_type == "course") & (ModelCall.ref_id == course_id),
        (ModelCall.ref_type == "chat") & (ModelCall.ref_id == course_id),
        _ref_in(ModelCall.job_id, _job_ids_of_course(course_id)),
    ]
    # **是 or 不是 and**：三条路各自都足以把一条调用算在这门课上。
    # 交给 `filter(a, b, c)` 会被逗号连成 and（SQLAlchemy 的 `filter(*args)`
    # 是「全部满足」），那样一条都匹配不上 —— 而现象是「明细几乎全空」。
    return list(
        ModelCall.query.filter(
            ModelCall.kind == "llm", db.or_(*_present(conditions))
        ).all()
    )


def _job_ids_of_course(course_id: str) -> list[str]:
    return [row.id for row in GenJob.query.filter_by(course_id=course_id).all()]


def _voice_rows_of_course(course_id: str) -> list[UsageRecord]:
    session_ids = [
        row.id for row in ClassroomSession.query.filter_by(course_id=course_id).all()
    ]
    conditions = [
        (UsageRecord.ref_type == "course") & (UsageRecord.ref_id == course_id),
        _ref_in(
            UsageRecord.ref_id,
            session_ids,
            wrap=UsageRecord.ref_type == "session",
        ),
    ]
    # 同上：挂课程与挂课堂是两条**不同**的归属路径，取其一即可
    return list(UsageRecord.query.filter(db.or_(*_present(conditions))).all())


def _ref_in(column: Any, values: Sequence[str], *, wrap: Any | None = None) -> Any | None:
    """`column IN (...)`，但**空列表返回 None**（= 这个条件不成立）。

    不能退化成 `IN ('')`：`job_id` / `ref_id` 这些列的缺省值就是空串，
    于是「这门课还没有生成任务」会匹配到**所有没挂任务的行** ——
    单课明细里冒出别人的账（工作台改课、课堂补页的那些），
    而数字看着完全正常，只是偏大。宁可少一个条件，也不要一个恒真的条件。
    """
    if not values:
        return None
    condition = column.in_(list(values))
    return condition if wrap is None else (wrap & condition)


def _present(conditions: Sequence[Any | None]) -> list[Any]:
    return [item for item in conditions if item is not None]


# --------------------------------------------------------------------------
# 明细行与分组
# --------------------------------------------------------------------------


def _llm_row(call: ModelCall) -> dict[str, Any]:
    return {
        "kind": "llm",
        "at": call.created_at,
        "provider": call.provider,
        "model": call.model,
        "tokens": int(call.tokens or 0),
        "promptTokens": int(call.prompt_tokens or 0),
        "completionTokens": int(call.completion_tokens or 0),
        "units": 0,
        "unitName": "",
        "estCost": round(float(call.est_cost or 0.0), 6),
        "latencyMs": int(call.latency_ms or 0),
        "ok": bool(call.ok),
        "errorCode": call.error_code or "",
        "stepId": call.step_id or "",
        "refType": call.ref_type or "",
        "refId": call.ref_id or "",
    }


def _voice_row(row: UsageRecord) -> dict[str, Any]:
    return {
        "kind": row.kind,
        "at": row.created_at,
        "provider": row.provider,
        "model": "",
        "tokens": 0,
        "promptTokens": 0,
        "completionTokens": 0,
        "units": int(row.units or 0),
        "unitName": row.unit_name or "",
        "estCost": round(float(row.est_cost or 0.0), 6),
        "latencyMs": 0,
        "ok": True,
        "errorCode": "",
        "stepId": "",
        "refType": row.ref_type or "",
        "refId": row.ref_id or "",
    }


def _entry_of_row(row: Mapping[str, Any]) -> Entry:
    return Entry(
        kind=str(row.get("kind") or ""),
        day=days.day_of(str(row.get("at") or "")),
        course_id="",
        tokens=int(row.get("tokens") or 0),
        units=int(row.get("units") or 0),
        cost=float(row.get("estCost") or 0.0),
    )


def _by_kind(entries: Iterable[Entry]) -> list[dict[str, Any]]:
    """四条链路各花了多少，**平的一份**：`{kind, totalTokens, totalUnits, unitName, ...}`。

    看板上的第一行就是它（不管按什么分组，四链路各自花了多少都最该先看到），
    所以形状要能直接渲染：分组那套 `{key, label, kinds: [...]}` 在这里
    多包了一层 —— 而这一层的长度恒为 1，前端每次都要 `kinds[0]` 才能取到数。

    **四条链路一条都不少**（没量的那条给一行 0），顺序固定按 `DAILY_KINDS`
    的声明序：图例的条数不该随这个月的用量变，也不该今天这个在前、明天那个在前。
    与「按天分组」给满 30 天是同一条口径 —— 缺一条与「那条是 0」在图上
    是两件事，而看板上只该有前者是意外。
    """
    totals: dict[str, dict[str, Any]] = {}
    for entry in entries:
        slot = totals.get(entry.kind)
        if slot is None:
            totals[entry.kind] = entry.bucket()
            continue
        # 同一条链路的第二条起：往已有那一格里累加
        slot["totalTokens"] += entry.tokens
        slot["totalUnits"] += entry.units
        slot["estCost"] = round(slot["estCost"] + entry.cost, 6)
        slot["calls"] += entry.calls
    return [
        totals[kind]
        if kind in totals
        else Entry(kind=kind, day="", course_id="", calls=0).bucket()
        for kind in DAILY_KINDS
    ]


def _group(entries: Iterable[Entry], group_by: str) -> list[dict[str, Any]]:
    """条目按 `group_by` 分桶。每个桶里再分链路，桶本身带一份合计。"""
    if group_by == "kind":  # 桶的 key 就是链路，那一层 `kinds` 恒为一个元素
        return _by_kind(entries)

    buckets: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = _key_of(entry, group_by)
        bucket = buckets.setdefault(key, {"key": key, "kinds": {}})
        kinds: dict[str, dict[str, Any]] = bucket["kinds"]
        slot = kinds.get(entry.kind)
        if slot is None:
            kinds[entry.kind] = entry.bucket()
        else:
            # 同一条链路的第二条起：往已有那一格里累加
            slot["totalTokens"] += entry.tokens
            slot["totalUnits"] += entry.units
            slot["estCost"] = round(slot["estCost"] + entry.cost, 6)
            slot["calls"] += entry.calls

    out = [
        {
            "key": key,
            "label": _label_of(key, group_by),
            "kinds": [bucket["kinds"][kind] for kind in DAILY_KINDS if kind in bucket["kinds"]],
            **_sum_of(list(bucket["kinds"].values())),
        }
        for key, bucket in buckets.items()
    ]
    # 天与课：新的在前，与仓库里所有列表同一个口径
    return sorted(out, key=lambda item: str(item["key"]), reverse=True)


def _key_of(entry: Entry, group_by: str) -> str:
    if group_by == "kind":
        return entry.kind
    if group_by == "course":
        return entry.course_id
    return entry.day


def _label_of(key: str, group_by: str) -> str:
    """给人看的名字。课程要显示标题 —— 一串 `c_01H…` 回答不了「哪门课」。

    课程被删了就拿原样显示 id：这条账**确实花过**，不能因为课没了就
    在横轴上消失（账本不随业务数据级联删除，见 `models/telemetry.py`）。
    """
    if group_by != "course":
        return key or "（未知）"
    if not key:
        return "（未归属）"
    course = db.session.get(Course, key)
    return (course.title or course.topic or key) if course is not None else key


def _sum_of(buckets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "totalTokens": sum(int(item.get("totalTokens") or 0) for item in buckets),
        "totalUnits": sum(int(item.get("totalUnits") or 0) for item in buckets),
        "estCost": round(sum(float(item.get("estCost") or 0.0) for item in buckets), 6),
        "calls": sum(int(item.get("calls") or 0) for item in buckets),
    }


def register_cli(app) -> None:
    """注册 `flask usage-refresh`（F5-7：把 `daily_usage` 的缓存重算一遍）。

    与 `exports-cleanup` 同源：仓库里没有常驻调度器，收尾的动作交给外面 ——
    部署方挂一条 cron，或由验收脚本显式调一次。命令只负责让它有个入口。

    **为什么需要它**：过去的日子只算一次（算完就存下来当缓存），而账是可能
    迟到的 —— 后台线程在午夜之后才写完的那一行，落在昨天，而昨天的缓存
    前一天就已经生成好了。不重算的话，那笔钱在看板上永远不出现。
    """
    import click

    @app.cli.command("usage-refresh")
    @click.option("--day", default="", help="只重算这一天（YYYY-MM-DD），缺省算最近几天")
    @click.option("--days-back", default=DEFAULT_REFRESH_DAYS, type=int,
                  help="不带 --day 时重算最近几天（含今天）")
    @click.option("--owner", default="", help="只重算这个归属人，缺省重算所有人")
    def usage_refresh_command(day: str, days_back: int, owner: str) -> None:  # pragma: no cover - CLI
        """重算用量缓存。默认最近两天（今天只算不存，见 `refresh`）。"""
        report = refresh(day=day, days_back=days_back, owner_id=owner or None)
        # 只用中文与 ASCII：Windows 控制台默认 GBK，打符号会直接崩掉命令
        click.echo(f"重算完成：{len(report['days'])} 天（{report['days'][0]} ~ "
                   f"{report['days'][-1]}）x {len(report['owners'])} 人，"
                   f"写入 {report['rows']} 行")
        click.echo("今天只算不存：它随时在变（见 aggregate.refresh 的注释）")


__all__ = [
    "DEFAULT_REFRESH_DAYS",
    "DETAIL_LIMIT",
    "GROUP_BYS",
    "Entry",
    "course_detail",
    "refresh",
    "register_cli",
    "spend",
    "summary",
    "totals",
]
