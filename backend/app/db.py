"""Owner-role connection for the app schema (logs, learners). Never used for learner SQL."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings

_pool = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(settings.admin_dsn, min_size=1, max_size=6, open=True,
                               kwargs={"row_factory": dict_row, "prepare_threshold": None})
    return _pool


@contextmanager
def tx():
    with pool().connection() as conn:
        with conn.transaction():
            yield conn


def q(sql, params=None):
    with tx() as c:
        return c.execute(sql, params or ()).fetchall()


def q1(sql, params=None):
    rows = q(sql, params)
    return rows[0] if rows else None


def ex(sql, params=None):
    with tx() as c:
        c.execute(sql, params or ())


J = Jsonb
