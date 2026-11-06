"""Every planted error is caught, and nothing else is flagged."""

import pytest
from fastapi.testclient import TestClient

from app import db

TYPES = ["stale_open", "duplicate", "ghost_fill", "miscoded", "reserve_misplaced"]


def flagged(conn, exception_type):
    rows = db.query(conn, "SELECT position_code FROM v_exceptions WHERE exception_type = %s", (exception_type,))
    return sorted(r["position_code"] for r in rows)


@pytest.mark.parametrize("exception_type", TYPES)
def test_every_plant_is_caught_and_nothing_else(seeded_db, manifest, exception_type):
    planted = manifest["plants"][exception_type]
    assert len(planted) > 0
    assert flagged(seeded_db, exception_type) == planted


def test_every_exception_has_an_owner_and_a_fix(seeded_db):
    row = db.one(seeded_db, """
        SELECT count(*) AS n, count(owner_name) AS owners, count(suggested_fix) AS fixes, min(age_days) AS youngest
        FROM v_exceptions""")
    assert row["n"] == row["owners"] == row["fixes"] == 240
    assert row["youngest"] >= 0


def test_fixing_the_data_clears_the_exception(seeded_db, manifest):
    """Exceptions are derived, so correcting the source row makes the exception disappear."""
    code = manifest["plants"]["ghost_fill"][0]
    seeded_db.execute("UPDATE positions SET person_id = NULL, opened_at = today() WHERE position_code = %s", (code,))
    assert code not in flagged(seeded_db, "ghost_fill")


def test_mark_resolved_and_undo(manifest):
    from app.main import app
    with db.get_conn() as conn:
        e = db.one(conn, "SELECT exception_type, position_id FROM v_exceptions WHERE NOT is_resolved ORDER BY position_id LIMIT 1")
        before = db.one(conn, "SELECT count(*) AS n FROM exception_resolutions")["n"]
    with TestClient(app) as client:
        assert client.get("/exceptions").status_code == 200
        assert client.get("/exceptions?type=duplicate&show=all&org=2").status_code == 200
        done = client.post("/exceptions/resolve", data=e)
        assert done.status_code == 200 and "Resolved" in done.text and "toast" in done.headers["hx-trigger"]
        with db.get_conn() as conn:
            assert db.one(conn, "SELECT count(*) AS n FROM exception_resolutions")["n"] == before + 1
        undone = client.post(f"/exceptions/unresolve?exception_type={e['exception_type']}&position_id={e['position_id']}")
        assert undone.status_code == 200 and "Mark resolved" in undone.text
        with db.get_conn() as conn:
            assert db.one(conn, "SELECT count(*) AS n FROM exception_resolutions")["n"] == before
