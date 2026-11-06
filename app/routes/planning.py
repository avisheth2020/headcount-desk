"""Planning: "What does each org need next year?" VP asks, SVP review, then lock into a new plan version."""

from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db, permissions, planning, web

router = APIRouter()
STEPS = ["Draft", "Submitted", "SVP review", "Approved"]
DONE = {"draft": 0, "sent_back": 0, "submitted": 2, "approved": 4}


def current_cycle(conn) -> dict:
    cycle = db.one(conn, """
        SELECT c.*, base.name AS base_plan_name, fy.starts_on, locked.name AS locked_plan_name, p.full_name AS locked_by_name
        FROM planning_cycles c
        JOIN plan_versions base ON base.id = c.base_plan_version_id
        JOIN fiscal_years fy ON fy.name = c.fiscal_year
        LEFT JOIN plan_versions locked ON locked.id = c.locked_plan_version_id
        LEFT JOIN people p ON p.id = c.locked_by
        ORDER BY c.id DESC LIMIT 1""")
    if cycle is None:
        raise HTTPException(404, "No planning cycle is open")
    return cycle


def submission(conn, submission_id: int) -> dict:
    row = db.one(conn, "SELECT * FROM v_plan_submissions WHERE id = %s", (submission_id,))
    if row is None:
        raise HTTPException(404, "No such plan")
    return row


@router.get("/planning", response_class=HTMLResponse, include_in_schema=False)
def planning_home(request: Request, flash: str | None = None, error: str | None = None):
    if request.query_params.get("as") in web.ROLES:           # the "Try this" link arrives as a VP
        response = RedirectResponse("/planning", status_code=303)
        response.set_cookie("role", request.query_params["as"], max_age=60 * 60 * 24 * 30, samesite="lax")
        return response
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        cycle = current_cycle(conn)
        role, me = ctx["role"], ctx["me"]
        scope = me["org_id"] if role == "svp" else None            # an SVP sees their own VPs first
        order, sort, direction = web.sorting(request, {
            "vp": "s.vp_name", "svp": "s.svp_name", "status": "s.status", "base": "s.base_headcount",
            "ask": "s.requested_change", "final": "s.final_change", "cost": "s.final_cost"}, "svp")
        rows = db.query(conn, f"""
            SELECT s.* FROM v_plan_submissions s WHERE s.cycle_id = %s
            ORDER BY (s.svp_org_id = %s) DESC, {order}, s.vp_name""", (cycle["id"], scope or 0))
        if request.query_params.get("format") == "csv":
            return web.csv_response("fy28-planning.csv", [
                ("SVP", "svp_name"), ("VP org", "vp_name"), ("Status", "status"), ("This year", "base_headcount"),
                ("Requested change", "requested_change"), ("Change that counts", "final_change"),
                ("Cost impact USD", "final_cost"), ("Next year", "proposed_headcount")], rows)
        envelopes = db.query(conn, "SELECT * FROM v_planning_envelopes WHERE cycle_id = %s ORDER BY svp_org_id", (cycle["id"],))
        waiting = [r for r in rows if r["status"] != "approved"]
        ctx.update(
            cycle=cycle, rows=rows, envelopes=envelopes, flash=flash, error=error, sort=sort, dir=direction,
            mine=next((r for r in rows if role == "vp" and r["vp_org_id"] == me["org_id"]), None),
            my_envelope=next((e for e in envelopes if e["svp_org_id"] == scope), None),
            waiting=waiting, can_lock=permissions.can_lock_plan(ctx) and cycle["status"] == "open",
            totals={"base": sum(r["base_headcount"] for r in rows), "final": sum(r["final_change"] for r in rows if r["status"] in ("submitted", "approved")),
                    "cost": sum(r["final_cost"] for r in rows if r["status"] in ("submitted", "approved"))},
            events=db.query(conn, """
                SELECT e.*, coalesce(a.full_name, 'Headcount Desk') AS actor_name, s.vp_name
                FROM planning_events e LEFT JOIN people a ON a.id = e.actor_id
                LEFT JOIN v_plan_submissions s ON s.id = e.submission_id
                WHERE e.cycle_id = %s ORDER BY e.at DESC, e.id DESC LIMIT 8""", (cycle["id"],)),
            locked_lines=db.query(conn, """
                SELECT o.name AS org_name, o.level, pl.job_family, pl.approved_headcount, pl.approved_cost_usd
                FROM plan_lines pl JOIN orgs o ON o.id = pl.org_id WHERE pl.plan_version_id = %s
                ORDER BY o.id, pl.job_family LIMIT 200""", (cycle["locked_plan_version_id"],)) if cycle["locked_plan_version_id"] else [],
        )
    return web.render(request, "planning.html", ctx)


def _detail(request: Request, conn, submission_id: int) -> dict:
    ctx = web.page_context(request, conn)
    sub = submission(conn, submission_id)
    cycle = current_cycle(conn)
    open_cycle = cycle["status"] == "open"
    ctx.update(
        sub=sub, cycle=cycle, steps=STEPS, done=DONE[sub["status"]],
        lines=db.query(conn, "SELECT * FROM v_plan_submission_lines WHERE submission_id = %s ORDER BY base_headcount DESC", (submission_id,)),
        envelope=db.one(conn, "SELECT * FROM v_planning_envelopes WHERE cycle_id = %s AND svp_org_id = %s", (sub["cycle_id"], sub["svp_org_id"])),
        events=db.query(conn, """
            SELECT e.*, coalesce(a.full_name, 'Headcount Desk') AS actor_name
            FROM planning_events e LEFT JOIN people a ON a.id = e.actor_id
            WHERE e.submission_id = %s ORDER BY e.at, e.id""", (submission_id,)),
        can_edit=open_cycle and permissions.can_edit_plan(ctx, sub),
        can_review=open_cycle and permissions.can_review_plan(ctx, sub) and sub["status"] == "submitted",
    )
    return ctx


@router.get("/planning/{submission_id}", response_class=HTMLResponse, include_in_schema=False)
def planning_detail(request: Request, submission_id: int, flash: str | None = None, error: str | None = None):
    with db.get_conn() as conn:
        ctx = _detail(request, conn, submission_id)
        ctx.update(flash=flash, error=error)
    return web.render(request, "planning_detail.html", ctx)


def _number(value: str) -> int:
    try:
        return int(str(value).strip().replace("+", "").replace("−", "-") or 0)
    except ValueError:
        raise planning.PlanningError("A change has to be a whole number, like 5 or -2")


@router.post("/planning/{submission_id}/save", response_class=HTMLResponse, include_in_schema=False)
async def planning_save(request: Request, submission_id: int):
    """Autosave as the VP (or the reviewing SVP) types. Returns the form with fresh totals, so the dollar impact is live."""
    form = await request.form()
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        sub = submission(conn, submission_id)
        editing, reviewing = permissions.can_edit_plan(ctx, sub), permissions.can_review_plan(ctx, sub)
        if not (editing or reviewing):
            permissions.forbid("Only the VP who owns this plan can edit it, and only their SVP can adjust it.")
        error = None
        try:
            for family in ("research", "eng", "ops", "g&a"):
                if editing and f"change_{family}" in form:
                    planning.save_line(conn, submission_id, family, _number(form[f"change_{family}"]), str(form.get(f"why_{family}", "")))
                elif reviewing and f"approved_{family}" in form:
                    planning.adjust(conn, submission_id, family, _number(form[f"approved_{family}"]))
        except planning.PlanningError as problem:
            conn.rollback()
            error = str(problem)
        ctx = _detail(request, conn, submission_id)
        ctx["error"] = error
    return web.render(request, "_planning_form.html", ctx)


def _act(request: Request, submission_id: int, check, action, done: str):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        sub = submission(conn, submission_id)
        if not check(ctx, sub):
            permissions.forbid("You cannot do that to this plan in your current role.")
        try:
            action(conn, ctx["me"]["id"])
        except planning.PlanningError as problem:
            conn.rollback()
            return RedirectResponse(f"/planning/{submission_id}?error={quote(str(problem))}", status_code=303)
    return RedirectResponse(f"/planning/{submission_id}?flash={quote(done)}", status_code=303)


@router.post("/planning/{submission_id}/submit", include_in_schema=False)
def planning_submit(request: Request, submission_id: int):
    return _act(request, submission_id, permissions.can_edit_plan,
                lambda conn, me: planning.submit(conn, submission_id, me), "Submitted. Your SVP has it now.")


@router.post("/planning/{submission_id}/approve", include_in_schema=False)
def planning_approve(request: Request, submission_id: int):
    return _act(request, submission_id, permissions.can_review_plan,
                lambda conn, me: planning.approve(conn, submission_id, me), "Approved.")


@router.post("/planning/{submission_id}/send-back", include_in_schema=False)
def planning_send_back(request: Request, submission_id: int, comment: str = Form("")):
    return _act(request, submission_id, permissions.can_review_plan,
                lambda conn, me: planning.send_back(conn, submission_id, me, comment), "Sent back with your comment.")


@router.post("/planning/lock", include_in_schema=False)
def planning_lock(request: Request, carry_over: str = Form("")):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        if not permissions.can_lock_plan(ctx):
            permissions.forbid("Only an SVP or the resource manager can lock the plan.")
        cycle = current_cycle(conn)
        try:
            planning.lock_cycle(conn, cycle["id"], ctx["me"]["id"], carry_over_unapproved=carry_over == "yes")
        except planning.PlanningError as problem:
            conn.rollback()
            return RedirectResponse(f"/planning?error={quote(str(problem))}", status_code=303)
    return RedirectResponse(f"/planning?flash={quote(cycle['fiscal_year'] + ' plan locked. It is a new plan version and takes effect when the year starts.')}", status_code=303)
