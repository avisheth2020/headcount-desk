"""The backfill workflow.

A request moves through a fixed set of statuses:

    submitted ──► vp_approved ──► recruiter_assigned ──► req_open ──► filled
        └──► rejected

`transition()` is the only code that changes a request's status. It checks the
move is legal and writes the audit row in the same transaction, so a status
can never change without a record of who did it and when.

Nothing here commits. The caller owns the transaction.
"""

from app import db

ALLOWED = {
    "submitted": {"vp_approved", "rejected"},
    "vp_approved": {"recruiter_assigned"},
    "recruiter_assigned": {"req_open"},
    "req_open": {"filled"},
    "rejected": set(),     # terminal
    "filled": set(),       # terminal
}


class WorkflowError(Exception):
    """A move the workflow does not allow."""


def transition(conn, request_id: int, to_status: str, actor_id: int | None, note: str | None = None) -> dict:
    """Move a request to a new status and record it. `actor_id` None means the system did it."""
    row = db.one(conn, "SELECT * FROM backfill_requests WHERE id = %s FOR UPDATE", (request_id,))
    if row is None:
        raise WorkflowError(f"Request {request_id} does not exist")
    if to_status not in ALLOWED[row["status"]]:
        raise WorkflowError(f"Request {request_id} cannot go from {row['status']} to {to_status}")
    conn.execute("UPDATE backfill_requests SET status = %s, updated_at = now() WHERE id = %s", (to_status, request_id))
    conn.execute("""
        INSERT INTO request_events (backfill_request_id, from_status, to_status, actor_id, note)
        VALUES (%s, %s, %s, %s, %s)""", (request_id, row["status"], to_status, actor_id, note))
    return {**row, "status": to_status}


def submit(conn, departing_person_id: int, requested_by: int, justification: str, urgency: str = "normal") -> int:
    """Create a request. The seat and the approving VP are looked up, not typed in."""
    if not justification.strip():
        raise WorkflowError("Say why the backfill is needed")
    candidate = db.one(conn, "SELECT * FROM v_backfill_candidates WHERE person_id = %s", (departing_person_id,))
    if candidate is None:
        raise WorkflowError("That person is not leaving, has no seat, or already has a backfill in progress")
    request_id = db.one(conn, """
        INSERT INTO backfill_requests (departing_person_id, position_id, requested_by, justification, urgency, vp_approver_id)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (departing_person_id, candidate["position_id"], requested_by, justification.strip(), urgency,
         candidate["vp_approver_id"]))["id"]
    conn.execute("""
        INSERT INTO request_events (backfill_request_id, from_status, to_status, actor_id, note)
        VALUES (%s, NULL, 'submitted', %s, %s)""", (request_id, requested_by, justification.strip()))
    return request_id


def approve(conn, request_id: int, vp_id: int, note: str | None = None) -> dict:
    """VP approves. A recruiter is assigned automatically, in the same transaction."""
    transition(conn, request_id, "vp_approved", vp_id, note or "Approved")
    family = db.one(conn, """
        SELECT p.job_family FROM backfill_requests b JOIN positions p ON p.id = b.position_id
        WHERE b.id = %s""", (request_id,))["job_family"]
    recruiter = db.one(conn, """
        SELECT person_id, full_name FROM v_recruiter_load
        WHERE job_family = %s ORDER BY load, person_id LIMIT 1""", (family,))
    if recruiter is None:
        raise WorkflowError(f"No recruiter covers {family}")
    conn.execute("UPDATE backfill_requests SET recruiter_id = %s WHERE id = %s", (recruiter["person_id"], request_id))
    transition(conn, request_id, "recruiter_assigned", None,
               f"Auto-assigned to {recruiter['full_name']} (least-loaded {family} recruiter)")
    return recruiter


def reject(conn, request_id: int, vp_id: int, reason: str) -> None:
    if not reason or not reason.strip():
        raise WorkflowError("A rejection needs a reason")
    transition(conn, request_id, "rejected", vp_id, reason.strip())


def open_request(conn, request_id: int, recruiter_id: int) -> int:
    """Recruiter starts work. The staffing request is created here, so nobody
    re-types the role into the position tool."""
    row = transition(conn, request_id, "req_open", recruiter_id, "Staffing request opened automatically")
    # If the person has already left, the seat is really empty: vacate it.
    conn.execute("""
        UPDATE positions SET person_id = NULL, opened_at = today()
        WHERE id = %s AND person_id IN (SELECT id FROM people WHERE end_date < today())""", (row["position_id"],))
    return db.one(conn, """
        INSERT INTO staffing_requests (position_id, recruiter_id, status, backfill_request_id, opened_at)
        VALUES (%s, %s, 'open', %s, today()) RETURNING id""", (row["position_id"], recruiter_id, request_id))["id"]


def fill(conn, request_id: int, recruiter_id: int, hire_name: str) -> int:
    """Offer accepted. The new person takes the seat and the staffing request closes."""
    hire_name = " ".join(hire_name.split())
    if not hire_name:
        raise WorkflowError("Enter the new hire's name")
    row = transition(conn, request_id, "filled", recruiter_id, f"Offer accepted by {hire_name}")
    seat = db.one(conn, """
        SELECT p.org_id, p.job_family, p.level, o.leader_person_id
        FROM positions p JOIN orgs o ON o.id = p.org_id WHERE p.id = %s""", (row["position_id"],))
    person_id = db.one(conn, """
        INSERT INTO people (full_name, email, org_id, job_family, level, location, start_date, manager_id)
        VALUES (%s, 'new.hire.' || nextval(pg_get_serial_sequence('people', 'id')) || '@meridianlabs.example',
                %s, %s, %s, 'Remote', today() + 14, %s)
        RETURNING id""", (hire_name, seat["org_id"], seat["job_family"], seat["level"], seat["leader_person_id"]))["id"]
    conn.execute("UPDATE positions SET person_id = %s, source = 'backfill' WHERE id = %s", (person_id, row["position_id"]))
    conn.execute("UPDATE staffing_requests SET status = 'filled', closed_at = today() WHERE backfill_request_id = %s",
                 (request_id,))
    return person_id
