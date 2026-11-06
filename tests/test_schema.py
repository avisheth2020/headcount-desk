"""The schema applies cleanly and its guard rails hold."""

import psycopg
import pytest

from app import db

EXPECTED_TABLES = {
    "orgs", "people", "positions", "staffing_requests", "plan_versions", "plan_lines",
    "backfill_requests", "request_events", "daily_snapshots", "check_runs", "check_results",
    "exception_resolutions", "recruiter_coverage", "app_meta",
}


def test_all_tables_exist(empty_db):
    rows = db.query(empty_db, "SELECT table_name FROM information_schema.tables "
                              "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'")
    assert EXPECTED_TABLES <= {r["table_name"] for r in rows}


def test_every_table_has_created_at(empty_db):
    rows = db.query(empty_db, "SELECT table_name FROM information_schema.columns "
                              "WHERE table_schema = current_schema() AND column_name = 'created_at'")
    assert EXPECTED_TABLES <= {r["table_name"] for r in rows}


def test_locked_plan_cannot_be_edited(empty_db):
    c = empty_db
    c.execute("INSERT INTO orgs (id, name, level, cost_center) VALUES (1, 'Co', 'company', 'CC-1')")
    c.execute("INSERT INTO plan_versions (id, name) VALUES (1, 'Plan')")
    c.execute("INSERT INTO plan_lines VALUES (1, 1, 'eng', 10, 1000)")
    c.execute("UPDATE plan_versions SET locked_at = now(), content_hash = plan_hash(1) WHERE id = 1")
    with pytest.raises(psycopg.errors.RaiseException, match="locked"):
        c.execute("UPDATE plan_lines SET approved_headcount = 99 WHERE plan_version_id = 1")


def test_bad_status_is_rejected(empty_db):
    c = empty_db
    c.execute("INSERT INTO orgs (id, name, level, cost_center) VALUES (1, 'Co', 'company', 'CC-1')")
    with pytest.raises(psycopg.errors.CheckViolation):
        c.execute("INSERT INTO positions (position_code, org_id, job_family, level, position_type, opened_at) "
                  "VALUES ('P-1', 1, 'eng', 'L5', 'imaginary', today())")
