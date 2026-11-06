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

from app import db  # noqa: E402
from scripts.migrate import migrate  # noqa: E402


def _build(schema: str) -> None:
    with db.connect(TEST_URL) as conn:
        migrate(conn, schema)


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
