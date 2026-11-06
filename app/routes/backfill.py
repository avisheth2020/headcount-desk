"""Requests: "Where is my backfill?" The queue, the tracker and the request form."""

from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db, permissions, web, workflow

router = APIRouter()

STEPS = ["Submitted", "VP approval", "Recruiter", "Request open", "Filled"]
# status -> how many steps are done (the next one is "now")
DONE = {"submitted": 1, "rejected": 1, "vp_approved": 2, "recruiter_assigned": 3, "req_open": 4, "filled": 5}
STATUS_LABELS = {"opened": "Reached an open staffing request", "submitted": "Waiting on VP", "recruiter_assigned": "Recruiter assigned", "req_open": "Request open",
                 "filled": "Filled", "rejected": "Rejected"}
MINE = {"vp": "vp_approver_id", "recruiter": "recruiter_id", "requester": "requested_by"}


def usable_open_for(conn, org_id: int) -> int:
    return db.one(conn, "SELECT usable_open FROM v_usable_open WHERE org_id = %s", (org_id,))["usable_open"]


@router.get("/requests", response_class=HTMLResponse, include_in_schema=False)
def requests_page(request: Request, scope: str | None = None, status: str | None = None):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        role, me = ctx["role"], ctx["me"]["id"]
        mine_col = MINE.get(role)
        scope = scope or ("mine" if mine_col else "all")
        where, params = ["TRUE"], {"me": me, "status": status}
        if scope == "mine" and mine_col:
            where.append(f"r.{mine_col} = %(me)s")
        if status == "opened":                               # the rows behind the median
            where.append("ct.days_to_open IS NOT NULL")
        elif status in STATUS_LABELS:
            where.append("r.status = %(status)s")
        order, sort, direction = web.sorting(request, {
            "id": "r.id", "who": "r.departing_name", "team": "r.team_name", "status": "r.status", "waiting": "r.waiting_on",
            "age": "r.time_in_status", "cycle": "ct.days_to_open", "submitted": "r.created_at"}, "submitted", "desc")
        default_order = "(r.status IN ('filled', 'rejected')), r.updated_at DESC"
        rows = db.query(conn, f"""
            SELECT r.*, ct.days_to_open
            FROM v_backfill_requests r
            LEFT JOIN v_backfill_cycle_time ct ON ct.backfill_request_id = r.id
            WHERE {' AND '.join(where)}
            ORDER BY {order if 'sort' in request.query_params else default_order}
            LIMIT 500""", params)
        if request.query_params.get("format") == "csv":
            return web.csv_response("backfill-requests.csv", [
                ("Request", "id"), ("Leaving", "departing_name"), ("Team", "team_name"), ("VP org", "vp_name"), ("Status", "status"),
                ("Waiting on", "waiting_on"), ("Urgency", "urgency"), ("Days to open request", "days_to_open"), ("Submitted", "created_at")], rows)
        inbox = []
        if role == "vp":
            inbox = db.query(conn, """
                SELECT r.*, u.usable_open AS vp_usable_open, pc.annual_cost, b.pct_of_budget, b.state AS budget_state, b.variance
                FROM v_backfill_requests r JOIN v_usable_open u ON u.org_id = r.vp_id
                JOIN v_budget b ON b.org_id = r.vp_id
                LEFT JOIN v_position_cost pc ON pc.position_id = r.position_id
                WHERE r.status = 'submitted' AND r.vp_approver_id = %s
                ORDER BY (r.urgency = 'urgent') DESC, r.updated_at""", (me,))
        elif role == "recruiter":
            inbox = db.query(conn, """
                SELECT r.* FROM v_backfill_requests r
                WHERE r.status = 'recruiter_assigned' AND r.recruiter_id = %s ORDER BY r.updated_at""", (me,))
        stats = db.one(conn, """
            SELECT (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY days_to_open) FROM v_backfill_cycle_time) AS median_days,
                   count(*) FILTER (WHERE status = 'submitted') AS waiting_vp,
                   count(*) FILTER (WHERE status IN ('vp_approved', 'recruiter_assigned')) AS waiting_recruiter,
                   count(*) FILTER (WHERE status = 'req_open') AS req_open,
                   count(*) FILTER (WHERE status = 'filled') AS filled
            FROM backfill_requests""")
        ctx.update(rows=rows, inbox=inbox, stats=stats, scope=scope, status=status, has_mine=bool(mine_col),
                   STATUS_LABELS=STATUS_LABELS, sort=sort if "sort" in request.query_params else None, dir=direction,
                   can_request=permissions.can_request_backfill(role))
    return web.render(request, "requests.html", ctx)


def _detail_context(request: Request, conn, request_id: int) -> dict:
    ctx = web.page_context(request, conn)
    r = db.one(conn, "SELECT * FROM v_backfill_requests WHERE id = %s", (request_id,))
    if r is None:
        raise HTTPException(404, "No such request")
    role, me = ctx["role"], ctx["me"]["id"]
    ctx.update(
        r=r, steps=STEPS, done=DONE[r["status"]],
        events=db.query(conn, """
            SELECT e.*, coalesce(a.full_name, 'Headcount Desk') AS actor_name
            FROM request_events e LEFT JOIN people a ON a.id = e.actor_id
            WHERE e.backfill_request_id = %s ORDER BY e.at, e.id""", (request_id,)),
        staffing=db.one(conn, "SELECT id, status, opened_at FROM staffing_requests WHERE backfill_request_id = %s", (request_id,)),
        vp_usable_open=usable_open_for(conn, r["vp_id"]),
        money=db.one(conn, """
            SELECT pc.annual_cost, b.pct_of_budget, b.state, b.variance
            FROM v_budget b LEFT JOIN v_position_cost pc ON pc.position_id = %s WHERE b.org_id = %s""", (r["position_id"], r["vp_id"])),
        can_approve=role == "vp" and r["status"] == "submitted" and r["vp_approver_id"] == me,
        can_open=role == "recruiter" and r["status"] == "recruiter_assigned" and r["recruiter_id"] == me,
        can_fill=role == "recruiter" and r["status"] == "req_open" and r["recruiter_id"] == me,
    )
    return ctx


@router.get("/requests/{request_id}", response_class=HTMLResponse, include_in_schema=False)
def request_detail(request: Request, request_id: int, flash: str | None = None):
    with db.get_conn() as conn:
        ctx = _detail_context(request, conn, request_id)
        ctx["flash"] = flash
    return web.render(request, "request_detail.html", ctx)


def _request_row(conn, request_id: int) -> dict:
    row = db.one(conn, "SELECT * FROM v_backfill_requests WHERE id = %s", (request_id,))
    if row is None:
        raise HTTPException(404, "No such request")
    return row


def _act(request: Request, request_id: int, action, card: bool):
    """Run one workflow action as the current persona, then re-render either
    the inbox card (HTMX, in place) or the detail page."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        try:
            message = action(conn, ctx["me"]["id"], ctx)
        except workflow.WorkflowError as error:
            conn.rollback()
            if card:
                return HTMLResponse(f'<p class="flash flash-bad" role="alert">{error}</p>', status_code=200)
            return RedirectResponse(f"/requests/{request_id}?flash={quote(str(error))}", status_code=303)
        if not card:
            return RedirectResponse(f"/requests/{request_id}?flash={quote(message)}", status_code=303)
        ctx.update(r=db.one(conn, "SELECT * FROM v_backfill_requests WHERE id = %s", (request_id,)), message=message)
        if ctx["role"] == "vp":
            ctx["remaining"] = db.one(conn, "SELECT count(*) AS n FROM backfill_requests WHERE status = 'submitted' AND vp_approver_id = %s", (ctx["me"]["id"],))["n"]
        else:
            ctx["remaining"] = db.one(conn, "SELECT count(*) AS n FROM backfill_requests WHERE status = 'recruiter_assigned' AND recruiter_id = %s", (ctx["me"]["id"],))["n"]
    return web.render(request, "_request_card_done.html", ctx)


@router.post("/requests/{request_id}/approve", include_in_schema=False)
def approve(request: Request, request_id: int):
    def action(conn, me, ctx):
        permissions.check_approve(ctx, _request_row(conn, request_id))
        recruiter = workflow.approve(conn, request_id, me)
        return f"Approved. {recruiter['full_name']} was assigned automatically."
    return _act(request, request_id, action, card="hx-request" in request.headers)


@router.post("/requests/{request_id}/reject", include_in_schema=False)
def reject(request: Request, request_id: int, reason: str = Form("")):
    def action(conn, me, ctx):
        permissions.check_approve(ctx, _request_row(conn, request_id))
        workflow.reject(conn, request_id, me, reason[:500])
        return "Rejected. The requester can see your reason."
    return _act(request, request_id, action, card="hx-request" in request.headers)


@router.post("/requests/{request_id}/open", include_in_schema=False)
def open_request(request: Request, request_id: int):
    def action(conn, me, ctx):
        permissions.check_recruit(ctx, _request_row(conn, request_id))
        workflow.open_request(conn, request_id, me)
        return "Staffing request opened. Nobody had to re-enter the role."
    return _act(request, request_id, action, card="hx-request" in request.headers)


@router.post("/requests/{request_id}/fill", include_in_schema=False)
def fill(request: Request, request_id: int, hire_name: str = Form("")):
    def action(conn, me, ctx):
        permissions.check_recruit(ctx, _request_row(conn, request_id))
        workflow.fill(conn, request_id, me, hire_name[:80])
        return f"Filled. {' '.join(hire_name.split())} now holds the seat."
    return _act(request, request_id, action, card=False)


# ── The request form ─────────────────────────────────────────────────────────

def _scope_org(ctx: dict) -> int:
    """People ask for backfills in their own org. The resource manager can pick anyone."""
    return permissions.backfill_scope(ctx)


@router.get("/backfill/new", response_class=HTMLResponse, include_in_schema=False)
def backfill_new(request: Request, person: int | None = None):
    if request.query_params.get("as") in web.ROLES:          # the "Try this" link arrives as a requester
        response = RedirectResponse("/backfill/new", status_code=303)
        response.set_cookie("role", request.query_params["as"], max_age=60 * 60 * 24 * 30, samesite="lax")
        return response
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        ctx["suggestions"] = db.query(conn, """
            SELECT k.* FROM v_backfill_candidates k JOIN v_org_closure c ON c.org_id = k.org_id
            WHERE c.ancestor_id = %s AND k.end_date >= today()
            ORDER BY k.end_date LIMIT 6""", (_scope_org(ctx),))
        ctx["scope_name"] = "Meridian Labs" if ctx["role"] == "rm" else ctx["me"]["org_name"]
        ctx["can_request"] = permissions.can_request_backfill(ctx["role"])
        ctx["selected"] = _preview(conn, person) if person else None
    return web.render(request, "backfill_new.html", ctx)


@router.get("/backfill/search", response_class=HTMLResponse, include_in_schema=False)
def backfill_search(request: Request, q: str = ""):
    q = q.strip()
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        ctx["q"] = q
        ctx["results"] = db.query(conn, """
            SELECT k.* FROM v_backfill_candidates k JOIN v_org_closure c ON c.org_id = k.org_id
            WHERE c.ancestor_id = %s AND k.full_name ILIKE %s
            ORDER BY k.full_name LIMIT 6""", (_scope_org(ctx), f"%{q}%")) if len(q) >= 2 else []
    return web.render(request, "_backfill_results.html", ctx)


def _preview(conn, person_id: int) -> dict | None:
    k = db.one(conn, "SELECT * FROM v_backfill_candidates WHERE person_id = %s", (person_id,))
    if k is None:
        return None
    k["vp_usable_open"] = usable_open_for(conn, k["vp_id"])
    k["budget"] = db.one(conn, "SELECT pct_of_budget, state FROM v_budget WHERE org_id = %s", (k["vp_id"],))
    k["annual_cost"] = db.one(conn, "SELECT annual_cost FROM v_position_cost WHERE position_id = %s", (k["position_id"],))["annual_cost"]
    k["cost"] = db.one(conn, """
        SELECT pl.approved_cost_usd / nullif(pl.approved_headcount, 0) AS per_head
        FROM plan_lines pl JOIN v_current_plan cp ON cp.id = pl.plan_version_id
        WHERE pl.org_id = %s AND pl.job_family = %s""", (k["org_id"], k["job_family"]))
    return k


@router.get("/backfill/preview", response_class=HTMLResponse, include_in_schema=False)
def backfill_preview(request: Request, person: int):
    """Step two of the form: everything we can infer about the seat, read-only."""
    with db.get_conn() as conn:
        selected = _preview(conn, person)
    if selected is None:
        raise HTTPException(404, "That person cannot be backfilled")
    return web.render(request, "_backfill_form.html", {"selected": selected})


@router.post("/backfill", include_in_schema=False)
def backfill_submit(request: Request, person: int = Form(...), justification: str = Form(""), urgency: str = Form("normal")):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        candidate = db.one(conn, "SELECT org_id FROM v_backfill_candidates WHERE person_id = %s", (person,))
        if candidate:
            permissions.check_request_backfill(conn, ctx, candidate["org_id"])
        if len(justification) > 500:
            return RedirectResponse(f"/backfill/new?person={person}&flash={quote('Keep the reason under 500 characters.')}", status_code=303)
        try:
            request_id = workflow.submit(conn, person, ctx["me"]["id"], justification,
                                         urgency if urgency in ("low", "normal", "urgent") else "normal")
        except workflow.WorkflowError as error:
            conn.rollback()
            return RedirectResponse(f"/backfill/new?person={person}&flash={quote(str(error))}", status_code=303)
    return RedirectResponse(f"/requests/{request_id}?flash={quote('Request submitted.')}", status_code=303)
