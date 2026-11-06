"""Apply the schema and views.

    uv run python -m scripts.migrate            # dev database from .env
    uv run python -m scripts.migrate --prod     # production database from .env

The schema is small and all data is synthetic, so a migration is a rebuild:
drop everything, then apply schema.sql, views.sql and checks.sql in order.
Run scripts.seed afterwards to load data.
"""

import argparse
import os
from pathlib import Path

from app import db

DB_DIR = Path(__file__).resolve().parent.parent / "db"
SQL_FILES = ["schema.sql", "views.sql", "checks.sql"]


def migrate(conn, schema: str = "public") -> None:
    """Rebuild `schema` from the SQL files. The caller commits."""
    conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    conn.execute(f'CREATE SCHEMA "{schema}"')
    conn.execute(f'SET search_path TO "{schema}"')
    for name in SQL_FILES:
        path = DB_DIR / name
        if path.exists():
            conn.execute(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true", help="use PROD_DATABASE_URL")
    args = parser.parse_args()
    url = os.environ["PROD_DATABASE_URL"] if args.prod else db.database_url()
    with db.connect(url) as conn:
        migrate(conn)
        tables = db.one(conn, "SELECT count(*) AS n FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
        views = db.one(conn, "SELECT count(*) AS n FROM information_schema.views WHERE table_schema = 'public'")
    print(f"Migrated {'production' if args.prod else 'dev'}: {tables['n']} tables, {views['n']} views.")


if __name__ == "__main__":
    main()
