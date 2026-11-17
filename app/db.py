"""Database connection for the Cinderhaven Data Platform (Postgres).

Fork-safe connection pool: each PID gets its own ThreadedConnectionPool so
gunicorn pre-fork workers don't share sockets. All callers use the
``get_conn()`` context manager which guarantees connections are returned.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extensions
import psycopg2.pool

# ============================================================
# Decimal -> float typecast (registered per-pool creation)
# ============================================================

DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values,
    'DEC2FLOAT',
    lambda value, curs: float(value) if value is not None else None,
)


def _register_dec2float() -> None:
    """Register the DEC2FLOAT typecast globally for the current process."""
    psycopg2.extensions.register_type(DEC2FLOAT)


# ============================================================
# PID-aware pool management
# ============================================================

_pools: dict[int, psycopg2.pool.ThreadedConnectionPool] = {}


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Copy .env.example to .env and configure."
        )
    return url


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Return a ThreadedConnectionPool for the current PID, creating one if needed."""
    pid = os.getpid()
    pool = _pools.get(pid)
    if pool is None:
        _register_dec2float()
        pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=get_database_url(),
            # retail_velocity_decision_tool first: this repo's own schema holds
            # stg_category_benchmarks (U19a); the platform's marts follow.
            options=("-c search_path=retail_velocity_decision_tool,public_marts,public_staging,raw,public "
                     "-c statement_timeout=30000"),
            connect_timeout=5,
        )
        _pools[pid] = pool
    return pool


@contextmanager
def get_conn():
    """Context manager that checks out a connection and returns it on exit.

    Usage::

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    """
    pool = get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        yield conn
    finally:
        pool.putconn(conn)


