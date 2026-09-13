"""模型基类与公共列类型。

约定：
- 主键统一 String(32)：种子数据用可读 slug，运行时用 uuid4().hex
- 每张表都有 created_at / updated_at（UTC ISO8601 字符串）
- JSON 字段统一命名 *_json，Python 侧通过描述符读写 dict/list
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.common.timeutil import utcnow_iso
from app.extensions import db


def new_id() -> str:
    """运行时主键：32 位十六进制，不可猜（避免用自增 id 探测资源）。"""
    return uuid.uuid4().hex


class TimestampMixin:
    """created_at / updated_at，均为 UTC ISO8601 字符串。"""

    created_at = db.Column(db.String(32), nullable=False, default=utcnow_iso)
    updated_at = db.Column(
        db.String(32), nullable=False, default=utcnow_iso, onupdate=utcnow_iso
    )


class JSONField:
    """把 TEXT 列包装成 JSON 属性。

    容错优先：库里被手工改坏的 JSON 只让该字段退化成 None，
    不能让整个接口 500（学习工具没必要为一条脏数据全站不可用）。
    """

    def __init__(self, column_name: str) -> None:
        self.column_name = column_name

    def __set_name__(self, owner, name: str) -> None:
        self.name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        raw = getattr(obj, self.column_name, None)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def __set__(self, obj, value: Any) -> None:
        if value is None:
            setattr(obj, self.column_name, None)
        else:
            setattr(obj, self.column_name, json.dumps(value, ensure_ascii=False))


class PkMixin:
    """字符串主键。显式传入（种子 slug）时保留，否则自动生成。"""

    id = db.Column(db.String(32), primary_key=True, default=new_id)


def enum_check(column: str, values: tuple[str, ...], name: str) -> db.CheckConstraint:
    """`<column> IN (...)` 那种 CHECK。

    枚举值全部来自各模型模块的常量元组 —— 调用方一个字符串都不该现写。
    SQLite 改不动 CHECK 约束，所以每加一个值都要配一条迁移（各模块的常量
    元组上都有这句话）。
    """
    joined = ", ".join(f"'{value}'" for value in values)
    return db.CheckConstraint(f"{column} IN ({joined})", name=name)


__all__ = ["JSONField", "PkMixin", "TimestampMixin", "enum_check", "new_id"]
