"""History for trend lines, from the daily snapshots."""

from app import db


def seat_history(conn, org_id: int) -> list[dict]:
    """One row per snapshot day for an org, oldest first. Approved headcount comes
    from whichever plan version was in force that day, so a re-plan shows as a
    real step in usable open rather than being painted over the whole history."""
    return db.query(conn, """
        SELECT s.snapshot_date AS day, s.filled + s.negative AS in_seats, s.open_no_req, s.open_with_req AS committed,
               a.approved - s.filled - s.open_with_req - s.reserve - s.negative AS usable_open
        FROM daily_snapshots s
        CROSS JOIN LATERAL (
            SELECT coalesce(sum(pl.approved_headcount), 0)::int AS approved
            FROM plan_lines pl JOIN v_org_closure c ON c.org_id = pl.org_id
            WHERE c.ancestor_id = s.org_id AND pl.plan_version_id = (
                SELECT pv.id FROM plan_versions pv
                WHERE pv.locked_at IS NOT NULL AND coalesce(pv.effective_from, pv.locked_at::date) <= s.snapshot_date
                ORDER BY pv.locked_at DESC LIMIT 1)
        ) a
        WHERE s.org_id = %s ORDER BY s.snapshot_date""", (org_id,))
