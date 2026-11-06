"""Budget: "Are we on budget?" Projected spend against the plan, for any org."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import db, web
from app.routes.overview import breadcrumbs

router = APIRouter()


@router.get("/budget", response_class=HTMLResponse, include_in_schema=False)
def budget(request: Request, org: int | None = None):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_id = org or (ctx["me"]["org_id"] if ctx["role"] in ("svp", "vp") else 1)
        me = db.one(conn, "SELECT * FROM v_budget WHERE org_id = %s", (org_id,))
        if me is None:
            raise HTTPException(404, "No such org")
        order, sort, direction = web.sorting(request, {
            "name": "b.name", "budget": "b.budget", "run_rate": "b.run_rate", "committed": "b.committed",
            "projected": "b.projected", "variance": "b.variance", "pct": "b.pct_of_budget"}, "pct", "desc")
        children = db.query(conn, f"SELECT b.* FROM v_budget b WHERE b.parent_id = %s ORDER BY {order}", (org_id,))
        if request.query_params.get("format") == "csv":
            return web.csv_response(f"budget-{me['name']}.csv".replace(" ", "-").lower(), [
                ("Org", "name"), ("Budget USD", "budget"), ("Run-rate USD", "run_rate"), ("Committed USD", "committed"),
                ("Projected USD", "projected"), ("Variance USD", "variance"), ("Percent of budget", "pct_of_budget"), ("State", "state")], children)
        fiscal = db.one(conn, "SELECT * FROM v_fiscal_now")
        direct = db.one(conn, """
            SELECT d.budget, d.run_rate, round(d.committed_annual * f.months_left / 12, 2) AS committed,
                   round(d.run_rate + d.committed_annual * f.months_left / 12, 2) AS projected
            FROM v_budget_direct d CROSS JOIN v_fiscal_now f WHERE d.org_id = %s""", (org_id,))
        ctx.update(org=me, children=children, fiscal=fiscal, direct=direct, sort=sort, dir=direction,
                   has_direct=bool(children) and (direct["budget"] or direct["run_rate"]),
                   seats=db.one(conn, "SELECT filled, negative, committed FROM v_usable_open WHERE org_id = %s", (org_id,)),
                   crumbs=breadcrumbs(conn, org_id),
                   svps=db.query(conn, "SELECT id, name FROM orgs WHERE level IN ('company', 'svp') ORDER BY id"),
                   over=db.query(conn, """
                       SELECT b.org_id, b.name, b.pct_of_budget, b.variance FROM v_budget b JOIN v_org_closure c ON c.org_id = b.org_id
                       WHERE c.ancestor_id = %s AND b.level = 'vp' AND b.state = 'over' ORDER BY b.pct_of_budget DESC""", (org_id,)))
    return web.render(request, "budget.html", ctx)
