"""生成内容的合规检查（P1-F2 / AGENTS §4.1「内容合规」）。

P1 只要一条最简的路径：生成内容过词表，命中就**整段重生成一次**，并把
「命中了什么、怎么处理的」记进 `audit_logs`。真正的多引擎内容安全是 P5 的事，
但这条路径的地基现在就打好 —— 词表可换、处理动作可换，审计留痕的约定不变。

三条刻意的取舍：

1. **词表只收「可执行的危害」，不收题材词**。历史课的「战争」「屠杀」、
   生物课的「生殖」，都是正经教学内容；漏杀几个词，比把一门课判成违规便宜得多。
   写进敏感词表的是「怎么造一个炸弹」这类**做法**，不是「炸弹」这个词。
2. **扫描的是最终 DSL 的全部字符串**，不是某几个字段。字段白名单会和
   `PageDraft` 一起漂移：今天加了 `hintScript` 忘了加进白名单，明天那页
   就成了检查不到的暗门。
3. **审计只记命中的词，不记命中的那句话**。词是判定依据（要能复核），
   整句是生成内容（AGENTS §19：不入库、不入日志）。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from flask import current_app

from app.common.dbw import db_write
from app.common.logging import get_logger
from app.extensions import db
from app.models import AuditLog

logger = get_logger("app.generation.filter")

#: P1 的简易词表。放的是「做法」而不是「题材」—— 见模块 docstring 第 1 条。
#: 部署方可以用 SENSITIVE_WORDS 追加自己的词（逗号分隔），追加项与这份是并集。
DEFAULT_SENSITIVE_WORDS: tuple[str, ...] = (
    "制作炸弹",
    "制造炸弹",
    "造炸弹",
    "爆炸物配方",
    "制作枪支",
    "买枪渠道",
    "毒品配方",
    "制毒",
    "吸毒方法",
    "赌博网站",
    "博彩开户",
    "诈骗话术",
    "洗钱流程",
    "色情服务",
    "招嫖",
    "自杀方法",
    "自残教程",
    "血腥虐杀",
)

#: 审计动作名。P5 的成本/合规看板按它分组，所以是一处常量。
ACTION_SENSITIVE = "sensitive_hit"

#: 命中的处理结果。三者要能区分开：拦下来了 / 重生成后干净了 / 重生成后还是不干净。
OUTCOME_REGENERATED = "regenerated"
OUTCOME_BLOCKED = "blocked"


def sensitive_words() -> tuple[str, ...]:
    """当前生效的词表：内置的 + 配置追加的。"""
    extra = str(current_app.config.get("SENSITIVE_WORDS") or "")
    appended = [word.strip() for word in extra.split(",") if word.strip()]
    return tuple(dict.fromkeys((*DEFAULT_SENSITIVE_WORDS, *appended)))


def scan(text: Any) -> list[str]:
    """一段文本命中了哪些词（按首次出现的位置排序，便于人看）。"""
    body = str(text or "")
    if not body:
        return []
    hits = [(body.find(word), word) for word in sensitive_words()]
    return [word for index, word in sorted(hits) if index >= 0]


def scan_page(page: Mapping[str, Any]) -> list[str]:
    """一页里命中的全部词。

    扫描范围是 DSL 里**所有**字符串（含嵌套的 quiz / code / sides），
    理由见模块 docstring 第 2 条。
    """
    hits: list[str] = []
    for text in _strings(page):
        hits.extend(scan(text))
    return list(dict.fromkeys(hits))


def record_hit(
    *,
    target: str,
    owner_id: str = "",
    words: Sequence[str],
    outcome: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """记一条审计。

    审计写不进去**不阻断生成**：内容合规的判定已经做完了，因为一次写库冲突
    把它整页丢掉，比少一条审计更糟。但一定要留 error 级日志 —— 合规记录
    缺了是 P5 对账时要能看见的事。
    """
    detail = {"words": list(words), "outcome": outcome}
    if extra:
        detail.update(extra)

    def _write() -> None:
        row = AuditLog(action=ACTION_SENSITIVE, target=target[:64], owner_id=owner_id or None)
        row.detail = detail  # JSONField 描述符，写的是 detail_json 列
        db.session.add(row)

    try:
        db_write(_write)
    except Exception as exc:  # 审计失败只能记日志，不能抛回管线
        logger.error("写入 audit_logs 失败（target=%s）：%s", target, type(exc).__name__)
    else:
        logger.warning("内容合规命中：target=%s words=%s outcome=%s", target, list(words), outcome)


def _strings(value: Any) -> Iterable[str]:
    """递归取出结构里所有的字符串。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for item in value:
            yield from _strings(item)


__all__ = [
    "ACTION_SENSITIVE",
    "DEFAULT_SENSITIVE_WORDS",
    "OUTCOME_BLOCKED",
    "OUTCOME_REGENERATED",
    "record_hit",
    "scan",
    "scan_page",
    "sensitive_words",
]
