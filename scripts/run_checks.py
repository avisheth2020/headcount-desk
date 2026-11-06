"""Run the data checks and print a summary.

    uv run python -m scripts.run_checks            # dev database from .env
    uv run python -m scripts.run_checks --prod     # production database from .env
"""

import argparse
import os

from app import db
from app.checks import CHECKS, run_checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true", help="use PROD_DATABASE_URL")
    args = parser.parse_args()
    url = os.environ["PROD_DATABASE_URL"] if args.prod else db.database_url()
    with db.connect(url) as conn:
        run_id = run_checks(conn)
        run = db.one(conn, "SELECT * FROM check_runs WHERE id = %s", (run_id,))
        problems = db.query(conn, "SELECT check_name, severity, message FROM check_results "
                                  "WHERE check_run_id = %s AND severity <> 'pass' ORDER BY id", (run_id,))
    print(f"Run {run_id}: {run['passed']} of {len(CHECKS)} checks passed, {run['warned']} warned, {run['failed']} failed.")
    for p in problems:
        print(f"  [{p['severity']}] {CHECKS[p['check_name']][0]}: {p['message']}")


if __name__ == "__main__":
    main()
