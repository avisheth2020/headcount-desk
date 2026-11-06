"""Usable open headcount, checked against a ten-position fixture worked out by hand.

    Company
    └── SVP "Research"            2 reserve seats held here
        └── VP "Applied"
            └── Director "Models"
                ├── Team A        4 filled, 1 committed, 1 open with no request
                └── Team B        1 filled, 1 negative (an over-hire)

    The plan approves 6 for Team A, 2 for Team B and 2 (reserve) at the SVP: 10.

    Team A:  6 approved − 4 filled − 1 committed                 = 1 usable
    Team B:  2 approved − 1 filled − 1 negative                  = 0 usable
    SVP:    10 approved − 5 filled − 1 committed − 2 reserve − 1 negative = 1 usable
"""

import pytest

from app import db


@pytest.fixture()
def fixture_db(empty_db):
    c = empty_db
    c.execute("""
        INSERT INTO orgs (id, name, parent_id, level, cost_center) VALUES
            (1, 'Company', NULL, 'company', 'CC-1'), (2, 'Research', 1, 'svp', 'CC-2'),
            (3, 'Applied', 2, 'vp', 'CC-3'), (4, 'Models', 3, 'director', 'CC-4'),
            (5, 'Team A', 4, 'team', 'CC-5'), (6, 'Team B', 4, 'team', 'CC-6')""")
    c.execute("""
        INSERT INTO people (id, full_name, email, org_id, job_family, level, location, start_date)
        SELECT n, 'Person ' || n, 'p' || n || '@example.com', CASE WHEN n <= 4 THEN 5 ELSE 6 END,
               'research', 'L5', 'Remote', today() - 400
        FROM generate_series(1, 7) AS n""")
    c.execute("""
        INSERT INTO positions (id, position_code, org_id, job_family, level, position_type, person_id, opened_at) VALUES
            (1, 'P-01', 5, 'research', 'L5', 'standard', 1,    today() - 500),
            (2, 'P-02', 5, 'research', 'L5', 'standard', 2,    today() - 500),
            (3, 'P-03', 5, 'research', 'L5', 'standard', 3,    today() - 500),
            (4, 'P-04', 5, 'research', 'L5', 'standard', 4,    today() - 500),
            (5, 'P-05', 5, 'research', 'L5', 'standard', NULL, today() - 20),   -- committed (request below)
            (6, 'P-06', 5, 'research', 'L5', 'standard', NULL, today() - 10),   -- open, no request
            (7, 'P-07', 6, 'research', 'L5', 'standard', 5,    today() - 500),
            (8, 'P-08', 6, 'research', 'L5', 'negative', 6,    today() - 100),  -- over-hire
            (9, 'P-09', 2, 'research', 'L5', 'reserve',  NULL, today() - 30),
            (10, 'P-10', 2, 'research', 'L5', 'reserve', NULL, today() - 30)""")
    c.execute("INSERT INTO staffing_requests (position_id, recruiter_id, status, opened_at) VALUES (5, 7, 'open', today() - 15)")
    c.execute("INSERT INTO plan_versions (id, name) VALUES (1, 'Old plan'), (2, 'Current plan')")
    c.execute("""
        INSERT INTO plan_lines (plan_version_id, org_id, job_family, approved_headcount, approved_cost_usd) VALUES
            (1, 5, 'research', 99, 0),                                 -- the old plan must be ignored
            (2, 5, 'research', 6, 600), (2, 6, 'research', 2, 200), (2, 2, 'research', 2, 200)""")
    c.execute("UPDATE plan_versions SET locked_at = now() - interval '90 days', content_hash = plan_hash(1) WHERE id = 1")
    c.execute("UPDATE plan_versions SET locked_at = now() - interval '10 days', content_hash = plan_hash(2) WHERE id = 2")
    return c


def usable(conn, org_name):
    row = db.one(conn, "SELECT * FROM v_usable_open WHERE name = %s", (org_name,))
    return {k: row[k] for k in ("approved", "filled", "committed", "reserve", "negative", "open_no_req", "usable_open")}


def test_team_a(fixture_db):
    assert usable(fixture_db, "Team A") == dict(approved=6, filled=4, committed=1, reserve=0, negative=0, open_no_req=1, usable_open=1)


def test_team_b_over_hire_nets_to_zero(fixture_db):
    assert usable(fixture_db, "Team B") == dict(approved=2, filled=1, committed=0, reserve=0, negative=1, open_no_req=0, usable_open=0)


def test_svp_rolls_up_and_subtracts_reserve(fixture_db):
    assert usable(fixture_db, "Research") == dict(approved=10, filled=5, committed=1, reserve=2, negative=1, open_no_req=1, usable_open=1)


def test_company_equals_svp_here(fixture_db):
    assert usable(fixture_db, "Company")["usable_open"] == 1


def test_every_position_lands_in_exactly_one_bucket(fixture_db):
    rows = db.query(fixture_db, "SELECT bucket, count(*) AS n FROM v_position_status GROUP BY bucket")
    assert {r["bucket"]: r["n"] for r in rows} == {"filled": 5, "committed": 1, "open_no_req": 1, "reserve": 2, "negative": 1}


def test_filling_the_committed_seat_does_not_change_usable_open(fixture_db):
    """A hire moves a seat from committed to filled. Usable open should not move."""
    fixture_db.execute("UPDATE positions SET person_id = 7 WHERE id = 5")
    fixture_db.execute("UPDATE staffing_requests SET status = 'filled', closed_at = today() WHERE position_id = 5")
    assert usable(fixture_db, "Team A") == dict(approved=6, filled=5, committed=0, reserve=0, negative=0, open_no_req=1, usable_open=1)


def test_seeded_children_sum_to_parent(seeded_db):
    """On the full dataset: every org's numbers equal its children's plus what it holds directly."""
    bad = db.query(seeded_db, """
        SELECT u.name
        FROM v_usable_open u
        JOIN v_headcount_direct d ON d.org_id = u.org_id
        LEFT JOIN v_usable_open k ON k.parent_id = u.org_id
        GROUP BY u.org_id, u.name, u.usable_open, d.approved, d.filled, d.committed, d.reserve, d.negative
        HAVING u.usable_open <> coalesce(sum(k.usable_open), 0) + d.approved - d.filled - d.committed - d.reserve - d.negative""")
    assert bad == []
