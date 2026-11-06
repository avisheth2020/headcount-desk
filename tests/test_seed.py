"""The synthetic data has the right shape, and it is the same every run."""

import json
from datetime import date, datetime

from app import db
from scripts.seed import ET, MANIFEST_PATH, PLANT_COUNTS, Builder


def test_about_six_thousand_people(seeded_db, manifest):
    active = db.one(seeded_db, "SELECT count(*) AS n FROM people WHERE end_date IS NULL OR end_date >= today()")["n"]
    assert active == manifest["counts"]["active_people"]
    assert 5_500 <= active <= 6_500


def test_row_counts_match_manifest(seeded_db, manifest):
    for table in ("orgs", "people", "positions", "staffing_requests", "backfill_requests", "plan_lines"):
        n = db.one(seeded_db, f"SELECT count(*) AS n FROM {table}")["n"]
        assert n == manifest["counts"][table], table


def test_org_chart_shape(seeded_db):
    levels = {r["level"]: r["n"] for r in db.query(seeded_db, "SELECT level, count(*) AS n FROM orgs GROUP BY level")}
    assert levels["company"] == 1 and levels["svp"] == 3 and levels["vp"] == 12
    assert 36 <= levels["director"] <= 48


def test_planted_counts(manifest):
    for kind, n in PLANT_COUNTS.items():
        assert len(manifest["plants"][kind]) == n, kind
    assert len(manifest["negative_positions"]) == 12


def test_sixty_days_of_snapshots_for_every_org(seeded_db):
    row = db.one(seeded_db, "SELECT count(DISTINCT snapshot_date) AS days, count(*) AS n, "
                            "(SELECT count(*) FROM orgs) AS orgs FROM daily_snapshots")
    assert row["days"] == 60 and row["n"] == 60 * row["orgs"]


def test_two_locked_plans_with_matching_hashes(seeded_db):
    rows = db.query(seeded_db, "SELECT name, locked_at, content_hash, plan_hash(id) AS now_hash FROM plan_versions ORDER BY id")
    assert [r["name"] for r in rows] == ["FY27 Plan", "FY27 Q1 Refresh"]
    assert all(r["locked_at"] and r["content_hash"] == r["now_hash"] for r in rows)


def test_seed_is_deterministic():
    as_of, now = date(2026, 11, 6), datetime(2026, 11, 6, 9, 0, tzinfo=ET)
    first, second = Builder(as_of, now).build(), Builder(as_of, now).build()
    assert first.manifest == second.manifest
    assert [p["full_name"] for p in first.people] == [p["full_name"] for p in second.people]


def test_committed_manifest_is_current(manifest):
    """seed_manifest.json in the repo matches what the seed produces today."""
    assert json.loads(MANIFEST_PATH.read_text()) == manifest
