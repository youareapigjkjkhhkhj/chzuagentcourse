"""请求归属人（P1-F3 越权 404 / 技术方案 §1021）。

P0~P4 是**单机本地会话**：没有登录，默认归属本机种子里的那位老师。
但「谁的资源」这件事从第一天就要有唯一出处 —— 否则每个接口各写一遍
`if course.owner_id == ...`，迟早有一个接口忘了写，而漏掉的那一个就是越权入口。

`X-Owner-Id` 头是留给多用户联调与越权用例的缝：
**它不是鉴权**（能改请求头就能冒充），单机场景下没有可冒充的对象；
P4 接入真正的会话后，换掉 `current_owner_id` 一个函数即可，调用方不用动。

越权的语义是 **404 而不是 403**（AGENTS §4.1）：403 等于承认「这个 id 存在，
只是不给你看」，用错误码的差别就能扫出别人有哪些课程。
"""

from __future__ import annotations

import re

from flask import has_request_context, request

#: 归属人透传头。值只允许字母数字与 - _ （id 的形状），别的一律当没给。
OWNER_HEADER = "X-Owner-Id"

_SAFE_OWNER = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def current_owner_id() -> str:
    """当前请求的归属人 id。取不到时返回空串，调用方按「不看归属」处理。"""
    if has_request_context():
        header = (request.headers.get(OWNER_HEADER) or "").strip()
        if _SAFE_OWNER.match(header):
            return header
    return local_owner_id()


def local_owner_id() -> str:
    """本机默认归属人：第一个建出来的用户（种子数据里的老师）。

    查不到（还没跑种子）就返回空串 —— 此时资源没有归属可言，
    接口按「都能看」处理，而不是把所有人挡在门外。
    """
    from app.models import User

    row = User.query.order_by(User.created_at, User.id).first()
    return str(row.id) if row is not None else ""


def owned_by(row, owner_id: str) -> bool:
    """一行资源是否属于 `owner_id`。

    两边的空值都算通过：
    - 请求侧空 = 还没跑种子，没有归属概念
    - 资源侧空 = 库里早于归属约定建出来的数据（P0 的示例课就是）
    只在**双方都有归属且不相同**时判越权 —— 这条规则反过来说也成立：
    真正的隔离要等 P4 有登录，现在多拦一道只会拦掉合法访问。
    """
    row_owner = getattr(row, "owner_id", None) or ""
    if not owner_id or not row_owner:
        return True
    return str(row_owner) == str(owner_id)


__all__ = ["OWNER_HEADER", "current_owner_id", "local_owner_id", "owned_by"]
