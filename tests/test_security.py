"""Request safety and role permissions. Identities are simulated, but the rules are enforced on the server."""

import pytest
from fastapi.testclient import TestClient as RawClient

from app import db, security
from tests.conftest import Client


@pytest.fixture(scope="module")
def client(manifest):
    from app.main import app
    with Client(app) as c:
        yield c


def as_role(client, role):
    client.cookies.set("role", role)
    return client


def test_a_write_without_the_csrf_token_is_refused(manifest):
    from app.main import app
    with RawClient(app) as raw:
        raw.get("/healthz")                                   # sets the cookie
        assert raw.post("/role", data={"role": "vp"}, follow_redirects=False).status_code == 403
        assert raw.post("/role", data={"role": "vp"}, headers={"X-CSRF-Token": "wrong"}, follow_redirects=False).status_code == 403
        ok = raw.post("/role", data={"role": "vp", "csrf_token": raw.cookies["csrf"]}, follow_redirects=False)
        assert ok.status_code == 303                          # a hidden form field works too


def test_security_headers_on_every_page(client):
    headers = client.get("/").headers
    assert "script-src 'self'" in headers["content-security-policy"] and "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-frame-options"] == "DENY" and headers["x-content-type-options"] == "nosniff"
    assert "max-age" in headers["strict-transport-security"]


def test_pages_have_no_inline_scripts_or_handlers(client):
    """The CSP forbids inline script, so none may be rendered."""
    for path in ("/", "/today", "/requests", "/exceptions", "/health", "/budget", "/org", "/styleguide", "/backfill/new"):
        html = client.get(path).text
        assert "onclick=" not in html and "hx-on" not in html and "<script>" not in html, path


def test_healthz_reports_the_database(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True and body["database"] == "ok" and body["data_as_of"]


def test_rate_limit_window(monkeypatch):
    class FakeRequest:
        headers = {"x-forwarded-for": "203.0.113.9"}
        client = None
    monkeypatch.setattr(security, "WRITES_PER_MINUTE", 3)
    security._writes.pop("203.0.113.9", None)
    assert [security.too_many_writes(FakeRequest()) for _ in range(5)] == [False, False, False, True, True]


# ── role permissions ─────────────────────────────────────────────────────────

def pending(conn, mine: bool) -> int:
    op = "=" if mine else "<>"
    return db.one(conn, f"""
        SELECT id FROM backfill_requests WHERE status = 'submitted'
          AND vp_approver_id {op} (SELECT value::int FROM app_meta WHERE key = 'persona_vp') ORDER BY id LIMIT 1""")["id"]


def test_only_the_vp_over_the_seat_can_approve(client):
    with db.get_conn() as conn:
        theirs, mine = pending(conn, mine=False), pending(conn, mine=True)
    assert as_role(client, "vp").post(f"/requests/{theirs}/approve", follow_redirects=False).status_code == 403
    for role in ("svp", "requester", "recruiter", "rm"):
        assert as_role(client, role).post(f"/requests/{mine}/approve", follow_redirects=False).status_code == 403
        assert as_role(client, role).post(f"/requests/{mine}/reject", data={"reason": "no"}, follow_redirects=False).status_code == 403
    with db.get_conn() as conn:
        assert db.one(conn, "SELECT status FROM backfill_requests WHERE id = %s", (mine,))["status"] == "submitted"


def test_only_the_assigned_recruiter_can_open_a_request(client):
    with db.get_conn() as conn:
        other = db.one(conn, """
            SELECT id FROM backfill_requests WHERE status = 'recruiter_assigned'
              AND recruiter_id <> (SELECT value::int FROM app_meta WHERE key = 'persona_recruiter') LIMIT 1""")["id"]
    for role in ("recruiter", "vp", "rm"):
        assert as_role(client, role).post(f"/requests/{other}/open", follow_redirects=False).status_code == 403


def test_backfills_can_only_be_requested_in_your_own_org(client):
    with db.get_conn() as conn:
        outside = db.one(conn, """
            SELECT k.person_id FROM v_backfill_candidates k
            WHERE k.end_date > today() AND NOT EXISTS (
                SELECT 1 FROM v_org_closure c JOIN people me ON me.org_id = c.ancestor_id
                WHERE c.org_id = k.org_id AND me.id = (SELECT value::int FROM app_meta WHERE key = 'persona_requester'))
            LIMIT 1""")["person_id"]
        before = db.one(conn, "SELECT count(*) AS n FROM backfill_requests")["n"]
    data = {"person": outside, "justification": "Not mine to ask for", "urgency": "normal"}
    assert as_role(client, "requester").post("/backfill", data=data, follow_redirects=False).status_code == 403
    assert as_role(client, "recruiter").post("/backfill", data=data, follow_redirects=False).status_code == 403
    with db.get_conn() as conn:
        assert db.one(conn, "SELECT count(*) AS n FROM backfill_requests")["n"] == before


def test_exceptions_can_only_be_resolved_by_an_owner(client):
    with db.get_conn() as conn:
        vp_org = db.one(conn, "SELECT org_id FROM people WHERE id = (SELECT value::int FROM app_meta WHERE key = 'persona_vp')")["org_id"]
        inside = db.one(conn, "SELECT exception_type, position_id FROM v_exceptions WHERE vp_id = %s AND NOT is_resolved LIMIT 1", (vp_org,))
        outside = db.one(conn, "SELECT exception_type, position_id FROM v_exceptions WHERE vp_id <> %s AND NOT is_resolved LIMIT 1", (vp_org,))
    for role in ("requester", "recruiter"):
        assert as_role(client, role).post("/exceptions/resolve", data=inside).status_code == 403
    assert as_role(client, "vp").post("/exceptions/resolve", data=outside).status_code == 403
    assert as_role(client, "vp").post("/exceptions/resolve", data=inside).status_code == 200
    undo = f"/exceptions/unresolve?exception_type={inside['exception_type']}&position_id={inside['position_id']}"
    assert as_role(client, "vp").post(undo).status_code == 200


def test_only_the_resource_manager_runs_checks(client):
    assert as_role(client, "svp").post("/health/run", follow_redirects=False).status_code == 403
    assert "Run checks now" not in as_role(client, "svp").get("/health").text
    assert "Run checks now" in as_role(client, "rm").get("/health").text


def test_long_input_is_rejected_with_a_message(client):
    with db.get_conn() as conn:
        person = db.one(conn, """
            SELECT k.person_id FROM v_backfill_candidates k JOIN v_org_closure c ON c.org_id = k.org_id
            JOIN people me ON me.org_id = c.ancestor_id AND me.id = (SELECT value::int FROM app_meta WHERE key = 'persona_requester')
            WHERE k.end_date > today() LIMIT 1""")["person_id"]
    response = as_role(client, "requester").post("/backfill", data={"person": person, "justification": "x" * 600}, follow_redirects=False)
    assert response.status_code == 303 and "under%20500" in response.headers["location"]
