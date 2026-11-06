"""Dollars: the budget math on a hand-worked fixture, then the seeded company.

Fixture (one team under one VP; fiscal year exactly half over, so 6.0 months left):

    seat   who        cost a year   counts as
    A      a person     $200,000    run-rate
    B      a person     $100,000    run-rate
    C      over-hire    $100,000    run-rate (a negative seat still costs money)
    D      recruiting   $120,000    committed: 120,000 × 6/12 = $60,000
    E      nobody       $100,000    nothing (no person, no request)
    F      reserve      $100,000    nothing

    budget (plan)  = $450,000
    run-rate       = 200 + 100 + 100              = $400,000
    committed      = 120 × 6/12                   = $ 60,000
    projected      = 400 + 60                     = $460,000   → 102.2% of budget, $10,000 over
"""

import pytest

from app import db


@pytest.fixture()
def budget_db(empty_db):
    c = empty_db
    c.execute("""
        INSERT INTO fiscal_years (name, starts_on, ends_on) VALUES ('FY', today() - 183, today() + 183);
        INSERT INTO orgs (id, name, parent_id, level, cost_center) VALUES
            (1, 'Company', NULL, 'company', 'CC-1'), (2, 'SVP', 1, 'svp', 'CC-2'), (3, 'VP', 2, 'vp', 'CC-3'),
            (4, 'Dir', 3, 'director', 'CC-4'), (5, 'Team', 4, 'team', 'CC-5');
        INSERT INTO people (id, full_name, email, org_id, job_family, level, location, start_date)
        SELECT n, 'Person ' || n, 'p' || n || '@example.com', 5, 'eng', 'L5', 'Remote', today() - 400 FROM generate_series(1, 4) n;
        INSERT INTO cost_rates (job_family, level, location, annual_loaded_cost_usd) VALUES
            ('eng', 'L5', 'Remote', 100000), ('eng', 'L6', 'Remote', 200000), ('eng', 'L5', 'London', 120000);
        INSERT INTO positions (id, position_code, org_id, job_family, level, position_type, person_id, opened_at, location) VALUES
            (1, 'A', 5, 'eng', 'L6', 'standard', 1,    today() - 500, 'Remote'),
            (2, 'B', 5, 'eng', 'L5', 'standard', 2,    today() - 500, 'Remote'),
            (3, 'C', 5, 'eng', 'L5', 'negative', 3,    today() - 100, 'Remote'),
            (4, 'D', 5, 'eng', 'L5', 'standard', NULL, today() - 20,  'London'),
            (5, 'E', 5, 'eng', 'L5', 'standard', NULL, today() - 10,  'Remote'),
            (6, 'F', 2, 'eng', 'L5', 'reserve',  NULL, today() - 30,  'Remote');
        INSERT INTO staffing_requests (position_id, recruiter_id, status, opened_at) VALUES (4, 4, 'open', today() - 15);
        INSERT INTO plan_versions (id, name, fiscal_year, effective_from) VALUES (1, 'Plan', 'FY', today() - 183);
        INSERT INTO plan_lines (plan_version_id, org_id, job_family, approved_headcount, approved_cost_usd) VALUES (1, 5, 'eng', 4, 450000);
        UPDATE plan_versions SET locked_at = now() - interval '200 days', content_hash = plan_hash(1) WHERE id = 1;""")
    return c


def test_fixture_budget_math(budget_db):
    assert float(db.one(budget_db, "SELECT months_left FROM v_fiscal_now")["months_left"]) == 6.0
    row = db.one(budget_db, "SELECT * FROM v_budget WHERE name = 'Team'")
    assert (row["budget"], row["run_rate"], row["committed"], row["projected"], row["variance"]) == (450000, 400000, 60000, 460000, -10000)
    assert float(row["pct_of_budget"]) == 102.2 and row["state"] == "over"


def test_budget_rolls_up_and_reserve_costs_nothing(budget_db):
    company = db.one(budget_db, "SELECT * FROM v_budget WHERE name = 'Company'")
    assert (company["budget"], company["projected"]) == (450000, 460000)


def test_budget_check_flags_the_org_that_is_over(budget_db):
    rows = db.query(budget_db, "SELECT * FROM v_check_budget")
    assert [(r["severity"], float(r["actual"])) for r in rows] == [("warn", 102.2)]
    assert "over" in rows[0]["message"]


def test_a_seat_with_no_rate_fails_the_cost_check(budget_db):
    assert db.one(budget_db, "SELECT severity FROM v_check_cost_rates")["severity"] == "pass"
    budget_db.execute("UPDATE positions SET location = 'Atlantis' WHERE id = 5")
    row = db.one(budget_db, "SELECT severity, actual FROM v_check_cost_rates")
    assert (row["severity"], row["actual"]) == ("fail", 1)


def test_next_years_plan_does_not_change_this_years_numbers(budget_db):
    """A plan locked today for a later fiscal year is not 'the current plan' yet."""
    budget_db.execute("""
        INSERT INTO plan_versions (id, name, effective_from) VALUES (2, 'Next year', today() + 200);
        INSERT INTO plan_lines (plan_version_id, org_id, job_family, approved_headcount, approved_cost_usd) VALUES (2, 3, 'eng', 99, 9900000);
        UPDATE plan_versions SET locked_at = now(), content_hash = plan_hash(2) WHERE id = 2;""")
    assert db.one(budget_db, "SELECT name FROM v_current_plan")["name"] == "Plan"
    assert db.one(budget_db, "SELECT budget FROM v_budget WHERE name = 'Company'")["budget"] == 450000


def test_seeded_company_has_every_seat_costed_and_two_orgs_over(seeded_db):
    assert db.one(seeded_db, "SELECT count(*) AS n FROM v_position_cost WHERE annual_cost IS NULL")["n"] == 0
    states = {r["state"]: r["n"] for r in db.query(seeded_db, "SELECT state, count(*) AS n FROM v_budget WHERE level = 'vp' GROUP BY state")}
    assert states.get("over") == 2
    demo_vp = db.one(seeded_db, """
        SELECT b.state, b.pct_of_budget FROM v_budget b
        WHERE b.org_id = (SELECT org_id FROM people WHERE id = (SELECT value::int FROM app_meta WHERE key = 'persona_vp'))""")
    assert demo_vp["state"] == "watch" and 99 <= float(demo_vp["pct_of_budget"]) < 100


def test_seeded_budget_rolls_up(seeded_db):
    bad = db.query(seeded_db, """
        SELECT b.name FROM v_budget b JOIN v_budget_direct d ON d.org_id = b.org_id
        LEFT JOIN v_budget k ON k.parent_id = b.org_id
        GROUP BY b.org_id, b.name, b.budget, b.run_rate, d.budget, d.run_rate
        HAVING b.budget <> coalesce(sum(k.budget), 0) + d.budget OR b.run_rate <> coalesce(sum(k.run_rate), 0) + d.run_rate""")
    assert bad == []
