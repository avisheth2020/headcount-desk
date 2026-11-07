"""The annual planning cycle: VP asks, SVP review, lock into a new plan version."""

import psycopg
import pytest

from app import db, planning
from tests.conftest import Client


def sub(conn, status, **where):
    extra = "".join(f" AND {k} = %({k})s" for k in where)
    return db.one(conn, f"SELECT * FROM v_plan_submissions WHERE status = %(status)s{extra} ORDER BY id LIMIT 1", {"status": status, **where})


def trail(conn, submission_id):
    rows = db.query(conn, "SELECT from_status, to_status FROM planning_events WHERE submission_id = %s ORDER BY at, id", (submission_id,))
    return [(r["from_status"], r["to_status"]) for r in rows]


def test_seeded_mid_cycle(seeded_db):
    """The demo SVP's org is mid-cycle; the demo VP still has a draft."""
    counts = {r["status"]: r["n"] for r in db.query(seeded_db, "SELECT status, count(*) AS n FROM plan_submissions GROUP BY status")}
    assert counts == {"draft": 1, "submitted": 2, "sent_back": 1, "approved": 8}
    draft = sub(seeded_db, "draft")
    assert draft["vp_leader_id"] == db.one(seeded_db, "SELECT value::int AS id FROM app_meta WHERE key = 'persona_vp'")["id"]
    for s in db.query(seeded_db, "SELECT id, status FROM plan_submissions"):
        assert trail(seeded_db, s["id"])[-1][1] == s["status"]


def test_base_matches_this_years_plan(seeded_db):
    """Every VP starts from the current plan: the base equals approved headcount for their org."""
    bad = db.query(seeded_db, """
        SELECT s.vp_name FROM v_plan_submissions s JOIN v_usable_open u ON u.org_id = s.vp_org_id
        WHERE s.base_headcount <> u.approved""")
    assert bad == []


def test_vp_edits_submits_and_svp_approves(seeded_db):
    c = seeded_db
    draft = sub(c, "draft")
    line = db.one(c, "SELECT * FROM v_plan_submission_lines WHERE submission_id = %s ORDER BY base_headcount DESC LIMIT 1", (draft["id"],))
    planning.save_line(c, draft["id"], line["job_family"], 10, "")
    with pytest.raises(planning.PlanningError, match="needs a reason"):
        planning.submit(c, draft["id"], draft["vp_leader_id"])
    planning.save_line(c, draft["id"], line["job_family"], 10, "Two new pods")
    after = db.one(c, "SELECT * FROM v_plan_submission_lines WHERE submission_id = %s AND job_family = %s", (draft["id"], line["job_family"]))
    assert abs(after["requested_cost"] - 10 * line["cost_per_head"]) < 1         # the live dollar impact
    planning.submit(c, draft["id"], draft["vp_leader_id"])
    with pytest.raises(planning.PlanningError, match="submitted"):                # locked for the VP once submitted
        planning.save_line(c, draft["id"], line["job_family"], 99, "More")

    planning.adjust(c, draft["id"], line["job_family"], 6)                        # the SVP approves fewer
    planning.approve(c, draft["id"], draft["svp_leader_id"])
    done = db.one(c, "SELECT * FROM v_plan_submissions WHERE id = %s", (draft["id"],))
    assert done["status"] == "approved" and done["final_change"] == done["requested_change"] - 4
    assert trail(c, draft["id"]) == [(None, "draft"), ("draft", "submitted"), ("submitted", "approved")]


def test_send_back_needs_a_comment_and_reopens_editing(seeded_db):
    c = seeded_db
    s = sub(c, "submitted")
    with pytest.raises(planning.PlanningError, match="what needs to change"):
        planning.send_back(c, s["id"], s["svp_leader_id"], "  ")
    planning.send_back(c, s["id"], s["svp_leader_id"], "Too many")
    line = db.one(c, "SELECT job_family FROM plan_submission_lines WHERE submission_id = %s LIMIT 1", (s["id"],))
    planning.save_line(c, s["id"], line["job_family"], 1, "Trimmed")              # editable again
    planning.submit(c, s["id"], s["vp_leader_id"])
    assert trail(c, s["id"])[-2:] == [("submitted", "sent_back"), ("sent_back", "submitted")]


@pytest.mark.parametrize("status,to_status", [("draft", "approved"), ("approved", "submitted"), ("sent_back", "approved")])
def test_cannot_skip_steps(seeded_db, status, to_status):
    s = sub(seeded_db, status)
    with pytest.raises(planning.PlanningError, match="cannot become"):
        planning.transition(seeded_db, s["id"], to_status, s["svp_leader_id"])


def test_cannot_cut_below_zero(seeded_db):
    draft = sub(seeded_db, "draft")
    line = db.one(seeded_db, "SELECT job_family, base_headcount FROM plan_submission_lines WHERE submission_id = %s LIMIT 1", (draft["id"],))
    with pytest.raises(planning.PlanningError, match="cannot cut more"):
        planning.save_line(seeded_db, draft["id"], line["job_family"], -(line["base_headcount"] + 1), "Too deep")


def test_envelope_counts_only_asks_that_are_on_the_table(seeded_db):
    e = db.one(seeded_db, "SELECT * FROM v_planning_envelopes WHERE n_draft = 1")
    on_table = db.one(seeded_db, """
        SELECT coalesce(sum(final_change), 0) AS n FROM v_plan_submissions
        WHERE svp_org_id = %s AND status IN ('submitted', 'approved')""", (e["svp_org_id"],))["n"]
    assert e["asked_headcount"] == on_table
    assert e["headcount_headroom"] == e["headcount_envelope"] - e["base_headcount"] - on_table


def test_lock_is_blocked_until_approved_or_explicitly_carried_over(seeded_db):
    c = seeded_db
    cycle = db.one(c, "SELECT id FROM planning_cycles")["id"]
    with pytest.raises(planning.PlanningError, match="4 VP plans are not approved"):
        planning.lock_cycle(c, cycle, actor_id=1)

    current_before = db.one(c, "SELECT id, name FROM v_current_plan")
    usable_before = db.one(c, "SELECT usable_open FROM v_usable_open WHERE org_id = 1")["usable_open"]
    version = planning.lock_cycle(c, cycle, actor_id=1, carry_over_unapproved=True)

    plan = db.one(c, "SELECT *, plan_hash(id) AS now_hash FROM plan_versions WHERE id = %s", (version,))
    assert plan["name"] == "FY28 Plan" and plan["locked_at"] and plan["content_hash"] == plan["now_hash"]
    # Approved asks are in; unapproved orgs carry this year's numbers.
    expected = db.one(c, """
        SELECT sum(base_headcount + CASE WHEN status = 'approved' THEN final_change ELSE 0 END) AS n FROM v_plan_submissions""")["n"]
    vp_lines = db.one(c, """
        SELECT sum(pl.approved_headcount) AS n FROM plan_lines pl JOIN orgs o ON o.id = pl.org_id
        WHERE pl.plan_version_id = %s AND o.level = 'vp'""", (version,))["n"]
    assert vp_lines == expected
    # Next year's plan does not change this year's numbers.
    assert db.one(c, "SELECT id, name FROM v_current_plan") == current_before
    assert db.one(c, "SELECT usable_open FROM v_usable_open WHERE org_id = 1")["usable_open"] == usable_before
    # The new plan is locked like any other, and the cycle is closed.
    with pytest.raises(psycopg.errors.RaiseException, match="locked"):
        with c.transaction():                                                     # a savepoint, so the test can carry on
            c.execute("UPDATE plan_lines SET approved_headcount = 1 WHERE plan_version_id = %s", (version,))
    draft = db.one(c, "SELECT id, vp_leader_id FROM v_plan_submissions WHERE status = 'draft'")
    with pytest.raises(planning.PlanningError, match="locked"):
        planning.submit(c, draft["id"], draft["vp_leader_id"])
    assert db.one(c, "SELECT to_status, note FROM planning_events WHERE submission_id IS NULL")["to_status"] == "locked"
    assert db.one(c, "SELECT severity FROM v_check_plan_integrity WHERE message LIKE 'FY28 Plan%%'")["severity"] == "pass"


def test_planning_audit_trail_cannot_be_edited(seeded_db):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded_db.execute("UPDATE planning_events SET note = 'rewritten' WHERE id = (SELECT min(id) FROM planning_events)")


def test_try_this_link_switches_role(manifest):
    from app.main import app
    with Client(app) as client:
        arrive = client.get("/planning?as=vp", follow_redirects=False)
        assert arrive.status_code == 303 and arrive.headers["location"] == "/planning" and "role=vp" in arrive.headers["set-cookie"]
        assert "Edit your plan" in client.get("/planning").text


def test_planning_pages_and_permissions(manifest):
    from app.main import app
    with db.get_conn() as conn:
        draft, submitted, other = sub(conn, "draft"), sub(conn, "submitted"), sub(conn, "approved")
    with Client(app) as client:
        for role in ("svp", "vp", "requester", "recruiter", "rm"):
            client.cookies.set("role", role)
            assert client.get("/planning").status_code == 200
            assert client.get(f"/planning/{draft['id']}").status_code == 200
        assert client.get("/planning?format=csv").headers["content-type"].startswith("text/csv")

        client.cookies.set("role", "requester")                    # only the owning VP edits
        assert client.post(f"/planning/{draft['id']}/save", data={"change_research": "5"}).status_code == 403
        assert client.post(f"/planning/{draft['id']}/submit", follow_redirects=False).status_code == 403
        assert client.post("/planning/lock", data={"carry_over": "yes"}, follow_redirects=False).status_code == 403
        client.cookies.set("role", "vp")                           # a VP cannot approve, and cannot edit another VP's plan
        assert client.post(f"/planning/{submitted['id']}/approve", follow_redirects=False).status_code == 403
        assert client.post(f"/planning/{other['id']}/save", data={"change_eng": "5"}).status_code == 403
        saved = client.post(f"/planning/{draft['id']}/save", data={"change_research": "13", "why_research": "Pods"})
        assert saved.status_code == 200 and 'value="13"' in saved.text
        bad = client.post(f"/planning/{draft['id']}/save", data={"change_research": "lots"})
        assert bad.status_code == 200 and "whole number" in bad.text
        client.cookies.set("role", "svp")                          # the SVP reviews only their own VPs
        assert client.post(f"/planning/{other['id']}/send-back", data={"comment": "no"}, follow_redirects=False).status_code == 403
    from scripts.seed import seed
    from tests.conftest import SEEDED_SCHEMA, TEST_URL
    with db.connect(TEST_URL, schema=SEEDED_SCHEMA) as conn:       # undo the saved edit
        seed(conn)


def test_room_to_grow_counts_only_submitted_and_approved():
    from app.routes.planning import room_to_grow
    envelope = {"svp_org_id": 2, "headcount_headroom": 62}
    rows = [{"id": 1, "svp_org_id": 2, "status": "draft", "final_change": 16},
            {"id": 2, "svp_org_id": 2, "status": "submitted", "final_change": 24},
            {"id": 3, "svp_org_id": 2, "status": "sent_back", "final_change": 78},
            {"id": 4, "svp_org_id": 9, "status": "approved", "final_change": 500}]
    use = room_to_grow(envelope, rows)
    assert (use["room"], use["left"], use["submitted"], use["draft"], use["sent_back"]) == (86, 62, 24, 16, 78)
    assert room_to_grow(envelope, rows, leave_out=1)["draft"] == 0
    assert room_to_grow(envelope, rows, leave_out=2)["left"] == 86           # your own ask is shown separately
