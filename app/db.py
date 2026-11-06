"""Database access. One small pool, plain SQL, rows come back as dicts."""

import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

_pool: ConnectionPool | None = None


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return url


def direct_url(url: str) -> str:
    """Neon gives a pooled host (xxx-pooler.region...). Scripts and tests that
    set session options need the direct host, which is the same name without
    the -pooler suffix."""
    return url.replace("-pooler.", ".", 1)


def connect(url: str | None = None, schema: str | None = None) -> psycopg.Connection:
    """A single connection, for scripts and tests. `schema` puts every
    unqualified table name in that schema (used to isolate test runs)."""
    kwargs = {"row_factory": dict_row}
    if schema:
        kwargs["options"] = f"-c search_path={schema}"
    return psycopg.connect(direct_url(url or database_url()), **kwargs)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        schema = os.environ.get("DB_SCHEMA")  # set only by the test suite
        url = database_url()
        kwargs = {"row_factory": dict_row, "prepare_threshold": None}  # pooler-safe
        if schema:
            url = direct_url(url)
            kwargs["options"] = f"-c search_path={schema}"
        _pool = ConnectionPool(url, min_size=1, max_size=4, kwargs=kwargs, open=True)
    return _pool


@contextmanager
def get_conn():
    """One connection from the pool. Commits on success, rolls back on error."""
    with pool().connection() as conn:
        yield conn


def query(conn, sql: str, params=None) -> list[dict]:
    return conn.execute(sql, params).fetchall()


def one(conn, sql: str, params=None) -> dict | None:
    return conn.execute(sql, params).fetchone()
