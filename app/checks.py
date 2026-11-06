"""Run the data checks. The checks themselves are SQL views in db/checks.sql;
this just runs them all and stores what they found."""

from app import db

# check name -> (title, what it asserts, in plain words). Shown on the Data health page, in this order.
CHECKS = {
    "tieout": ("Tie-out", "Today's filled seats equal yesterday's, plus hires, minus exits."),
    "rollup": ("Roll-up", "Every org adds up to the orgs below it plus the seats it holds itself."),
    "referential": ("Referential", "Every position has a real org, and every active person has a seat."),
    "ratio": ("Ratio", "No VP org's share of company headcount moves more than 3 points in a day."),
    "plan_integrity": ("Plan integrity", "The locked plan still matches the fingerprint taken when it was locked."),
    "open_share": ("Exception volume", "No VP org has more than 8% of its seats open with nobody recruiting."),
}


def run_checks(conn, run_at=None) -> int:
    """Run every check and store the results. Returns the run id. The caller commits."""
    run_id = db.one(conn, "INSERT INTO check_runs (run_at) VALUES (coalesce(%s, now())) RETURNING id", (run_at,))["id"]
    conn.execute("""
        INSERT INTO check_results (check_run_id, check_name, org_id, severity, expected, actual, message)
        SELECT %s, check_name, org_id, severity, expected, actual, message FROM v_check_all""", (run_id,))
    # A check's status is its worst row. Count checks, not rows.
    conn.execute("""
        WITH worst AS (
            SELECT check_name,
                   CASE WHEN bool_or(severity = 'fail') THEN 'fail'
                        WHEN bool_or(severity = 'warn') THEN 'warn' ELSE 'pass' END AS status
            FROM check_results WHERE check_run_id = %(run)s GROUP BY check_name
        )
        UPDATE check_runs
        SET passed = (SELECT count(*) FROM worst WHERE status = 'pass'),
            warned = (SELECT count(*) FROM worst WHERE status = 'warn'),
            failed = (SELECT count(*) FROM worst WHERE status = 'fail')
        WHERE id = %(run)s""", {"run": run_id})
    return run_id
