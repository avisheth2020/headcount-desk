"""Forecast: "Where will we end the quarter?" Today plus expected hires minus expected exits, with a range."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import db, web
from app.routes.overview import breadcrumbs, get_org

router = APIRouter()
PAGE_SIZE = 50


@router.get("/forecast", response_class=HTMLResponse, include_in_schema=False)
def forecast(request: Request, org: int | None = None):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_id = org or (ctx["me"]["org_id"] if ctx["role"] in ("svp", "vp") else 1)
        me = db.one(conn, "SELECT * FROM v_forecast WHERE org_id = %s", (org_id,))
        if me is None:
            raise HTTPException(404, "No such org")
        order, sort, direction = web.sorting(request, {
            "name": "f.name", "now": "f.in_seats", "hires": "f.expected_hires", "exits": "f.expected_exits",
            "projected": "f.projected", "approved": "f.approved", "gap": "f.approved - f.projected",
            "spend": "f.projected_run_rate / nullif(f.budget, 0)"}, "name")
        children = db.query(conn, f"SELECT f.* FROM v_forecast f WHERE f.parent_id = %s ORDER BY {order}", (org_id,))
        if request.query_params.get("format") == "csv":
            return web.csv_response(f"forecast-{me['name']}.csv".replace(" ", "-").lower(), [
                ("Org", "name"), ("In seats today", "in_seats"), ("Expected hires", "expected_hires"), ("Expected exits", "expected_exits"),
                ("Projected", "projected"), ("P25", "projected_low"), ("P75", "projected_high"), ("Approved", "approved"),
                ("Projected run-rate USD", "projected_run_rate"), ("Budget USD", "budget")], children)
        ctx.update(
            org=me, children=children, sort=sort, dir=direction, crumbs=breadcrumbs(conn, org_id),
            svps=db.query(conn, "SELECT id, name FROM orgs WHERE level IN ('company', 'svp') ORDER BY id"),
            history=db.one(conn, """
                SELECT count(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY days) AS median,
                       percentile_cont(0.25) WITHIN GROUP (ORDER BY days) AS p25,
                       percentile_cont(0.75) WITHIN GROUP (ORDER BY days) AS p75 FROM v_time_to_fill"""),
            attrition=db.one(conn, """
                SELECT a.*, o.name FROM v_attrition a JOIN orgs o ON o.id = a.org_id
                WHERE a.org_id = coalesce((SELECT svp_id FROM v_org_path WHERE org_id = %s), 1)""", (org_id,)),
            flagged=db.query(conn, """
                SELECT f.org_id, f.name, f.over_plan, f.over_budget, f.projected, f.approved, f.projected_run_rate, f.budget
                FROM v_forecast f JOIN v_org_closure c ON c.org_id = f.org_id
                WHERE c.ancestor_id = %s AND f.level = 'vp' AND (f.over_plan OR f.over_budget)
                ORDER BY f.projected_run_rate / nullif(f.budget, 0) DESC""", (org_id,)),
        )
    return web.render(request, "forecast.html", ctx)


@router.get("/forecast/requests", response_class=HTMLResponse, include_in_schema=False)
def forecast_requests(request: Request, org: int = 1, page: int = 1):
    """The rows behind "expected hires": every open request and its chance of being filled by quarter end."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = get_org(conn, org)
        order, sort, direction = web.sorting(request, {
            "code": "p.position_code", "team": "o.name", "opened": "fp.opened_at", "age": "fp.age_days", "chance": "fp.p_fill"}, "chance", "desc")
        rows = db.query(conn, f"""
            SELECT fp.*, p.position_code, p.job_family, p.level, o.name AS org_name
            FROM v_fill_probability fp
            JOIN v_org_closure c ON c.org_id = fp.org_id
            JOIN positions p ON p.id = fp.position_id
            JOIN orgs o ON o.id = fp.org_id
            WHERE c.ancestor_id = %s ORDER BY {order}, p.position_code""", (org,))
        if request.query_params.get("format") == "csv":
            return web.csv_response("forecast-open-requests.csv", [
                ("Position", "position_code"), ("Team", "org_name"), ("Stage", "status"), ("Opened", "opened_at"),
                ("Age in days", "age_days"), ("Age at quarter end", "age_at_quarter_end"), ("Chance filled by quarter end", "p_fill")], rows)
        page = max(page, 1)
        ctx.update(org=org_row, rows=rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE], total=len(rows), page=page, size=PAGE_SIZE,
                   pages=max(1, -(-len(rows) // PAGE_SIZE)), sort=sort, dir=direction, crumbs=breadcrumbs(conn, org),
                   expected=sum(r["p_fill"] for r in rows), fiscal=db.one(conn, "SELECT * FROM v_fiscal_now"))
    return web.render(request, "forecast_requests.html", ctx)


@router.get("/forecast/exits", response_class=HTMLResponse, include_in_schema=False)
def forecast_exits(request: Request, org: int = 1):
    """The rows behind the attrition rate: who left in the last 60 days."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = get_org(conn, org)
        rows = db.query(conn, """
            SELECT pe.id, pe.full_name, pe.job_family, pe.level, pe.end_date, o.name AS org_name
            FROM people pe JOIN v_org_closure c ON c.org_id = pe.org_id JOIN orgs o ON o.id = pe.org_id
            WHERE c.ancestor_id = %s AND pe.end_date BETWEEN today() - 60 AND today() - 1
            ORDER BY pe.end_date DESC, pe.full_name LIMIT 500""", (org,))
        ctx.update(org=org_row, rows=rows, crumbs=breadcrumbs(conn, org),
                   attrition=db.one(conn, "SELECT * FROM v_attrition WHERE org_id = %s", (org,)))
    return web.render(request, "forecast_exits.html", ctx)
