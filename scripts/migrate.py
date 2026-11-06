"""Bring the database schema up to date.

    uv run python -m scripts.migrate            # dev database from .env
    uv run python -m scripts.migrate --prod     # production database from .env
    uv run python -m scripts.migrate --reset    # drop everything and rebuild (dev only by habit)

Two kinds of SQL, handled differently:

- db/migrations/NNN_*.sql change tables. Each runs once, in order, and is
  recorded in the schema_migrations table.
- db/views/*.sql are views. They hold no data, so they are dropped and rebuilt
  on every run. That keeps each rule readable in one file.

Run scripts.seed afterwards to load data.
"""

import argparse
import os
from pathlib import Path

from app import db

DB_DIR = Path(__file__).resolve().parent.parent / "db"


def migrate(conn, schema: str = "public", reset: bool = False) -> list[str]:
    """Apply pending migrations and rebuild the views. Returns the versions applied. The caller commits."""
    if reset:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    conn.execute(f'SET search_path TO "{schema}"')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     text PRIMARY KEY,
            applied_at  timestamptz NOT NULL DEFAULT now()
        )""")
    applied = {r["version"] for r in db.query(conn, "SELECT version FROM schema_migrations")}
    # A database built before migrations were numbered already has the baseline.
    if not applied and db.one(conn, "SELECT to_regclass('orgs') IS NOT NULL AS yes")["yes"]:
        conn.execute("INSERT INTO schema_migrations (version) VALUES ('001_baseline')")
        applied.add("001_baseline")

    # Views depend on tables, so drop them before changing tables and rebuild after.
    for view in db.query(conn, "SELECT table_name FROM information_schema.views WHERE table_schema = current_schema()"):
        conn.execute(f'DROP VIEW IF EXISTS "{view["table_name"]}" CASCADE')

    ran = []
    for path in sorted((DB_DIR / "migrations").glob("*.sql")):
        if path.stem not in applied:
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            ran.append(path.stem)
    for path in sorted((DB_DIR / "views").glob("*.sql")):
        conn.execute(path.read_text())
    return ran


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true", help="use PROD_DATABASE_URL")
    parser.add_argument("--reset", action="store_true", help="drop everything first")
    args = parser.parse_args()
    url = os.environ["PROD_DATABASE_URL"] if args.prod else db.database_url()
    with db.connect(url) as conn:
        ran = migrate(conn, reset=args.reset)
        versions = db.one(conn, "SELECT count(*) AS n FROM schema_migrations")["n"]
        views = db.one(conn, "SELECT count(*) AS n FROM information_schema.views WHERE table_schema = 'public'")["n"]
    target = "production" if args.prod else "dev"
    print(f"Migrated {target}: applied {', '.join(ran) or 'nothing new'}; {versions} migrations on record, {views} views rebuilt.")


if __name__ == "__main__":
    main()
