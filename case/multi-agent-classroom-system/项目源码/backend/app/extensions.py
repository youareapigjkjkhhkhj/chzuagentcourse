"""Flask 扩展单例。

集中在一处初始化，避免循环 import（create_app 负责 init_app）。
"""

from __future__ import annotations

import sqlite3

from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine

# 统一约束命名：Alembic 在 SQLite 上要用 batch mode 重建表，
# 匿名约束会导致 autogenerate 反复产生无意义的 diff。
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate()
cors = CORS()


@event.listens_for(Engine, "connect")
def _install_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """为每个 SQLite 连接装上 PRAGMA。

    注册在模块顶层：本模块在 create_app 里被 import，必然早于任何引擎创建，
    因此不需要额外的「只装一次」守卫。isinstance 判断保证不碰其它数据库。

    WAL：读写不互相阻塞（课堂演示时一边落库一边读列表）。
    busy_timeout：写锁竞争时不立刻抛 database is locked。
    foreign_keys：SQLite 默认不校验外键，必须显式打开。
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
    finally:
        cursor.close()
