"""Who may do what. Identities are simulated (a cookie picks the role), but
every rule is checked on the server, so hiding a button is never the only guard."""

from fastapi import HTTPException

from app import db


def forbid(message: str):
    raise HTTPException(403, message)


def in_org(conn, org_id: int, ancestor_id: int) -> bool:
    """True if org_id is ancestor_id or sits anywhere below it."""
    return db.one(conn, "SELECT 1 AS yes FROM v_org_closure WHERE ancestor_id = %s AND org_id = %s",
                  (ancestor_id, org_id)) is not None


def can_request_backfill(role: str) -> bool:
    return role in ("requester", "vp", "svp", "rm")


def backfill_scope(ctx: dict) -> int:
    """The org a person may request backfills in: their own, or the whole company for the resource manager."""
    return 1 if ctx["role"] == "rm" else ctx["me"]["org_id"]


def check_request_backfill(conn, ctx: dict, seat_org_id: int) -> None:
    if not can_request_backfill(ctx["role"]):
        forbid("Recruiters cannot request a backfill.")
    if not in_org(conn, seat_org_id, backfill_scope(ctx)):
        forbid("You can only request a backfill for a seat in your own org.")


def check_approve(ctx: dict, request_row: dict) -> None:
    if ctx["role"] != "vp" or request_row["vp_approver_id"] != ctx["me"]["id"]:
        forbid(f"Only {request_row['approver_name']}, the VP over this seat, can approve or reject it.")


def check_recruit(ctx: dict, request_row: dict) -> None:
    if ctx["role"] != "recruiter" or request_row["recruiter_id"] != ctx["me"]["id"]:
        forbid("Only the recruiter assigned to this request can move it forward.")


def can_resolve_exceptions(role: str) -> bool:
    return role in ("rm", "vp", "svp")


def check_resolve_exception(conn, ctx: dict, seat_org_id: int) -> None:
    if not can_resolve_exceptions(ctx["role"]):
        forbid("Only a resource manager, or the VP or SVP who owns the seat, can resolve an exception.")
    if ctx["role"] != "rm" and not in_org(conn, seat_org_id, ctx["me"]["org_id"]):
        forbid("You can only resolve exceptions in your own org.")


def check_run_checks(ctx: dict) -> None:
    if ctx["role"] != "rm":
        forbid("Only a resource manager can run the data checks.")


def can_edit_plan(ctx: dict, submission: dict) -> bool:
    return (ctx["role"] == "vp" and submission["vp_org_id"] == ctx["me"]["org_id"]
            and submission["status"] in ("draft", "sent_back"))


def can_review_plan(ctx: dict, submission: dict) -> bool:
    return ctx["role"] == "svp" and submission["svp_org_id"] == ctx["me"]["org_id"]


def can_lock_plan(ctx: dict) -> bool:
    return ctx["role"] in ("svp", "rm")
