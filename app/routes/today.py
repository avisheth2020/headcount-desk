"""Today: each role's home page. It answers "what needs me?"."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import db, web
from app.checks import CHECKS

router = APIRouter()


def latest_check(conn) -> dict:
    run = db.one(conn, "SELECT * FROM check_runs ORDER BY run_at DESC, id DESC LIMIT 1")
    run["findings"] = db.query(conn, """
        SELECT r.check_name, r.severity, r.message, r.org_id FROM check_results r
        WHERE r.check_run_id = %s AND r.severity <> 'pass' ORDER BY r.id""", (run["id"],))
    for f in run["findings"]:
        f["title"] = CHECKS[f["check_name"]][0]
    run["total"] = len(CHECKS)
    return run


def since_yesterday(conn, org_id: int) -> dict:
    """What moved between the last two snapshots for an org, plus the day's workflow activity."""
    snap = db.one(conn, """
        SELECT cur.filled - prev.filled AS filled, cur.open_with_req - prev.open_with_req AS committed,
               cur.open_no_req - prev.open_no_req AS open_no_req, d.today_date, d.prev_date
        FROM v_snapshot_days d
        JOIN daily_snapshots cur ON cur.snapshot_date = d.today_date AND cur.org_id = %(org)s
        JOIN daily_snapshots prev ON prev.snapshot_date = d.prev_date AND prev.org_id = %(org)s""", {"org": org_id})
    moves = db.one(conn, """
        SELECT count(*) FILTER (WHERE pe.start_date = d.today_date) AS hires,
               count(*) FILTER (WHERE pe.end_date = d.prev_date) AS exits
        FROM people pe JOIN v_org_closure c ON c.org_id = pe.org_id CROSS JOIN v_snapshot_days d
        WHERE c.ancestor_id = %s""", (org_id,))
    flow = db.one(conn, """
        SELECT count(*) FILTER (WHERE e.to_status = 'submitted') AS submitted,
               count(*) FILTER (WHERE e.to_status = 'vp_approved') AS approved,
               count(*) FILTER (WHERE e.to_status = 'req_open') AS opened,
               count(*) FILTER (WHERE e.to_status = 'filled') AS filled
        FROM request_events e
        JOIN backfill_requests b ON b.id = e.backfill_request_id
        JOIN positions p ON p.id = b.position_id
        JOIN v_org_closure c ON c.org_id = p.org_id
        WHERE c.ancestor_id = %s AND e.at > now() - interval '24 hours'""", (org_id,))
    resolved = db.one(conn, """
        SELECT count(*) AS n FROM v_exceptions e JOIN v_org_closure c ON c.org_id = e.org_id
        WHERE c.ancestor_id = %s AND e.is_resolved AND e.resolved_at > now() - interval '24 hours'""", (org_id,))["n"]
    return {**snap, **moves, "flow": flow, "resolved": resolved}


def org_summary(conn, org_id: int) -> dict:
    return db.one(conn, """
        SELECT u.org_id, u.name, u.usable_open, u.approved, u.filled, u.open_no_req, b.budget, b.projected, b.variance, b.pct_of_budget, b.state,
               (SELECT count(*) FROM v_exceptions e JOIN v_org_closure c ON c.org_id = e.org_id
                 WHERE c.ancestor_id = u.org_id AND NOT e.is_resolved) AS exceptions
        FROM v_usable_open u JOIN v_budget b ON b.org_id = u.org_id WHERE u.org_id = %s""", (org_id,))


@router.get("/today", response_class=HTMLResponse, include_in_schema=False)
def today(request: Request):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        role, me = ctx["role"], ctx["me"]
        ctx["check"] = latest_check(conn)
        if role == "svp":
            ctx.update(summary=org_summary(conn, me["org_id"]), changes=since_yesterday(conn, me["org_id"]),
                       vps=db.query(conn, """
                           SELECT u.org_id, u.name, u.usable_open, b.pct_of_budget, b.state FROM v_usable_open u
                           JOIN v_budget b ON b.org_id = u.org_id WHERE u.parent_id = %s ORDER BY b.pct_of_budget DESC""", (me["org_id"],)),
                       pending=db.one(conn, """
                           SELECT count(*) AS n FROM v_backfill_requests r JOIN v_org_closure c ON c.org_id = r.org_id
                           WHERE c.ancestor_id = %s AND r.status = 'submitted'""", (me["org_id"],))["n"])
        elif role == "vp":
            ctx.update(summary=org_summary(conn, me["org_id"]),
                       inbox=db.query(conn, """
                           SELECT r.*, u.usable_open AS vp_usable_open, pc.annual_cost, b.pct_of_budget, b.state AS budget_state, b.variance
                           FROM v_backfill_requests r
                           JOIN v_usable_open u ON u.org_id = r.vp_id
                           JOIN v_budget b ON b.org_id = r.vp_id
                           LEFT JOIN v_position_cost pc ON pc.position_id = r.position_id
                           WHERE r.status = 'submitted' AND r.vp_approver_id = %s
                           ORDER BY (r.urgency = 'urgent') DESC, r.updated_at""", (me["id"],)),
                       leaving=db.one(conn, """
                           SELECT count(*) AS n FROM v_backfill_candidates k JOIN v_org_closure c ON c.org_id = k.org_id
                           WHERE c.ancestor_id = %s AND k.end_date >= today()""", (me["org_id"],))["n"])
        elif role == "recruiter":
            ctx.update(
                inbox=db.query(conn, """
                    SELECT r.* FROM v_backfill_requests r
                    WHERE r.status = 'recruiter_assigned' AND r.recruiter_id = %s ORDER BY r.updated_at""", (me["id"],)),
                aging=db.query(conn, """
                    SELECT s.id, s.status, s.opened_at, today() - s.opened_at AS age_days, s.backfill_request_id,
                           p.id AS position_id, p.position_code, p.job_family, p.level, o.name AS org_name
                    FROM staffing_requests s JOIN positions p ON p.id = s.position_id JOIN orgs o ON o.id = p.org_id
                    WHERE s.recruiter_id = %s AND s.status IN ('open', 'offer_out')
                    ORDER BY s.opened_at LIMIT 100""", (me["id"],)))
            ages = [r["age_days"] for r in ctx["aging"]]
            ctx["age_stats"] = {"total": len(ages), "over60": sum(a > 60 for a in ages), "mid": sum(30 < a <= 60 for a in ages),
                                "median": sorted(ages)[len(ages) // 2] if ages else 0,
                                "offers": sum(r["status"] == "offer_out" for r in ctx["aging"])}
        elif role == "rm":
            ctx.update(
                summary=org_summary(conn, 1),
                by_type=db.query(conn, """
                    SELECT exception_type, type_label, count(*) FILTER (WHERE NOT is_resolved) AS open, count(*) AS total
                    FROM v_exceptions GROUP BY 1, 2 ORDER BY 3 DESC"""),
                over=db.query(conn, "SELECT org_id, name, pct_of_budget, variance FROM v_budget WHERE level = 'vp' AND state = 'over' ORDER BY pct_of_budget DESC"),
                stuck=db.query(conn, """
                    SELECT r.id, r.departing_name, r.status, r.waiting_on, r.time_in_status FROM v_backfill_requests r
                    WHERE r.status IN ('submitted', 'recruiter_assigned') AND r.time_in_status > interval '3 days'
                    ORDER BY r.time_in_status DESC LIMIT 5"""))
        else:   # requester
            ctx.update(
                mine=db.query(conn, "SELECT r.* FROM v_backfill_requests r WHERE r.requested_by = %s ORDER BY r.updated_at DESC LIMIT 20", (me["id"],)),
                leaving=db.query(conn, """
                    SELECT k.* FROM v_backfill_candidates k JOIN v_org_closure c ON c.org_id = k.org_id
                    WHERE c.ancestor_id = %s AND k.end_date >= today() ORDER BY k.end_date LIMIT 8""", (me["org_id"],)))
    return web.render(request, "today.html", ctx)
