"""Exceptions: "What's wrong in the data, and who fixes it?" A to-do list, grouped by owner."""

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import db, permissions, web

router = APIRouter()

TYPES = {  # exception type -> (label, one-line definition)
    "stale_open": ("Stale open", "A seat that has been empty for more than 90 days with nobody recruiting for it."),
    "duplicate": ("Duplicate seat", "The same person sitting in two seats. One of them is not real."),
    "ghost_fill": ("Ghost fill", "A seat still assigned to someone who has already left."),
    "miscoded": ("Mis-coded", "A seat coded to a job family its team has no plan for."),
    "reserve_misplaced": ("Misplaced reserve", "Reserve parked on a team instead of held by the SVP."),
}


def progress(conn, org_id: int) -> dict:
    return db.one(conn, """
        SELECT count(*) AS total, count(*) FILTER (WHERE e.is_resolved) AS resolved
        FROM v_exceptions e JOIN v_org_closure c ON c.org_id = e.org_id
        WHERE c.ancestor_id = %s""", (org_id,))


@router.get("/exceptions", response_class=HTMLResponse, include_in_schema=False)
def exceptions(request: Request, org: int = 1, type: str | None = None, show: str = "open"):
    if type is not None and type not in TYPES:
        raise HTTPException(404, "No such exception type")
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = db.one(conn, "SELECT id, name, level FROM orgs WHERE id = %s", (org,))
        if org_row is None:
            raise HTTPException(404, "No such org")
        rows = db.query(conn, """
            SELECT e.*
            FROM v_exceptions e JOIN v_org_closure c ON c.org_id = e.org_id
            WHERE c.ancestor_id = %(org)s
              AND (%(type)s::text IS NULL OR e.exception_type = %(type)s)
              AND (%(all)s OR NOT e.is_resolved)
            ORDER BY e.is_resolved, e.age_days DESC NULLS LAST, e.position_code""",
            {"org": org, "type": type, "all": show == "all"})
        by_type = {r["exception_type"]: r["n"] for r in db.query(conn, """
            SELECT e.exception_type, count(*) AS n
            FROM v_exceptions e JOIN v_org_closure c ON c.org_id = e.org_id
            WHERE c.ancestor_id = %s AND NOT e.is_resolved GROUP BY 1""", (org,))}
        if request.query_params.get("format") == "csv":
            return web.csv_response("exceptions.csv", [
                ("Type", "type_label"), ("Position", "position_code"), ("Team", "org_name"), ("Owner", "owner_name"),
                ("Detail", "detail"), ("Suggested fix", "suggested_fix"), ("Age in days", "age_days"), ("Resolved", "is_resolved")], rows)
        groups: dict[int, dict] = {}
        for r in rows:
            g = groups.setdefault(r["owner_id"], {"owner_id": r["owner_id"], "owner_name": r["owner_name"],
                                                  "owner_org_name": r["owner_org_name"], "rows": [], "open": 0})
            g["rows"].append(r)
            g["open"] += not r["is_resolved"]
        ctx.update(
            org=org_row, type=type, show=show, TYPES=TYPES, can_resolve=permissions.can_resolve_exceptions(ctx["role"]), by_type=by_type, progress=progress(conn, org),
            groups=sorted(groups.values(), key=lambda g: -g["open"]),
            svps=db.query(conn, "SELECT id, name FROM orgs WHERE level IN ('company', 'svp') ORDER BY id"),
        )
    return web.render(request, "exceptions.html", ctx)


def _toggle(request: Request, exception_type: str, position_id: int, org: int, resolve: bool):
    if exception_type not in TYPES:
        raise HTTPException(404, "No such exception type")
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        seat = db.one(conn, "SELECT org_id FROM positions WHERE id = %s", (position_id,))
        if seat is None:
            raise HTTPException(404, "No such position")
        permissions.check_resolve_exception(conn, ctx, seat["org_id"])
        if resolve:
            conn.execute("""
                INSERT INTO exception_resolutions (exception_type, position_id, resolved_by) VALUES (%s, %s, %s)
                ON CONFLICT (exception_type, position_id) DO NOTHING""", (exception_type, position_id, ctx["me"]["id"]))
        else:
            conn.execute("DELETE FROM exception_resolutions WHERE exception_type = %s AND position_id = %s",
                         (exception_type, position_id))
        row = db.one(conn, "SELECT * FROM v_exceptions WHERE exception_type = %s AND position_id = %s",
                     (exception_type, position_id))
        if row is None:
            raise HTTPException(404, "That exception no longer exists")
        ctx.update(e=row, org={"id": org}, progress=progress(conn, org), oob=True, can_resolve=True)
    response = web.render(request, "_exception_row.html", ctx)
    if resolve:   # tell the page to show a toast with an Undo button
        response.headers["HX-Trigger"] = json.dumps({"toast": {
            "message": f"{row['position_code']} marked resolved.",
            "undo": f"/exceptions/unresolve?exception_type={exception_type}&position_id={position_id}&org={org}",
            "target": f"#exc-{exception_type}-{position_id}"}})
    return response


@router.post("/exceptions/resolve", response_class=HTMLResponse, include_in_schema=False)
def resolve(request: Request, exception_type: str = Form(...), position_id: int = Form(...), org: int = Form(1)):
    """Mark one exception resolved. Returns just that row, updated in place."""
    return _toggle(request, exception_type, position_id, org, resolve=True)


@router.post("/exceptions/unresolve", response_class=HTMLResponse, include_in_schema=False)
def unresolve(request: Request, exception_type: str, position_id: int, org: int = 1):
    return _toggle(request, exception_type, position_id, org, resolve=False)
