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
