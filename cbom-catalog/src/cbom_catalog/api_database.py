from __future__ import annotations

import os
from contextlib import AbstractContextManager
from threading import Lock
from typing import Any

from psycopg import Connection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool[Any] | None = None
_pool_lock = Lock()


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    if os.environ.get("PGHOST"):
        user = os.environ.get("PGUSER", "cbom")
        password = os.environ.get("PGPASSWORD", "")
        host = os.environ["PGHOST"]
        port = os.environ.get("PGPORT", "5432")
        database = os.environ.get("PGDATABASE", "cbom_catalog")
        return make_conninfo(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
        )
    raise ValueError("DATABASE_URL or PostgreSQL PG* environment variables are required")


def _configure(connection: Connection[Any]) -> None:
    """Configure short-lived API queries without changing ingest/database defaults."""
    statement_timeout_ms = max(
        1_000,
        min(int(os.environ.get("CBOM_API_STATEMENT_TIMEOUT_MS", "20000")), 120_000),
    )
    connection.execute("SET jit = off")
    connection.execute(
        "SELECT set_config('statement_timeout', %s, false)",
        (f"{statement_timeout_ms}ms",),
    )
    connection.commit()


def pool() -> ConnectionPool[Any]:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            minimum = max(1, min(int(os.environ.get("CBOM_API_POOL_MIN_SIZE", "1")), 16))
            maximum = max(
                minimum,
                min(int(os.environ.get("CBOM_API_POOL_MAX_SIZE", "8")), 64),
            )
            _pool = ConnectionPool(
                conninfo=_database_url(),
                min_size=minimum,
                max_size=maximum,
                timeout=float(os.environ.get("CBOM_API_POOL_TIMEOUT_SECONDS", "5")),
                kwargs={"row_factory": dict_row},
                configure=_configure,
                open=True,
                name="cbom-api",
            )
    return _pool


def connection() -> AbstractContextManager[Connection[Any]]:
    return pool().connection()


def close_pool() -> None:
    global _pool
    with _pool_lock:
        current = _pool
        _pool = None
    if current is not None:
        current.close()
