"""这堂课里有谁：主讲老师与 AI 同学（P3 §2.3 / F3-12）。

**为什么单独一个模块**：两个地方问的是同一个问题 —— 讨论里的**发言人**
（`runtime._pick_classmate`）与面板上的**在线名单**（`recorder.presence`）——
而它们分属两个模块。各查各的话，讨论里冒出第 4 位同学、名单上还只有 3 个，
「看见的」和「听到的」就不是一回事了。

**同学的数量取设置里的 `classmateCount`**（设置页「AI 同学数量」）。这与讨论
激烈程度（`runtime._intensity`）同一个口径：读的是**当前设置**而不是生成课程
时那份快照 —— 一堂已经生成的课，老师把同学从 3 位调到 4 位，下一次讨论就该
是 4 个人在说话。生成时用不用得上这个数（P1 的提示词目前不看它）与这里无关：
这里管的是课堂上有几个人开口。

**人数与角色库不一致时：宁可少，不可假。** 库里只有 3 位而设置是 5 位，就按
3 位来。凭空造出两张没有名字、没有音色的嘴，比少两个人难查得多。
"""

from __future__ import annotations

from typing import Any

from app.common.logging import get_logger
from app.models import AgentRole

logger = get_logger("app.classroom.roster")

#: 设置里「AI 同学数量」的键（`settings_service` 的生成参数）。
CLASSMATE_COUNT_KEY = "classmateCount"

#: 没有种子角色时的兜底老师（离线测试与「还没跑种子」的库里就是这样）。
DEFAULT_TEACHER: dict[str, Any] = {
    "code": "teacher",
    "name": "老师",
    "role": "teacher",
    "persona": {},
}


def _roles(role: str) -> list[dict[str, Any]]:
    """某一种角色，按 `sort_order` 排 —— 顺序就是「谁先开口」。"""
    rows = (
        AgentRole.query.filter_by(role=role)
        .order_by(AgentRole.sort_order, AgentRole.id)
        .all()
    )
    return [row.to_dict() for row in rows]


def teacher() -> dict[str, Any]:
    """主讲老师。角色库空着时给一个没有名字的兜底 —— 课还得上。"""
    people = _roles("teacher")
    return people[0] if people else dict(DEFAULT_TEACHER)


def classmates() -> list[dict[str, Any]]:
    """这堂课的同学：角色库里的前 N 位（N = 设置里的 AI 同学数量）。"""
    people = _roles("student")
    count = classmate_count()
    if count is None:
        return people
    return people[:count]


def classmate_count() -> int | None:
    """设置里的 AI 同学数量。**读不出来返回 `None`（= 全员上），不返回 0。**

    读不出来就让课堂上一个人都不说话，比多两个人难解释得多 —— 前者看起来
    像坏了，后者只是多两张嘴。
    """
    from app.services import settings_service

    try:
        raw = settings_service.get_generation().get(CLASSMATE_COUNT_KEY)
        if raw is None:
            return None
        return max(0, int(raw))
    except Exception:  # 设置读不出来不该让讨论开不起来
        logger.debug("课堂：读不到 AI 同学数量，按角色库全员上")
        return None


def presence_members() -> list[dict[str, Any]]:
    """在线名单里的 AI 同学（F3-12）。

    **不计入 `presence.online`** —— 那个数是「几个人真的连进来了」，AI 同学
    一直在（它们不是连接，是角色）。混在一起数，老师看见的在线人数就没法
    用来判断「学生到齐没有」了。
    """
    return [
        {
            "code": person["code"],
            "name": person["name"],
            "color": person.get("avatarColor") or "",
            "role": person.get("role") or "student",
        }
        for person in classmates()
    ]


__all__ = [
    "CLASSMATE_COUNT_KEY",
    "DEFAULT_TEACHER",
    "classmate_count",
    "classmates",
    "presence_members",
    "teacher",
]
