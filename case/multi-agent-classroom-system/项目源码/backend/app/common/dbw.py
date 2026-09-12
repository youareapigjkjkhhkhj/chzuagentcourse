"""串行化写库（AGENTS.md §4.2）。

SQLite 是单写者：多个请求同时写会撞 `database is locked`。
所有写操作一律经 db_write 串行化 + 统一提交/回滚。

嵌套调用：内层不提交，把提交推迟到最外层，保证整体原子性。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from flask import has_app_context

from app.common.logging import get_logger
from app.extensions import db

T = TypeVar("T")

_logger = get_logger("app.dbw")

# 可重入锁：同一线程内嵌套调用不会自锁
_write_lock = threading.RLock()
_state = threading.local()


def _depth() -> int:
    return getattr(_state, "depth", 0)


def _set_depth(value: int) -> None:
    _state.depth = value


def db_write(fn: Callable[[], T]) -> T:
    """在串行化的写事务中执行 fn，成功提交、失败回滚，并返回 fn 的结果。"""
    if not has_app_context():
        raise RuntimeError("db_write 必须在应用上下文中调用（缺少 app.app_context()）")

    with _write_lock:
        depth = _depth()
        _set_depth(depth + 1)
        try:
            result = fn()
        except BaseException:
            _set_depth(depth)
            if depth == 0:
                # 最外层负责回滚，内层交给外层
                try:
                    db.session.rollback()
                except Exception:  # pragma: no cover - 回滚失败只能记日志
                    _logger.exception("回滚失败")
            raise
        else:
            _set_depth(depth)
            if depth == 0:
                try:
                    db.session.commit()
                except BaseException:
                    db.session.rollback()
                    raise
            return result


def db_read(fn: Callable[[], T]) -> T:
    """读操作不需要串行化，但提供统一入口，便于将来换连接池策略。"""
    return fn()


def in_write_transaction() -> bool:
    """当前线程是否正处在 db_write 事务内（供 repository 判断是否需要自己提交）。"""
    return _depth() > 0


__all__ = ["db_read", "db_write", "in_write_transaction"]
