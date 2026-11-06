"""Every page renders against the seeded data, for every role."""

import pytest
from tests.conftest import Client as TestClient

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
    assert "synthetic data" in page.text and "Take the tour" in page.text


@pytest.mark.parametrize("path", [
    "/?org=1", "/?org={team}", "/positions?org={svp}", "/positions?org={svp}&bucket=committed",
    "/positions?org={svp}&bucket=reserve&direct=1", "/positions/{position}", "/plan?org={svp}", "/about",
    "/palette?q=priya", "/palette", "/healthz", "/docs", "/budget", "/budget?org={svp}", "/org", "/org/children?parent={svp}&depth=1",
    "/styleguide", "/planning", "/forecast", "/positions/{position}?partial=1", "/people/1", "/positions?org={svp}&sort=cost&dir=desc&page=2",
    "/positions?org={svp}&format=csv", "/budget?org={svp}&format=csv", "/plan?org={svp}&format=csv",
])
def test_page_renders(client, ids, path):
    assert client.get(path.format(**ids)).status_code == 200


def test_unknown_org_is_a_404(client):
    assert client.get("/?org=999999").status_code == 404


def test_role_switch_lands_each_role_on_today(client):
    for role, (_, landing) in web.ROLES.items():
        response = client.post("/role", data={"role": role}, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == landing == "/today"
        page = client.get("/today")
        assert page.status_code == 200 and web.ROLES[role][0] in page.text
    client.cookies.delete("role")


def test_sort_and_filters_live_in_the_url(client, ids):
    page = client.get(f"/positions?org={ids['svp']}&bucket=committed&sort=cost&dir=desc")
    assert 'aria-sort="descending"' in page.text
    costs = [int(c.replace(",", "")) for c in __import__("re").findall(r'data-label="Cost a year">\$([0-9,]+)K', page.text)]
    assert costs and costs == sorted(costs, reverse=True)
    assert client.get(f"/positions?org={ids['svp']}&sort=;drop table").status_code == 200   # unknown sort falls back


def test_csv_export(client, ids):
    response = client.get(f"/positions?org={ids['svp']}&bucket=committed&format=csv")
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("Position,Team") and len(lines) > 10


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
        assert 'data-pick-name="Siobhan O&#39;Connor"' in html
        assert "value = '" not in html
    finally:
        with db.get_conn() as conn:
            conn.execute("UPDATE people SET full_name = %s WHERE id = %s", (person["full_name"], person["person_id"]))


def test_a_today_number_opens_exactly_its_rows(client):
    """The SVP's "waiting on a VP" tile and the list it opens agree."""
    import re
    today = client.get("/today", cookies={"role": "svp"}).text
    href, count = re.search(r'href="(/requests\?[^"]+)"><span>Backfills waiting on a VP</span><b>(\d+)</b>', today).groups()
    rows = client.get(href.replace("&amp;", "&"), cookies={"role": "svp"}).text
    assert rows.count('class="rowlink"') == int(count)


def test_the_form_skeleton_is_hidden_until_something_loads():
    from pathlib import Path
    css = Path("app/static/app.css").read_text()
    assert css.index(".skeleton-rows {") < css.index(".htmx-indicator { display: none; }")


def test_headcount_seat_map_adds_up(client):
    """One square per unfilled seat, and the focus changes what is highlighted, not the count."""
    import re
    page = client.get("/?focus=committed").text
    seats = re.search(r'<div class="seats".*?</div>', page, re.S).group(0)
    match = re.search(r'Of (\d+) unfilled seats: (\d+) committed, (\d+) reserve, (\d+) over-hired, (-?\d+) usable open', seats)
    total, committed, reserve, over, usable = map(int, match.groups())
    assert total == committed + reserve + over + usable
    assert seats.count("<i ") == total and seats.count(" on\"") == committed


def test_seat_history_ends_near_today(seeded_db):
    from app import trends
    history = trends.seat_history(seeded_db, 1)
    assert len(history) == 60 and history[0]["day"] < history[-1]["day"]
    now = seeded_db.execute("SELECT usable_open FROM v_usable_open WHERE org_id = 1").fetchone()
    assert abs(history[-1]["usable_open"] - (now["usable_open"] if isinstance(now, dict) else now[0])) < 25
