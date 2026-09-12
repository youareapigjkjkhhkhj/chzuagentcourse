"""串行化写库测试（AGENTS.md §4.2）。

SQLite 单写者：所有写操作必须经 db_write 串行化，避免 database is locked。
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import DeclarativeBase

from app.extensions import db

pytestmark = pytest.mark.unit


class Base(DeclarativeBase):
    """测试专用 declarative base。

    刻意不用 db.Model —— 那会把这个表注册进 app 的 db.metadata，
    让「迁移与模型是否一致」的契约测试误以为线上漏建了一张表。
    """


class Counter(Base):
    """最小自增计数器，用来观察并发写的丢更新。"""

    __tablename__ = "test_counter"

    id = Column(Integer, primary_key=True)
    name = Column(String(32), unique=True, nullable=False)
    value = Column(Integer, nullable=False, default=0)


@pytest.fixture()
def counter(app):
    """把 Counter 建到当前测试库，并返回一个查询入口。"""
    Base.metadata.create_all(db.engine)
    return Counter


def _one(name: str) -> Counter:
    return db.session.query(Counter).filter_by(name=name).one()


def test_db_write_commits(app, counter):
    from app.common.dbw import db_write

    def _create():
        row = Counter(name="a", value=1)
        db.session.add(row)
        db.session.flush()  # 让主键生成，验证确实写进去了
        return row.id

    with app.app_context():
        row_id = db_write(_create)
        assert row_id is not None
        assert _one("a").value == 1


def test_db_write_returns_value(app, counter):
    from app.common.dbw import db_write

    with app.app_context():
        db_write(lambda: db.session.add(Counter(name="b", value=7)))
        assert db_write(lambda: _one("b").value) == 7


def test_db_write_rolls_back_on_error(app, counter):
    """写函数抛异常必须回滚，不能留半截数据。"""
    from app.common.dbw import db_write

    def _boom():
        db.session.add(Counter(name="c", value=1))
        raise ValueError("模拟业务失败")

    with app.app_context():
        with pytest.raises(ValueError):
            db_write(_boom)

        assert db.session.query(Counter).filter_by(name="c").first() is None


def test_db_write_is_serialized_across_threads(app, counter):
    """多线程并发写必须串行化，结果不能丢更新。"""
    from app.common.dbw import db_write

    with app.app_context():
        db_write(lambda: db.session.add(Counter(name="counter", value=0)))

    threads = 8
    per_thread = 10

    def worker():
        # 每个线程自带 app context，各自持有独立 session（真实部署就是这个形状）
        with app.app_context():
            for _ in range(per_thread):

                def _inc():
                    row = _one("counter")
                    row.value = row.value + 1
                    return row.value

                db_write(_inc)

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join(timeout=60)

    with app.app_context():
        assert _one("counter").value == threads * per_thread


def test_db_write_without_app_context_is_rejected(app):
    """脱离应用上下文调用要明确报错，而不是静默失败。"""
    from app.common.dbw import db_write

    outcome: dict = {}

    def worker():
        try:
            db_write(lambda: None)
            outcome["raised"] = False
        except RuntimeError:
            outcome["raised"] = True

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)

    assert outcome.get("raised") is True, "无 app context 时必须抛 RuntimeError"


def test_db_write_nested_call_does_not_deadlock(app, counter):
    """同一线程内嵌套调用不能自锁（用可重入锁）。"""
    from app.common.dbw import db_write

    with app.app_context():

        def _outer():
            db.session.add(Counter(name="n1", value=1))

            def _inner():
                db.session.add(Counter(name="n2", value=2))

            db_write(_inner)

        db_write(_outer)
        assert db.session.query(Counter).count() == 2


def test_in_write_transaction_reflects_nesting(app, counter):
    """嵌套时内层能看到自己处在事务中，供 repository 决定要不要自己提交。"""
    from app.common.dbw import db_write, in_write_transaction

    seen: list[bool] = []

    def _inner():
        seen.append(in_write_transaction())

    def _outer():
        seen.append(in_write_transaction())
        db_write(_inner)

    with app.app_context():
        assert in_write_transaction() is False
        db_write(_outer)
        assert in_write_transaction() is False

    assert seen == [True, True]
