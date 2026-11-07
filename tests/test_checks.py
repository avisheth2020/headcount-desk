"""The data checks: the planted anomaly is flagged, clean data passes, broken data fails."""

import pytest
from tests.conftest import Client as TestClient

from app import db
from app.checks import CHECKS, run_checks


def results(conn, check_name):
    return db.query(conn, f"SELECT * FROM v_check_{check_name}")


def worst(rows):
    return max((r["severity"] for r in rows), key=["pass", "warn", "fail"].index)


def test_planted_anomaly_is_flagged(seeded_db, manifest):
    flagged = [r for r in results(seeded_db, "ratio") if r["severity"] != "pass"]
    assert len(flagged) == 1
    anomaly = manifest["anomaly"]
    assert flagged[0]["org_id"] == anomaly["org_id"]
    assert float(flagged[0]["expected"]) == anomaly["share_before_pct"]
    assert float(flagged[0]["actual"]) == anomaly["share_after_pct"]
    assert flagged[0]["actual"] - flagged[0]["expected"] > 5
    assert flagged[0]["message"].startswith(f"{anomaly['org']} went from")


@pytest.mark.parametrize("check_name", ["tieout", "rollup", "referential", "plan_integrity", "open_share", "cost_rates"])
def test_other_checks_pass_on_fresh_data(seeded_db, check_name):
    rows = results(seeded_db, check_name)
    assert rows and worst(rows) == "pass", [r["message"] for r in rows if r["severity"] != "pass"]


def test_this_mornings_run_is_six_of_eight(seeded_db):
    """Two checks need a look on fresh data, by design: the planted anomaly and two orgs over budget."""
    run = db.one(seeded_db, "SELECT * FROM check_runs ORDER BY run_at DESC LIMIT 1")
    assert (run["passed"], run["warned"], run["failed"]) == (6, 2, 0)
    assert db.one(seeded_db, "SELECT count(*) AS n FROM check_runs")["n"] == 14


def test_tieout_catches_a_snapshot_that_does_not_add_up(seeded_db):
    seeded_db.execute("""
        UPDATE daily_snapshots SET filled = filled + 5
        WHERE org_id = 1 AND snapshot_date = (SELECT today_date FROM v_snapshot_days)""")
    failed = [r for r in results(seeded_db, "tieout") if r["severity"] == "fail"]
    assert [r["org_id"] for r in failed] == [1]
    assert failed[0]["actual"] - failed[0]["expected"] == 5


def test_rollup_catches_a_team_that_was_double_counted(seeded_db):
    team = db.one(seeded_db, "SELECT id, parent_id FROM orgs WHERE level = 'team' ORDER BY id LIMIT 1")
    seeded_db.execute("""
        UPDATE daily_snapshots SET filled = filled * 2
        WHERE org_id = %s AND snapshot_date = (SELECT today_date FROM v_snapshot_days)""", (team["id"],))
    failed = [r["org_id"] for r in results(seeded_db, "rollup") if r["severity"] == "fail"]
    assert failed == [team["parent_id"]]


def test_referential_catches_a_person_with_no_seat(seeded_db):
    seeded_db.execute("""
        INSERT INTO people (full_name, email, org_id, job_family, level, location, start_date)
        VALUES ('No Seat', 'no.seat@example.com', 1, 'eng', 'L5', 'Remote', today() - 30)""")
    assert worst(results(seeded_db, "referential")) == "fail"


def test_plan_integrity_catches_an_edit_made_around_the_lock(seeded_db):
    """The trigger blocks normal edits. If someone switches it off, the fingerprint still catches them."""
    seeded_db.execute("ALTER TABLE plan_lines DISABLE TRIGGER plan_lines_locked")
    seeded_db.execute("""
        UPDATE plan_lines SET approved_headcount = approved_headcount + 10
        WHERE (plan_version_id, org_id, job_family) = (SELECT plan_version_id, org_id, job_family FROM plan_lines
                                                        WHERE plan_version_id = 2 LIMIT 1)""")
    rows = results(seeded_db, "plan_integrity")
    assert [r["severity"] for r in rows] == ["pass", "fail"] and "edited a locked plan" in rows[1]["message"]


def test_open_share_warns_when_too_many_seats_are_unworked(seeded_db):
    vp = db.one(seeded_db, "SELECT id FROM orgs WHERE level = 'vp' ORDER BY id LIMIT 1")["id"]
    seeded_db.execute("""
        UPDATE positions SET person_id = NULL
        WHERE id IN (SELECT p.id FROM positions p JOIN v_org_closure c ON c.org_id = p.org_id
                     WHERE c.ancestor_id = %s AND p.position_type = 'standard' AND p.person_id IS NOT NULL LIMIT 80)""", (vp,))
    warned = [r["org_id"] for r in results(seeded_db, "open_share") if r["severity"] == "warn"]
    assert warned == [vp]


def test_run_checks_stores_every_row_and_counts_checks(seeded_db):
    run_id = run_checks(seeded_db)
    run = db.one(seeded_db, "SELECT * FROM check_runs WHERE id = %s", (run_id,))
    assert run["passed"] + run["warned"] + run["failed"] == len(CHECKS)
    stored = db.one(seeded_db, "SELECT count(*) AS n, count(DISTINCT check_name) AS checks FROM check_results WHERE check_run_id = %s", (run_id,))
    assert stored["checks"] == len(CHECKS)
    assert stored["n"] == db.one(seeded_db, "SELECT count(*) AS n FROM v_check_all")["n"]


def test_health_pages(manifest):
    from app.main import app
    with TestClient(app) as client:
        client.cookies.set("role", "rm")
        page = client.get("/health")
        assert page.status_code == 200
        assert "6 of 8 checks passed" in page.text and "2 need a look" in page.text
        assert f"{manifest['anomaly']['org']} went from" in page.text
        for name in CHECKS:
            assert client.get(f"/health/check/{name}").status_code == 200
        rows = client.get(f"/health/snapshots?org={manifest['anomaly']['org_id']}")
        assert rows.status_code == 200 and "pts" in rows.text
        again = client.post("/health/run", follow_redirects=False)
        assert again.status_code == 303
        with db.get_conn() as conn:
            conn.execute("DELETE FROM check_runs WHERE id = (SELECT max(id) FROM check_runs)")


def test_every_seeded_run_has_a_result_for_every_check(seeded_db):
    from app.checks import CHECKS
    rows = db.query(seeded_db, """
        SELECT r.id, count(DISTINCT c.check_name) AS checks, r.passed + r.warned + r.failed AS total
        FROM check_runs r JOIN check_results c ON c.check_run_id = r.id GROUP BY r.id""")
    assert len(rows) == 14 and all(r["checks"] == len(CHECKS) == r["total"] for r in rows)
