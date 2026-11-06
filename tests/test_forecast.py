"""The quarter-end forecast: today + expected hires − expected exits, with a range.

The fixture is small enough to work by hand. History: four requests that took
10, 20, 30 and 40 days to fill. Two requests are open now, aged 5 and 25 days.
With D days left in the quarter:

    chance(request) = of the past requests that took longer than its age,
                      the share that took no longer than its age + D

    e.g. D = 20:  age 5  → longer than 5: all four; filled by day 25: 10 and 20  → 2/4 = 0.50
                  age 25 → longer than 25: 30 and 40; filled by day 45: both     → 2/2 = 1.00
                  expected hires = 1.50

    exits: 1 of 21 people left in the last 60 days → 1/20 × 30.4375/60 a month.
"""

from math import sqrt

import pytest

from app import db

HISTORY = [10, 20, 30, 40]


@pytest.fixture()
def forecast_db(empty_db):
    c = empty_db
    c.execute("""
        INSERT INTO fiscal_years (name, starts_on, ends_on) VALUES ('FY', today() - 70, today() + 294);
        INSERT INTO orgs (id, name, parent_id, level, cost_center) VALUES
            (1, 'Company', NULL, 'company', 'CC-1'), (2, 'SVP', 1, 'svp', 'CC-2'), (3, 'VP', 2, 'vp', 'CC-3'),
            (4, 'Dir', 3, 'director', 'CC-4'), (5, 'Team', 4, 'team', 'CC-5');
        INSERT INTO cost_rates (job_family, level, location, annual_loaded_cost_usd) VALUES ('eng', 'L5', 'Remote', 100000);
        INSERT INTO people (id, full_name, email, org_id, job_family, level, location, start_date, end_date)
        SELECT n, 'Person ' || n, 'p' || n || '@example.com', 5, 'eng', 'L5', 'Remote', today() - 400,
               CASE WHEN n = 21 THEN today() - 30 END
        FROM generate_series(1, 21) n;
        INSERT INTO positions (id, position_code, org_id, job_family, level, person_id, opened_at)
        SELECT n, 'P-' || n, 5, 'eng', 'L5', CASE WHEN n <= 20 THEN n END, today() - 500 FROM generate_series(1, 26) n;
        INSERT INTO staffing_requests (position_id, recruiter_id, status, opened_at, closed_at) VALUES
            (23, 1, 'filled', today() - 110, today() - 100), (24, 1, 'filled', today() - 120, today() - 100),
            (25, 1, 'filled', today() - 130, today() - 100), (26, 1, 'filled', today() - 140, today() - 100),
            (21, 1, 'open', today() - 5, NULL), (22, 1, 'offer_out', today() - 25, NULL);
        INSERT INTO plan_versions (id, name, fiscal_year, effective_from) VALUES (1, 'Plan', 'FY', today() - 70);
        INSERT INTO plan_lines (plan_version_id, org_id, job_family, approved_headcount, approved_cost_usd) VALUES (1, 5, 'eng', 26, 2600000);
        UPDATE plan_versions SET locked_at = now() - interval '80 days', content_hash = plan_hash(1) WHERE id = 1;""")
    return c


def chance(age, days_left):
    longer = [d for d in HISTORY if d > age]
    return len([d for d in longer if d <= age + days_left]) / len(longer) if longer else 0.0


def test_fill_probability_follows_the_stated_rule(forecast_db):
    days_left = db.one(forecast_db, "SELECT quarter_ends_on - today() AS d FROM v_fiscal_now")["d"]
    rows = {r["age_days"]: float(r["p_fill"]) for r in db.query(forecast_db, "SELECT age_days, p_fill FROM v_fill_probability")}
    assert rows == {5: pytest.approx(chance(5, days_left)), 25: pytest.approx(chance(25, days_left))}
    if days_left == 20:                       # the worked example in the docstring
        assert rows == {5: 0.5, 25: 1.0}


def test_forecast_adds_up(forecast_db):
    f = db.one(forecast_db, "SELECT * FROM v_forecast WHERE name = 'VP'")
    days_left = f["days_left"]
    hires = [chance(5, days_left), chance(25, days_left)]
    rate = 1 / 20 * 30.4375 / 60
    exits = 20 * rate * days_left / 30.4375
    assert f["in_seats"] == 20 and f["open_requests"] == 2
    assert float(f["expected_hires"]) == pytest.approx(sum(hires), abs=0.05)
    assert float(f["monthly_rate"]) == pytest.approx(rate, abs=1e-4)
    assert float(f["expected_exits"]) == pytest.approx(exits, abs=0.06)
    p50 = 20 + sum(hires) - exits
    sd = sqrt(sum(p * (1 - p) for p in hires) + exits)
    assert f["projected"] == round(p50)
    assert (f["projected_low"], f["projected_high"]) == (round(p50 - 0.674 * sd), round(p50 + 0.674 * sd))
    assert f["projected_low"] <= f["projected"] <= f["projected_high"]
    assert f["over_plan"] is False            # 26 approved, about 21 projected
    assert float(f["projected_run_rate"]) == pytest.approx(2_000_000 + (sum(hires) - exits) * 100_000, abs=6000)


def test_an_org_over_its_plan_is_flagged(forecast_db):
    forecast_db.execute("ALTER TABLE plan_lines DISABLE TRIGGER plan_lines_locked")
    forecast_db.execute("UPDATE plan_lines SET approved_headcount = 18, approved_cost_usd = 1800000")
    f = db.one(forecast_db, "SELECT over_plan, over_budget FROM v_forecast WHERE name = 'VP'")
    assert f["over_plan"] is True and f["over_budget"] is True


def test_seeded_forecast_is_sane(seeded_db):
    odds = db.one(seeded_db, "SELECT min(p_fill) AS lo, max(p_fill) AS hi, count(*) AS n FROM v_fill_probability")
    assert 0 <= odds["lo"] <= odds["hi"] <= 1 and odds["n"] > 150
    assert db.one(seeded_db, "SELECT count(*) AS n FROM v_time_to_fill")["n"] > 300
    for f in db.query(seeded_db, "SELECT * FROM v_forecast WHERE level IN ('company', 'svp', 'vp')"):
        assert f["projected_low"] <= f["projected"] <= f["projected_high"], f["name"]
        assert f["expected_hires"] <= f["open_requests"], f["name"]
        assert 0 < float(f["monthly_rate"]) < 0.05, f["name"]
    company = db.one(seeded_db, "SELECT * FROM v_forecast WHERE org_id = 1")
    children = db.one(seeded_db, "SELECT sum(expected_hires) AS hires FROM v_forecast WHERE level = 'svp'")
    assert float(company["expected_hires"]) == pytest.approx(float(children["hires"]), abs=0.3)      # hires roll up


def test_forecast_pages(manifest):
    from app.main import app
    from tests.conftest import Client
    with Client(app) as client:
        for role in ("svp", "vp", "rm"):
            client.cookies.set("role", role)
            page = client.get("/forecast")
            assert page.status_code == 200 and "Where will we end the quarter?" in page.text and "Likely range" in page.text
        for path in ("/forecast?org=1", "/forecast?org=3&sort=projected&dir=desc", "/forecast/requests?org=2",
                     "/forecast/requests?org=2&format=csv", "/forecast/exits?org=2", "/forecast?org=1&format=csv"):
            assert client.get(path).status_code == 200, path
        assert client.get("/forecast?org=999999").status_code == 404
