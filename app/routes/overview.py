"""Headcount: "How many people can we actually hire?" plus the rows behind every number."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import charts, db, trends, web

router = APIRouter()
PAGE_SIZE = 50
CHILD_LABEL = {"company": "By SVP", "svp": "By VP org", "vp": "By director", "director": "By team"}
SEGMENTS = ["filled", "committed", "reserve", "negative"]
SEAT_KINDS = ["committed", "reserve", "negative", "usable_open"]       # the unfilled seats, in the order they are drawn
FOCUS = {"committed": "committed", "reserve": "reserve", "negative": "negative", "usable": "usable_open"}


def breadcrumbs(conn, org_id: int) -> list[dict]:
    return db.query(conn, """
        SELECT a.id, a.name, a.level
        FROM v_org_closure c JOIN orgs a ON a.id = c.ancestor_id
        WHERE c.org_id = %s ORDER BY c.depth DESC""", (org_id,))


def get_org(conn, org_id: int) -> dict:
    row = db.one(conn, "SELECT id, name, level, parent_id FROM orgs WHERE id = %s", (org_id,))
    if row is None:
        raise HTTPException(404, "No such org")
    return row


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def headcount(request: Request, org: int | None = None, flash: str | None = None, focus: str = "usable"):
    focus = focus if focus in FOCUS else "usable"
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_id = org or ctx["personas"]["svp"]["org_id"]      # default: the Research SVP
        me = db.one(conn, "SELECT * FROM v_usable_open WHERE org_id = %s", (org_id,))
        if me is None:
            raise HTTPException(404, "No such org")
        order, sort, direction = web.sorting(request, {
            "name": "u.name", "approved": "u.approved", "filled": "u.filled", "committed": "u.committed",
            "reserve": "u.reserve", "negative": "u.negative", "usable": "u.usable_open", "budget": "b.pct_of_budget"}, "name")
        children = db.query(conn, f"""
            SELECT u.*, b.budget, b.projected, b.pct_of_budget, b.state
            FROM v_usable_open u JOIN v_budget b ON b.org_id = u.org_id
            WHERE u.parent_id = %s ORDER BY {order}""", (org_id,))
        if request.query_params.get("format") == "csv":
            return web.csv_response(f"headcount-{me['name']}.csv".replace(" ", "-").lower(), [
                ("Org", "name"), ("Approved", "approved"), ("Filled", "filled"), ("Committed", "committed"), ("Reserve", "reserve"),
                ("Negative", "negative"), ("Usable open", "usable_open"), ("Budget USD", "budget"), ("Projected USD", "projected")], children)
        direct = db.one(conn, """
            SELECT d.*, d.approved - d.filled - d.committed - d.reserve - d.negative AS usable_open
            FROM v_headcount_direct d WHERE org_id = %s""", (org_id,))
        exceptions = {r["org_id"]: r["n"] for r in db.query(conn, """
            SELECT c.ancestor_id AS org_id, count(*) AS n
            FROM v_exceptions e JOIN v_org_closure c ON c.org_id = e.org_id
            WHERE NOT e.is_resolved GROUP BY c.ancestor_id""")}
        key = FOCUS[focus]
        ranked = [{"name": c["name"], key: c[key], "href": f"/?org={c['org_id']}"} for c in children]
        if direct and children and any(direct[k] for k in FOCUS.values()):
            ranked.append({"name": f"Held at {me['name']}", key: direct[key], "href": None})
        ctx.update(
            org=me, children=children, direct=direct, exceptions=exceptions, flash=flash, sort=sort, dir=direction,
            focus=focus, focus_key=key, seat_kinds=SEAT_KINDS, trend=trends.seat_history(conn, org_id),
            ranked=[{**r, "key": r["name"], "text": f"{r[key]:,}".replace("-", "−")} for r in charts.share_bars(ranked, key)],
            budget=db.one(conn, "SELECT * FROM v_budget WHERE org_id = %s", (org_id,)),
            unfilled=me["approved"] - me["filled"], segments=SEGMENTS,
            crumbs=breadcrumbs(conn, org_id),
            svps=db.query(conn, "SELECT id, name FROM orgs WHERE level IN ('company', 'svp') ORDER BY id"),
            leader=db.one(conn, "SELECT p.full_name FROM orgs o JOIN people p ON p.id = o.leader_person_id WHERE o.id = %s", (org_id,)),
            child_label=CHILD_LABEL.get(me["level"]),
            has_direct=any(direct[k] for k in ("approved", "filled", "committed", "reserve", "negative")) and children,
        )
    return web.render(request, "headcount.html", ctx)


POSITION_SORTS = {"code": "ps.position_code", "team": "o.name", "family": "ps.job_family", "level": "ps.level",
                  "status": "ps.bucket", "who": "pe.full_name", "cost": "cr.annual_loaded_cost_usd", "opened": "ps.opened_at"}


@router.get("/positions", response_class=HTMLResponse, include_in_schema=False)
def positions(request: Request, org: int = 1, bucket: str | None = None, direct: int = 0, page: int = 1):
    """The rows behind a number: every position in an org (and below it), optionally one bucket."""
    if bucket is not None and bucket not in ("filled", "committed", "open_no_req", "reserve", "negative"):
        raise HTTPException(404, "No such bucket")
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = get_org(conn, org)
        order, sort, direction = web.sorting(request, POSITION_SORTS, "team")
        where = "c.ancestor_id = %(org)s AND (%(bucket)s::text IS NULL OR ps.bucket = %(bucket)s)"
        if direct:
            where += " AND c.depth = 0"
        as_csv = request.query_params.get("format") == "csv"
        page = max(page, 1)
        params = {"org": org, "bucket": bucket, "limit": 5000 if as_csv else PAGE_SIZE, "offset": 0 if as_csv else (page - 1) * PAGE_SIZE}
        total = db.one(conn, f"SELECT count(*) AS n FROM v_position_status ps JOIN v_org_closure c ON c.org_id = ps.org_id WHERE {where}", params)["n"]
        rows = db.query(conn, f"""
            SELECT ps.*, o.name AS org_name, p.location, pe.full_name, pe.end_date, rec.full_name AS recruiter_name,
                   cr.annual_loaded_cost_usd AS annual_cost
            FROM v_position_status ps
            JOIN v_org_closure c ON c.org_id = ps.org_id
            JOIN positions p ON p.id = ps.position_id
            JOIN orgs o ON o.id = ps.org_id
            LEFT JOIN people pe ON pe.id = ps.person_id
            LEFT JOIN people rec ON rec.id = ps.recruiter_id
            LEFT JOIN cost_rates cr ON cr.job_family = ps.job_family AND cr.level = ps.level AND cr.location = p.location
            WHERE {where}
            ORDER BY {order}, ps.position_code
            LIMIT %(limit)s OFFSET %(offset)s""", params)
        if as_csv:
            return web.csv_response(f"positions-{org_row['name']}.csv".replace(" ", "-").lower(), [
                ("Position", "position_code"), ("Team", "org_name"), ("Job family", "job_family"), ("Level", "level"),
                ("Location", "location"), ("Status", "bucket"), ("Person", "full_name"), ("Recruiter", "recruiter_name"),
                ("Annual cost USD", "annual_cost"), ("Open since", "opened_at")], rows)
        ctx.update(org=org_row, bucket=bucket, direct=direct, rows=rows, total=total, page=page, size=PAGE_SIZE,
                   pages=max(1, -(-total // PAGE_SIZE)), crumbs=breadcrumbs(conn, org), sort=sort, dir=direction)
    return web.render(request, "positions.html", ctx)


@router.get("/positions/{position_id}", response_class=HTMLResponse, include_in_schema=False)
def position_detail(request: Request, position_id: int):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        pos = db.one(conn, """
            SELECT ps.*, o.name AS org_name, p.location, pe.full_name, pe.email, pe.start_date, pe.end_date,
                   rec.full_name AS recruiter_name, sr.opened_at AS request_opened_at, cr.annual_loaded_cost_usd AS annual_cost
            FROM v_position_status ps
            JOIN positions p ON p.id = ps.position_id
            JOIN orgs o ON o.id = ps.org_id
            LEFT JOIN people pe ON pe.id = ps.person_id
            LEFT JOIN people rec ON rec.id = ps.recruiter_id
            LEFT JOIN staffing_requests sr ON sr.id = ps.staffing_request_id
            LEFT JOIN cost_rates cr ON cr.job_family = ps.job_family AND cr.level = ps.level AND cr.location = p.location
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
            can_backfill=db.one(conn, "SELECT person_id FROM v_backfill_candidates WHERE position_id = %s", (position_id,)),
        )
    return web.render(request, "position_detail.html", ctx)


@router.get("/people/{person_id}", response_class=HTMLResponse, include_in_schema=False)
def person_detail(request: Request, person_id: int):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        person = db.one(conn, """
            SELECT pe.*, o.name AS org_name, m.full_name AS manager_name, path.vp_name, path.svp_name
            FROM people pe JOIN orgs o ON o.id = pe.org_id JOIN v_org_path path ON path.org_id = pe.org_id
            LEFT JOIN people m ON m.id = pe.manager_id WHERE pe.id = %s""", (person_id,))
        if person is None:
            raise HTTPException(404, "No such person")
        ctx.update(
            person=person, crumbs=breadcrumbs(conn, person["org_id"]),
            seats=db.query(conn, """
                SELECT ps.position_id, ps.position_code, ps.bucket, o.name AS org_name
                FROM v_position_status ps JOIN orgs o ON o.id = ps.org_id WHERE ps.person_id = %s ORDER BY ps.position_id""", (person_id,)),
            reports=db.one(conn, "SELECT count(*) AS n FROM people WHERE manager_id = %s AND (end_date IS NULL OR end_date >= today())", (person_id,))["n"],
            backfills=db.query(conn, "SELECT id, status, created_at FROM backfill_requests WHERE departing_person_id = %s ORDER BY created_at DESC", (person_id,)),
        )
    return web.render(request, "person_detail.html", ctx)


@router.get("/plan", response_class=HTMLResponse, include_in_schema=False)
def plan_lines(request: Request, org: int = 1, direct: int = 0, page: int = 1):
    """The rows behind "Approved": plan lines for an org and everything below it,
    with the previous plan version alongside."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = get_org(conn, org)
        order, sort, direction = web.sorting(request, {
            "org": "o.name", "family": "cur.job_family", "previous": "prev.approved_headcount",
            "approved": "cur.approved_headcount", "cost": "cur.approved_cost_usd"}, "org")
        rows = db.query(conn, f"""
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
            ORDER BY {order}, o.name, cur.job_family""", (org, bool(direct)))
        if request.query_params.get("format") == "csv":
            return web.csv_response(f"plan-{org_row['name']}.csv".replace(" ", "-").lower(), [
                ("Org", "org_name"), ("Job family", "job_family"), ("Previous", "previous_headcount"),
                ("Approved", "approved_headcount"), ("Approved cost USD", "approved_cost_usd")], rows)
        size, page = 100, max(page, 1)
        ctx.update(org=org_row, rows=rows[(page - 1) * size: page * size], crumbs=breadcrumbs(conn, org), direct=direct,
                   page=page, size=size, pages=max(1, -(-len(rows) // size)), count=len(rows), sort=sort, dir=direction,
                   total=sum(r["approved_headcount"] for r in rows),
                   total_cost=sum(r["approved_cost_usd"] for r in rows),
                   total_previous=sum(r["previous_headcount"] or 0 for r in rows),
                   versions=db.query(conn, "SELECT name, locked_at FROM plan_versions WHERE locked_at IS NOT NULL AND coalesce(effective_from, locked_at::date) <= today() ORDER BY locked_at"))
    return web.render(request, "plan.html", ctx)


ORG_ROW_SQL = """
    SELECT u.org_id, u.name, u.level, u.parent_id, u.approved, u.filled, u.usable_open,
           b.budget, b.projected, b.pct_of_budget, b.state, p.full_name AS leader_name,
           EXISTS (SELECT 1 FROM orgs k WHERE k.parent_id = u.org_id) AS has_children
    FROM v_usable_open u
    JOIN v_budget b ON b.org_id = u.org_id
    JOIN orgs o ON o.id = u.org_id
    LEFT JOIN people p ON p.id = o.leader_person_id
"""


@router.get("/org", response_class=HTMLResponse, include_in_schema=False)
def org_explorer(request: Request):
    """Browse the hierarchy with seats and dollars at every level. Deeper levels load on demand."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        rows = db.query(conn, ORG_ROW_SQL + " WHERE u.level IN ('company', 'svp', 'vp') ORDER BY u.org_id")
        by_parent: dict = {}
        for r in rows:
            by_parent.setdefault(r["parent_id"], []).append(r)
        ordered = []

        def walk(parent_id, depth):
            for r in sorted(by_parent.get(parent_id, []), key=lambda r: r["name"]):
                ordered.append({**r, "depth": depth, "expanded": r["level"] in ("company", "svp")})
                walk(r["org_id"], depth + 1)
        walk(None, 0)
        ctx.update(rows=ordered)
    return web.render(request, "org.html", ctx)


@router.get("/org/children", response_class=HTMLResponse, include_in_schema=False)
def org_children(request: Request, parent: int, depth: int = 0):
    with db.get_conn() as conn:
        rows = db.query(conn, ORG_ROW_SQL + " WHERE u.parent_id = %s ORDER BY u.name", (parent,))
    depth = min(max(depth, 0), 6)
    return web.render(request, "_org_rows.html", {"rows": [{**r, "depth": depth + 1, "expanded": False} for r in rows]})
