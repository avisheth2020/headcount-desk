"""A small read-only JSON API over the same SQL views the pages use.
FastAPI documents it automatically at /docs."""

from fastapi import APIRouter, HTTPException, Query

from app import db
from app.checks import CHECKS

router = APIRouter(prefix="/api", tags=["API"])


@router.get("/usable-open", summary="Usable open headcount for an org and the orgs directly below it")
def usable_open(org_id: int = Query(1, description="Org id. 1 is the whole company.")):
    with db.get_conn() as conn:
        org = db.one(conn, "SELECT * FROM v_usable_open WHERE org_id = %s", (org_id,))
        if org is None:
            raise HTTPException(404, "No such org")
        children = db.query(conn, "SELECT * FROM v_usable_open WHERE parent_id = %s ORDER BY name", (org_id,))
    return {"formula": "usable_open = approved - filled - committed - reserve - negative", "org": org, "children": children}


@router.get("/exceptions", summary="Open data exceptions, oldest first")
def exceptions(exception_type: str | None = Query(None, description="stale_open, duplicate, ghost_fill, miscoded or reserve_misplaced"),
               limit: int = Query(50, ge=1, le=500)):
    with db.get_conn() as conn:
        rows = db.query(conn, """
            SELECT exception_type, type_label, position_code, org_name, owner_name, detail, suggested_fix, age_days
            FROM v_exceptions
            WHERE NOT is_resolved AND (%(type)s::text IS NULL OR exception_type = %(type)s)
            ORDER BY age_days DESC NULLS LAST, position_code LIMIT %(limit)s""", {"type": exception_type, "limit": limit})
    return {"count": len(rows), "exceptions": rows}


@router.get("/requests", summary="Backfill requests and where each one is")
def requests(status: str | None = Query(None, description="submitted, recruiter_assigned, req_open, filled or rejected")):
    with db.get_conn() as conn:
        rows = db.query(conn, """
            SELECT id, status, urgency, departing_name, position_code, team_name, vp_name, requester_name,
                   approver_name, recruiter_name, waiting_on, created_at, updated_at
            FROM v_backfill_requests
            WHERE (%(status)s::text IS NULL OR status = %(status)s) ORDER BY updated_at DESC""", {"status": status})
    return {"count": len(rows), "requests": rows}


@router.get("/requests/{request_id}/events", summary="The audit trail for one backfill request")
def request_events(request_id: int):
    with db.get_conn() as conn:
        rows = db.query(conn, """
            SELECT e.at, e.from_status, e.to_status, coalesce(a.full_name, 'system') AS actor, e.note
            FROM request_events e LEFT JOIN people a ON a.id = e.actor_id
            WHERE e.backfill_request_id = %s ORDER BY e.at, e.id""", (request_id,))
    if not rows:
        raise HTTPException(404, "No such request")
    return {"request_id": request_id, "events": rows}


@router.get("/checks/latest", summary="The latest data check run and anything that did not pass")
def latest_checks():
    with db.get_conn() as conn:
        run = db.one(conn, "SELECT id, run_at, passed, warned, failed FROM check_runs ORDER BY run_at DESC, id DESC LIMIT 1")
        findings = db.query(conn, """
            SELECT check_name, severity, expected, actual, message FROM check_results
            WHERE check_run_id = %s AND severity <> 'pass' ORDER BY id""", (run["id"],))
    return {"run": run, "checks": {name: title for name, (title, _) in CHECKS.items()}, "findings": findings}
