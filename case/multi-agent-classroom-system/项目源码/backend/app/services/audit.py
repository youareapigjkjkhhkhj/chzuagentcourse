"""审计留痕（P5-A14 / §6）。

`audit_logs` 这张表 P1 就在用了（敏感词拦截一条路径，见 `generation/filter.py`）。
P5 把它扩成「关键操作都要有一条」，验收条件是：

    关键操作（创建课程、删除课程、修改 Provider、导出）均有一条 `audit_logs`
    记录，含操作者与 IP。

三件事值得先说清楚：

1. **为什么单独一个模块**。P1 那条路径是自己拼 `AuditLog(...)` 的，因为那时只有
   一个调用点。P5 一下多了四处，四处各拼一遍的结果是「IP 有的写有的忘」——
   而漏掉的那一处不会报错，只会在真要查的时候才被发现少了一列。
2. **IP 取谁的**。默认取 `request.remote_addr`（TCP 对端），**不认** `X-Forwarded-For`：
   那个头是客户端可以自己填的，无条件采信等于让审计里的 IP 变成「操作者说他从哪来」。
   只有确实跑在反向代理后面时（compose 的 nginx 档 / 生产入口），部署方开
   `AUDIT_TRUST_PROXY=true`，才按 XFF 的第一段取真实客户端。
3. **写不进去不阻断业务**。审计是旁路：一次写库冲突不该让「删课」这种用户
   明确要做的事失败。失败留 error 日志 —— 审计缺了是运维要能看见的事，
   而不是让用户看见的事（同 `generation/filter.py` 的口径）。
"""

from __future__ import annotations

from typing import Any, Mapping

from flask import has_request_context, request

from app.common.dbw import db_write
from app.common.identity import current_owner_id
from app.common.logging import get_logger
from app.extensions import db
from app.models import AuditLog

logger = get_logger("app.audit")

#: 动作名。点号分段：`域.动作`。**只增不改** —— 已写下的行靠它查，
#: 改一次就会让历史记录与新记录分成两拨，且那一批永远补不回来。
ACTION_COURSE_CREATE = "course.create"
ACTION_COURSE_DELETE = "course.delete"
ACTION_PROVIDER_UPDATE = "provider.update"
ACTION_PROVIDER_ENABLE = "provider.enable"
ACTION_EXPORT_CREATE = "export.create"
#: 带着正确访问码走进来（P5-A13）。失败的尝试**不写库**：那是一个能被反复
#: 触发的动作，写到库里就成了写放大，拒绝侧只记日志。
ACTION_ACCESS_GRANT = "access.grant"

#: `target` 列宽 64。超长的 id 截断而不是报错：审计记的是「动过什么」，
#: 截断的 id 仍然能定位到人，而一次写失败会丢掉整条记录。
_TARGET_MAX = 64
_UA_MAX = 255
_IP_MAX = 64


def _client_ip() -> str:
    """操作者 IP。见模块 docstring 第 2 条：代理头只在明确配置时才认。"""
    if not has_request_context():
        return ""
    from flask import current_app

    if current_app.config.get("AUDIT_TRUST_PROXY"):
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded:
            return forwarded[:_IP_MAX]
    return (request.remote_addr or "")[:_IP_MAX]


def _user_agent() -> str:
    if not has_request_context():
        return ""
    # 不直接取 request.headers['User-Agent']：走 request.user_agent 拿到的
    # 已经去过非法字符，而这一列是要进库的
    return (request.user_agent.string or "")[:_UA_MAX]


def record(
    action: str,
    *,
    target: str = "",
    owner_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    """记一条审计。

    `target` 形如 `course:c_01H…`（见 `models/telemetry.py` 的列注释）。
    `detail` 只放**判定依据**这类要能复核的东西（动作、结果、数量）——
    AGENTS §19：提示词原文与材料正文不入库，审计也不例外。
    """
    ip = _client_ip()
    ua = _user_agent()
    owner = current_owner_id() if owner_id is None else owner_id
    payload = dict(detail or {})

    def _write() -> None:
        row = AuditLog(
            action=action,
            target=(target or "")[:_TARGET_MAX],
            owner_id=owner or None,
            ip=ip,
            ua=ua,
        )
        row.detail = payload  # JSONField 描述符，写的是 detail_json 列
        db.session.add(row)

    try:
        db_write(_write)
    except Exception as exc:  # 审计失败只能记日志，不能抛回调用方
        logger.error("写入 audit_logs 失败（action=%s target=%s）：%s", action, target, type(exc).__name__)
    else:
        logger.info("审计 action=%s target=%s owner=%s", action, target or "-", owner or "-")


def list_recent(limit: int = 50, action: str = "") -> list[dict]:
    """最近的审计记录（新的在前）。给运维排查用，不对外开接口。"""
    query = AuditLog.query
    if action:
        query = query.filter(AuditLog.action == action)
    rows = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(max(1, limit)).all()
    return [row.to_dict() for row in rows]


__all__ = [
    "ACTION_ACCESS_GRANT",
    "ACTION_COURSE_CREATE",
    "ACTION_COURSE_DELETE",
    "ACTION_EXPORT_CREATE",
    "ACTION_PROVIDER_ENABLE",
    "ACTION_PROVIDER_UPDATE",
    "list_recent",
    "record",
]
