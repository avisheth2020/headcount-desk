"""The annual planning cycle.

A VP's submission moves through:

    draft ──► submitted ──► approved
                 │
                 └──► sent_back ──► submitted (again)

Then the cycle is locked, which writes a new plan_version for next year.

Same rule as backfills: `transition()` is the only code that changes a
submission's status, and it writes the audit row in the same transaction.
Nothing here commits; the caller owns the transaction.
"""

from app import db

ALLOWED = {
    "draft": {"submitted"},
    "submitted": {"approved", "sent_back"},
    "sent_back": {"submitted"},
    "approved": set(),
}
MAX_CHANGE = 500


class PlanningError(Exception):
    """A move the planning cycle does not allow."""


def _open_submission(conn, submission_id: int) -> dict:
    row = db.one(conn, """
        SELECT s.*, c.status AS cycle_status FROM plan_submissions s
        JOIN planning_cycles c ON c.id = s.cycle_id WHERE s.id = %s FOR UPDATE OF s""", (submission_id,))
    if row is None:
        raise PlanningError(f"Submission {submission_id} does not exist")
    if row["cycle_status"] == "locked":
        raise PlanningError("This planning cycle is locked. Changes now need a new plan version.")
    return row


def transition(conn, submission_id: int, to_status: str, actor_id: int | None, note: str | None = None) -> dict:
    row = _open_submission(conn, submission_id)
    if to_status not in ALLOWED[row["status"]]:
        raise PlanningError(f"A plan that is {row['status'].replace('_', ' ')} cannot become {to_status.replace('_', ' ')}")
    conn.execute("UPDATE plan_submissions SET status = %s, updated_at = now() WHERE id = %s", (to_status, submission_id))
    conn.execute("""
        INSERT INTO planning_events (cycle_id, submission_id, from_status, to_status, actor_id, note)
        VALUES (%s, %s, %s, %s, %s, %s)""", (row["cycle_id"], submission_id, row["status"], to_status, actor_id, note))
    return {**row, "status": to_status}


def _check_change(change: int, base: int) -> None:
    if abs(change) > MAX_CHANGE:
        raise PlanningError(f"A change has to be between −{MAX_CHANGE} and +{MAX_CHANGE}")
    if base + change < 0:
        raise PlanningError(f"You cannot cut more than the {base} positions this job family has")


def save_line(conn, submission_id: int, job_family: str, change: int, justification: str) -> None:
    """The VP edits their ask. Only while it is a draft or has been sent back."""
    row = _open_submission(conn, submission_id)
    if row["status"] not in ("draft", "sent_back"):
        raise PlanningError("This plan has been submitted. It can be edited again if the SVP sends it back.")
    line = db.one(conn, "SELECT base_headcount FROM plan_submission_lines WHERE submission_id = %s AND job_family = %s",
                  (submission_id, job_family))
    if line is None:
        raise PlanningError("That job family is not part of this plan")
    _check_change(change, line["base_headcount"])
    conn.execute("""
        UPDATE plan_submission_lines SET requested_change = %s, approved_change = NULL, justification = %s
        WHERE submission_id = %s AND job_family = %s""", (change, justification.strip()[:300], submission_id, job_family))


def submit(conn, submission_id: int, vp_id: int) -> None:
    missing = db.one(conn, """
        SELECT count(*) AS n FROM plan_submission_lines
        WHERE submission_id = %s AND requested_change <> 0 AND btrim(justification) = ''""", (submission_id,))["n"]
    if missing:
        raise PlanningError("Every change needs a reason before you submit")
    total = db.one(conn, "SELECT requested_change FROM v_plan_submissions WHERE id = %s", (submission_id,))
    transition(conn, submission_id, "submitted", vp_id,
               f"Asked for {total['requested_change']:+d} positions" if total else None)


def adjust(conn, submission_id: int, job_family: str, approved_change: int) -> None:
    """The SVP sets the number they are willing to approve for one job family."""
    row = _open_submission(conn, submission_id)
    if row["status"] != "submitted":
        raise PlanningError("Only a submitted plan can be adjusted")
    line = db.one(conn, "SELECT base_headcount FROM plan_submission_lines WHERE submission_id = %s AND job_family = %s",
                  (submission_id, job_family))
    if line is None:
        raise PlanningError("That job family is not part of this plan")
    _check_change(approved_change, line["base_headcount"])
    conn.execute("UPDATE plan_submission_lines SET approved_change = %s WHERE submission_id = %s AND job_family = %s",
                 (approved_change, submission_id, job_family))


def approve(conn, submission_id: int, svp_id: int) -> None:
    totals = db.one(conn, "SELECT requested_change, final_change FROM v_plan_submissions WHERE id = %s", (submission_id,))
    note = "Approved as requested" if totals and totals["requested_change"] == totals["final_change"] \
        else f"Approved {totals['final_change']:+d} of the {totals['requested_change']:+d} requested" if totals else None
    transition(conn, submission_id, "approved", svp_id, note)


def send_back(conn, submission_id: int, svp_id: int, comment: str) -> None:
    if not comment or not comment.strip():
        raise PlanningError("Say what needs to change before sending a plan back")
    transition(conn, submission_id, "sent_back", svp_id, comment.strip()[:500])


def lock_cycle(conn, cycle_id: int, actor_id: int, carry_over_unapproved: bool = False) -> int:
    """Lock the cycle and write next year's plan as a new plan_version.

    Approved asks are applied. A VP org that is not approved yet either blocks
    the lock or, if `carry_over_unapproved` is set, keeps this year's numbers.
    The new plan is at VP level; splitting it down to teams happens after lock.
    """
    cycle = db.one(conn, "SELECT * FROM planning_cycles WHERE id = %s FOR UPDATE", (cycle_id,))
    if cycle is None:
        raise PlanningError("No such planning cycle")
    if cycle["status"] == "locked":
        raise PlanningError("This planning cycle is already locked")
    waiting = db.query(conn, "SELECT vp_name FROM v_plan_submissions WHERE cycle_id = %s AND status <> 'approved' ORDER BY vp_name", (cycle_id,))
    if waiting and not carry_over_unapproved:
        raise PlanningError(f"{len(waiting)} VP plans are not approved yet: {', '.join(w['vp_name'] for w in waiting)}")
    year = db.one(conn, "SELECT name, starts_on FROM fiscal_years WHERE name = %s", (cycle["fiscal_year"],))
    version_id = db.one(conn, """
        INSERT INTO plan_versions (name, fiscal_year, effective_from) VALUES (%s, %s, %s) RETURNING id""",
        (f"{year['name']} Plan", year["name"], year["starts_on"]))["id"]
    # Each VP org: this year plus the approved change (nothing for a plan that was not approved).
    conn.execute("""
        INSERT INTO plan_lines (plan_version_id, org_id, job_family, approved_headcount, approved_cost_usd)
        SELECT %s, s.vp_org_id, l.job_family,
               l.base_headcount + CASE WHEN s.status = 'approved' THEN l.final_change ELSE 0 END,
               l.base_cost_usd  + CASE WHEN s.status = 'approved' THEN l.final_cost   ELSE 0 END
        FROM plan_submissions s JOIN v_plan_submission_lines l ON l.submission_id = s.id
        WHERE s.cycle_id = %s""", (version_id, cycle_id))
    # Everything above VP level (leadership seats and central reserve) carries over unchanged.
    conn.execute("""
        INSERT INTO plan_lines (plan_version_id, org_id, job_family, approved_headcount, approved_cost_usd)
        SELECT %s, pl.org_id, pl.job_family, pl.approved_headcount, pl.approved_cost_usd
        FROM plan_lines pl JOIN orgs o ON o.id = pl.org_id
        WHERE pl.plan_version_id = %s AND o.level IN ('company', 'svp')""", (version_id, cycle["base_plan_version_id"]))
    conn.execute("UPDATE plan_versions SET locked_at = now(), locked_by = %s, content_hash = plan_hash(id) WHERE id = %s",
                 (actor_id, version_id))
    conn.execute("""
        UPDATE planning_cycles SET status = 'locked', locked_plan_version_id = %s, locked_at = now(), locked_by = %s
        WHERE id = %s""", (version_id, actor_id, cycle_id))
    note = "Locked with every VP plan approved" if not waiting else \
        f"Locked with {len(waiting)} VP plans not approved; they carry this year's numbers: {', '.join(w['vp_name'] for w in waiting)}"
    conn.execute("""
        INSERT INTO planning_events (cycle_id, submission_id, from_status, to_status, actor_id, note)
        VALUES (%s, NULL, 'open', 'locked', %s, %s)""", (cycle_id, actor_id, note))
    return version_id
