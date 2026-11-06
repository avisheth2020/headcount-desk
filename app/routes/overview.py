"""Headcount: "How many people can we actually hire?" plus the rows behind every number."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import db, web

router = APIRouter()
PAGE_SIZE = 50
CHILD_LABEL = {"company": "By SVP", "svp": "By VP org", "vp": "By director", "director": "By team"}


def waterfall_steps(org: dict) -> list[dict]:
    """The bars of the waterfall: approved, then each bucket taken away, then what is left."""
    steps = [{"label": "Approved", "value": org["approved"], "from": 0, "to": org["approved"], "kind": "base",
              "href": f"/plan?org={org['org_id']}", "hint": web.BUCKETS["approved"][1]}]
    level = org["approved"]
    for key in ("filled", "committed", "reserve", "negative"):
        steps.append({"label": web.BUCKETS[key][0], "value": org[key], "from": level - org[key], "to": level, "kind": "minus",
                      "href": f"/positions?org={org['org_id']}&bucket={key}", "hint": web.BUCKETS[key][1]})
        level -= org[key]
    steps.append({"label": "Usable open", "value": level, "from": 0, "to": level, "kind": "result",
                  "href": "#breakdown", "hint": web.BUCKETS["usable_open"][1]})
    return steps


def breadcrumbs(conn, org_id: int) -> list[dict]:
    return db.query(conn, """
        SELECT a.id, a.name, a.level
        FROM v_org_closure c JOIN orgs a ON a.id = c.ancestor_id
        WHERE c.org_id = %s ORDER BY c.depth DESC""", (org_id,))


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def headcount(request: Request, org: int | None = None, flash: str | None = None):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_id = org or ctx["personas"]["svp"]["org_id"]      # default: the Research SVP
        me = db.one(conn, "SELECT * FROM v_usable_open WHERE org_id = %s", (org_id,))
        if me is None:
            raise HTTPException(404, "No such org")
        children = db.query(conn, "SELECT * FROM v_usable_open WHERE parent_id = %s ORDER BY name", (org_id,))
        direct = db.one(conn, """
            SELECT d.*, d.approved - d.filled - d.committed - d.reserve - d.negative AS usable_open
            FROM v_headcount_direct d WHERE org_id = %s""", (org_id,))
        exceptions = {r["org_id"]: r["n"] for r in db.query(conn, """
            SELECT c.ancestor_id AS org_id, count(*) AS n
            FROM v_exceptions e JOIN v_org_closure c ON c.org_id = e.org_id
            WHERE NOT e.is_resolved GROUP BY c.ancestor_id""")}
        ctx.update(
            org=me, steps=waterfall_steps(me), children=children, direct=direct, exceptions=exceptions, flash=flash,
            crumbs=breadcrumbs(conn, org_id),
            svps=db.query(conn, "SELECT id, name FROM orgs WHERE level IN ('company', 'svp') ORDER BY id"),
            leader=db.one(conn, "SELECT p.full_name FROM orgs o JOIN people p ON p.id = o.leader_person_id WHERE o.id = %s", (org_id,)),
            child_label=CHILD_LABEL.get(me["level"]),
            has_direct=any(direct[k] for k in ("approved", "filled", "committed", "reserve", "negative")) and children,
        )
    return web.render(request, "headcount.html", ctx)


@router.get("/positions", response_class=HTMLResponse, include_in_schema=False)
def positions(request: Request, org: int, bucket: str | None = None, direct: int = 0, page: int = 1):
    """The rows behind a number: every position in an org (and below it), optionally one bucket."""
    if bucket is not None and bucket not in ("filled", "committed", "open_no_req", "reserve", "negative"):
        raise HTTPException(404, "No such bucket")
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = db.one(conn, "SELECT id, name, level FROM orgs WHERE id = %s", (org,))
        if org_row is None:
            raise HTTPException(404, "No such org")
        where = "c.ancestor_id = %(org)s AND (%(bucket)s::text IS NULL OR ps.bucket = %(bucket)s)"
        if direct:
            where += " AND c.depth = 0"
        params = {"org": org, "bucket": bucket, "limit": PAGE_SIZE, "offset": (max(page, 1) - 1) * PAGE_SIZE}
        total = db.one(conn, f"SELECT count(*) AS n FROM v_position_status ps JOIN v_org_closure c ON c.org_id = ps.org_id WHERE {where}", params)["n"]
        rows = db.query(conn, f"""
            SELECT ps.*, o.name AS org_name, pe.full_name, pe.end_date, rec.full_name AS recruiter_name
            FROM v_position_status ps
            JOIN v_org_closure c ON c.org_id = ps.org_id
            JOIN orgs o ON o.id = ps.org_id
            LEFT JOIN people pe ON pe.id = ps.person_id
            LEFT JOIN people rec ON rec.id = ps.recruiter_id
            WHERE {where}
            ORDER BY o.name, ps.position_code
            LIMIT %(limit)s OFFSET %(offset)s""", params)
        ctx.update(org=org_row, bucket=bucket, direct=direct, rows=rows, total=total, page=max(page, 1),
                   pages=max(1, -(-total // PAGE_SIZE)), crumbs=breadcrumbs(conn, org))
    return web.render(request, "positions.html", ctx)


@router.get("/positions/{position_id}", response_class=HTMLResponse, include_in_schema=False)
def position_detail(request: Request, position_id: int):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        pos = db.one(conn, """
            SELECT ps.*, o.name AS org_name, pe.full_name, pe.email, pe.start_date, pe.end_date,
                   rec.full_name AS recruiter_name, sr.opened_at AS request_opened_at
            FROM v_position_status ps
            JOIN orgs o ON o.id = ps.org_id
            LEFT JOIN people pe ON pe.id = ps.person_id
            LEFT JOIN people rec ON rec.id = ps.recruiter_id
            LEFT JOIN staffing_requests sr ON sr.id = ps.staffing_request_id
            WHERE ps.position_id = %s""", (position_id,))
        if pos is None:
            raise HTTPException(404, "No such position")
        ctx.update(
            pos=pos, crumbs=breadcrumbs(conn, pos["org_id"]),
            exceptions=db.query(conn, "SELECT * FROM v_exceptions WHERE position_id = %s", (position_id,)),
            backfills=db.query(conn, """
                SELECT b.id, b.status, b.created_at, d.full_name AS departing_name
                FROM backfill_requests b JOIN people d ON d.id = b.departing_person_id
                WHERE b.position_id = %s ORDER BY b.created_at DESC""", (position_id,)),
        )
    return web.render(request, "position_detail.html", ctx)


@router.get("/plan", response_class=HTMLResponse, include_in_schema=False)
def plan_lines(request: Request, org: int, direct: int = 0):
    """The rows behind "Approved": plan lines for an org and everything below it,
    with the previous plan version alongside."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = db.one(conn, "SELECT id, name, level FROM orgs WHERE id = %s", (org,))
        if org_row is None:
            raise HTTPException(404, "No such org")
        rows = db.query(conn, """
            SELECT o.id AS org_id, o.name AS org_name, o.level, cur.job_family,
                   cur.approved_headcount, cur.approved_cost_usd, prev.approved_headcount AS previous_headcount
            FROM plan_lines cur
            JOIN v_current_plan cp ON cp.id = cur.plan_version_id
            JOIN v_org_closure c ON c.org_id = cur.org_id
            JOIN orgs o ON o.id = cur.org_id
            LEFT JOIN plan_lines prev
                   ON prev.org_id = cur.org_id AND prev.job_family = cur.job_family
                  AND prev.plan_version_id = (SELECT id FROM plan_versions WHERE locked_at < cp.locked_at
                                              ORDER BY locked_at DESC LIMIT 1)
            WHERE c.ancestor_id = %s AND (c.depth = 0 OR NOT %s)
            ORDER BY o.name, cur.job_family""", (org, bool(direct)))
        ctx.update(org=org_row, rows=rows, crumbs=breadcrumbs(conn, org), direct=direct,
                   total=sum(r["approved_headcount"] for r in rows),
                   total_cost=sum(r["approved_cost_usd"] for r in rows),
                   total_previous=sum(r["previous_headcount"] or 0 for r in rows),
                   versions=db.query(conn, "SELECT name, locked_at FROM plan_versions WHERE locked_at IS NOT NULL ORDER BY locked_at"))
    return web.render(request, "plan.html", ctx)
