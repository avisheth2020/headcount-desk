"""Test setup.

Every test run builds its own throwaway Postgres schema, so tests never touch
the data the app is using. Locally that schema lives on the dev database from
.env; in CI it lives on a Postgres service container (TEST_DATABASE_URL).
"""

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

TEST_URL = os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
RUN_ID = uuid.uuid4().hex[:8]
SEEDED_SCHEMA = f"test_{RUN_ID}_seeded"
EMPTY_SCHEMA = f"test_{RUN_ID}_empty"

# The app's connection pool reads these, so page tests hit the seeded test schema.
os.environ["DATABASE_URL"] = TEST_URL
os.environ["DB_SCHEMA"] = SEEDED_SCHEMA
os.environ["RATE_LIMIT_WRITES"] = "100000"      # the suite writes far faster than a person would

from app import db  # noqa: E402
from scripts.migrate import migrate  # noqa: E402


def _build(schema: str) -> None:
    with db.connect(TEST_URL) as conn:
        migrate(conn, schema, reset=True)


def _drop(schema: str) -> None:
    with db.connect(TEST_URL) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture(scope="session")
def empty_schema():
    """A migrated schema with no rows, for hand-built fixtures."""
    _build(EMPTY_SCHEMA)
    yield EMPTY_SCHEMA
    _drop(EMPTY_SCHEMA)


@pytest.fixture()
def empty_db(empty_schema):
    """A connection to the empty schema. Everything a test does is rolled back."""
    conn = db.connect(TEST_URL, schema=empty_schema)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture(scope="session")
def manifest():
    """Build the full synthetic dataset once per run. Returns what was planted."""
    from scripts.seed import seed
    with db.connect(TEST_URL) as conn:
        migrate(conn, SEEDED_SCHEMA, reset=True)
        planted = seed(conn)
    yield planted
    if db._pool is not None:
        db._pool.close()
    _drop(SEEDED_SCHEMA)


@pytest.fixture()
def seeded_db(manifest):
    """A connection to the seeded schema. Everything a test does is rolled back."""
    conn = db.connect(TEST_URL, schema=SEEDED_SCHEMA)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


from fastapi.testclient import TestClient  # noqa: E402


class Client(TestClient):
    """A test client that behaves like a browser: it sends the CSRF token back on every write."""

    def post(self, url, **kwargs):
        if "csrf" not in self.cookies:
            self.get("/healthz")
        headers = {"X-CSRF-Token": self.cookies["csrf"], **(kwargs.pop("headers", None) or {})}
        return super().post(url, headers=headers, **kwargs)
