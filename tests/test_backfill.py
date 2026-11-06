"""The backfill workflow: the happy path, rejection, and moves that are not allowed."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import db, workflow


@pytest.fixture()
def candidate(seeded_db):
    """Someone who is leaving, still holds a seat, and has no backfill yet."""
    return db.one(seeded_db, "SELECT * FROM v_backfill_candidates WHERE end_date > today() ORDER BY person_id LIMIT 1")


def status(conn, request_id):
    return db.one(conn, "SELECT status FROM backfill_requests WHERE id = %s", (request_id,))["status"]


def trail(conn, request_id):
    rows = db.query(conn, "SELECT from_status, to_status FROM request_events WHERE backfill_request_id = %s ORDER BY id", (request_id,))
    return [(r["from_status"], r["to_status"]) for r in rows]


def test_happy_path(seeded_db, candidate):
    c = seeded_db
    usable_before = db.one(c, "SELECT usable_open FROM v_usable_open WHERE org_id = %s", (candidate["vp_id"],))["usable_open"]

    request_id = workflow.submit(c, candidate["person_id"], requested_by=1, justification="Needed", urgency="urgent")
    assert status(c, request_id) == "submitted"

    recruiter = workflow.approve(c, request_id, candidate["vp_approver_id"])
    assert status(c, request_id) == "recruiter_assigned"          # approval and assignment happen together
    covers = db.one(c, "SELECT job_family FROM recruiter_coverage WHERE person_id = %s", (recruiter["person_id"],))
    seat = db.one(c, "SELECT job_family FROM positions WHERE id = %s", (candidate["position_id"],))
    assert covers["job_family"] == seat["job_family"]

    staffing_id = workflow.open_request(c, request_id, recruiter["person_id"])
    created = db.one(c, "SELECT * FROM staffing_requests WHERE id = %s", (staffing_id,))
    assert created["position_id"] == candidate["position_id"] and created["status"] == "open"
    assert created["backfill_request_id"] == request_id          # nobody typed this in

    hire_id = workflow.fill(c, request_id, recruiter["person_id"], "Robin  Okafor")
    assert status(c, request_id) == "filled"
    seat = db.one(c, "SELECT person_id FROM positions WHERE id = %s", (candidate["position_id"],))
    assert seat["person_id"] == hire_id
    assert db.one(c, "SELECT status FROM staffing_requests WHERE id = %s", (staffing_id,))["status"] == "filled"

    assert trail(c, request_id) == [
        (None, "submitted"), ("submitted", "vp_approved"), ("vp_approved", "recruiter_assigned"),
        ("recruiter_assigned", "req_open"), ("req_open", "filled")]
    usable_after = db.one(c, "SELECT usable_open FROM v_usable_open WHERE org_id = %s", (candidate["vp_id"],))["usable_open"]
    assert usable_after == usable_before                          # a backfill reuses the seat


def test_auto_assignment_picks_the_least_loaded_recruiter(seeded_db, candidate):
    c = seeded_db
    family = db.one(c, "SELECT job_family FROM positions WHERE id = %s", (candidate["position_id"],))["job_family"]
    expected = db.one(c, "SELECT person_id FROM v_recruiter_load WHERE job_family = %s ORDER BY load, person_id LIMIT 1", (family,))
    request_id = workflow.submit(c, candidate["person_id"], 1, "Needed")
    assert workflow.approve(c, request_id, candidate["vp_approver_id"])["person_id"] == expected["person_id"]


def test_rejection_needs_a_reason_and_is_final(seeded_db, candidate):
    c = seeded_db
    request_id = workflow.submit(c, candidate["person_id"], 1, "Needed")
    with pytest.raises(workflow.WorkflowError, match="reason"):
        workflow.reject(c, request_id, candidate["vp_approver_id"], "   ")
    workflow.reject(c, request_id, candidate["vp_approver_id"], "Role is being merged")
    assert status(c, request_id) == "rejected"
    assert trail(c, request_id)[-1] == ("submitted", "rejected")
    with pytest.raises(workflow.WorkflowError):
        workflow.approve(c, request_id, candidate["vp_approver_id"])


@pytest.mark.parametrize("to_status", ["recruiter_assigned", "req_open", "filled", "submitted"])
def test_cannot_skip_steps(seeded_db, candidate, to_status):
    request_id = workflow.submit(seeded_db, candidate["person_id"], 1, "Needed")
    with pytest.raises(workflow.WorkflowError, match="cannot go from submitted"):
        workflow.transition(seeded_db, request_id, to_status, actor_id=1)
    assert status(seeded_db, request_id) == "submitted"
    assert len(trail(seeded_db, request_id)) == 1                 # nothing was logged for the failed move


def test_filled_is_final(seeded_db):
    done = db.one(seeded_db, "SELECT id, recruiter_id FROM backfill_requests WHERE status = 'filled' LIMIT 1")
    with pytest.raises(workflow.WorkflowError):
        workflow.open_request(seeded_db, done["id"], done["recruiter_id"])


def test_one_live_backfill_per_seat(seeded_db, candidate):
    workflow.submit(seeded_db, candidate["person_id"], 1, "Needed")
    with pytest.raises(workflow.WorkflowError, match="already has a backfill"):
        workflow.submit(seeded_db, candidate["person_id"], 1, "Asking again")


def test_audit_trail_cannot_be_edited(seeded_db):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded_db.execute("UPDATE request_events SET note = 'rewritten' WHERE id = (SELECT min(id) FROM request_events)")


def test_seeded_requests_have_consistent_trails(seeded_db):
    """Every seeded request's last event matches its status."""
    bad = db.query(seeded_db, """
        SELECT b.id FROM backfill_requests b
        JOIN LATERAL (SELECT to_status FROM request_events e WHERE e.backfill_request_id = b.id
                      ORDER BY e.at DESC, e.id DESC LIMIT 1) last ON TRUE
        WHERE last.to_status <> b.status""")
    assert bad == []


def test_demo_vp_has_three_requests_waiting(seeded_db):
    row = db.one(seeded_db, """
        SELECT count(*) AS n FROM backfill_requests
        WHERE status = 'submitted' AND vp_approver_id = (SELECT value::int FROM app_meta WHERE key = 'persona_vp')""")
    assert row["n"] == 3


@pytest.fixture()
def reseed_after(manifest):
    """The browser test commits real changes, so put the data back afterwards."""
    yield
    from scripts.seed import seed
    from tests.conftest import SEEDED_SCHEMA, TEST_URL
    with db.connect(TEST_URL, schema=SEEDED_SCHEMA) as conn:
        seed(conn)


def test_flow_in_the_browser(reseed_after):
    """Requester submits, VP approves from the inbox, recruiter opens and fills."""
    from app.main import app
    with db.get_conn() as conn:
        sam = db.one(conn, "SELECT value::int AS id FROM app_meta WHERE key = 'persona_requester'")["id"]
        person = db.one(conn, """
            SELECT k.person_id, k.full_name FROM v_backfill_candidates k
            JOIN v_org_closure c ON c.org_id = k.org_id
            JOIN people s ON s.org_id = c.ancestor_id AND s.id = %s
            WHERE k.end_date > today() AND k.job_family = 'research' ORDER BY k.end_date LIMIT 1""", (sam,))
    with TestClient(app) as client:
        client.cookies.set("role", "requester")
        assert client.get("/requests").status_code == 200
        form = client.get("/backfill/new")
        assert form.status_code == 200 and person["full_name"] in form.text
        assert person["full_name"] in client.get(f"/backfill/search?q={person['full_name'][:4]}").text
        assert "stays at" in client.get(f"/backfill/preview?person={person['person_id']}").text
        created = client.post("/backfill", data={"person": person["person_id"], "justification": "Test", "urgency": "urgent"},
                              follow_redirects=False)
        assert created.status_code == 303
        url = created.headers["location"].split("?")[0]
        assert "Waiting on" in client.get(url).text

        client.cookies.set("role", "vp")
        inbox = client.get("/requests")
        assert "4 requests need your approval" in inbox.text
        approved = client.post(f"{url}/approve", headers={"HX-Request": "true"})
        assert approved.status_code == 200 and "Approved" in approved.text and "3 requests need your approval" in approved.text

        client.cookies.set("role", "recruiter")
        assert client.get("/requests").status_code == 200
        with db.get_conn() as conn:
            row = db.one(conn, "SELECT recruiter_id, (SELECT value::int FROM app_meta WHERE key = 'persona_recruiter') AS marcus "
                               "FROM backfill_requests WHERE id = %s", (int(url.rsplit("/", 1)[1]),))
        assert row["recruiter_id"] == row["marcus"]               # the demo recruiter is the least loaded
        assert client.post(f"{url}/open", follow_redirects=False).status_code == 303
        assert client.post(f"{url}/fill", data={"hire_name": "Robin Okafor"}, follow_redirects=False).status_code == 303
        page = client.get(url)
        assert "Filled" in page.text and "Offer accepted by Robin Okafor" in page.text
        for role in ("svp", "rm"):
            client.cookies.set("role", role)
            assert client.get("/requests").status_code == 200
            assert client.get("/requests?scope=all&status=filled").status_code == 200
