import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from config import config


@contextmanager
def get_db_connection():
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_cursor(cursor_factory=RealDictCursor):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
