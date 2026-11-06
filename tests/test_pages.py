"""Every page renders against the seeded data, for every role."""

import pytest
from fastapi.testclient import TestClient

from app import db, web


@pytest.fixture(scope="module")
def client(manifest):
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def ids(manifest):
    with db.get_conn() as conn:
        return {
            "svp": db.one(conn, "SELECT id FROM orgs WHERE name = 'Research'")["id"],
            "team": db.one(conn, "SELECT id FROM orgs WHERE level = 'team' ORDER BY id LIMIT 1")["id"],
            "position": db.one(conn, "SELECT id FROM positions ORDER BY id LIMIT 1")["id"],
        }


def test_headcount_shows_the_hero_number(client, ids):
    with db.get_conn() as conn:
        expected = db.one(conn, "SELECT usable_open FROM v_usable_open WHERE org_id = %s", (ids["svp"],))["usable_open"]
    page = client.get("/")
    assert page.status_code == 200
    assert "How many people can we actually hire?" in page.text
    assert f'class="hero-number"' in page.text and f">{expected}</a>" in page.text
    assert "Prototype" in page.text and "Try this" in page.text


@pytest.mark.parametrize("path", [
    "/?org=1", "/?org={team}", "/positions?org={svp}", "/positions?org={svp}&bucket=committed",
    "/positions?org={svp}&bucket=reserve&direct=1", "/positions/{position}", "/plan?org={svp}", "/about",
    "/search?q=priya", "/healthz", "/docs",
])
def test_page_renders(client, ids, path):
    assert client.get(path.format(**ids)).status_code == 200


def test_unknown_org_is_a_404(client):
    assert client.get("/?org=999999").status_code == 404


def test_role_switch_lands_each_role_on_its_page(client):
    for role, (_, landing) in web.ROLES.items():
        response = client.post("/role", data={"role": role}, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == landing
    client.cookies.clear()


@pytest.mark.parametrize("path", ["/api/usable-open", "/api/usable-open?org_id=2", "/api/exceptions?exception_type=duplicate",
                                  "/api/requests?status=submitted", "/api/requests/1001/events", "/api/checks/latest"])
def test_api_returns_json(client, path):
    response = client.get(path)
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/json")


def test_api_matches_the_page(client, ids):
    data = client.get(f"/api/usable-open?org_id={ids['svp']}").json()
    org = data["org"]
    assert org["usable_open"] == org["approved"] - org["filled"] - org["committed"] - org["reserve"] - org["negative"]
    assert sum(c["approved"] for c in data["children"]) <= org["approved"]


def test_friendly_404(client):
    page = client.get("/requests/999999")
    assert page.status_code == 404 and "find that" in page.text
    assert client.get("/api/usable-open?org_id=999999").json() == {"detail": "No such org"}


def test_names_with_apostrophes_are_safe_in_the_backfill_form(client):
    """A name like O'Connor must not end up inside an inline script."""
    with db.get_conn() as conn:
        person = db.one(conn, "SELECT person_id, full_name FROM v_backfill_candidates ORDER BY person_id LIMIT 1")
        conn.execute("UPDATE people SET full_name = %s WHERE id = %s", ("Siobhan O'Connor", person["person_id"]))
    try:
        html = client.get("/backfill/search?q=O'Conn").text
        assert 'data-name="Siobhan O&#39;Connor"' in html
        assert "value = '" not in html
    finally:
        with db.get_conn() as conn:
            conn.execute("UPDATE people SET full_name = %s WHERE id = %s", (person["full_name"], person["person_id"]))
