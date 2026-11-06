"""Demo housekeeping: keep the synthetic data fresh, and let a visitor reset it."""

from datetime import datetime, timedelta, timezone

from app import db

RESET_COOLDOWN = timedelta(seconds=45)
RESEED_LOCK = 4242  # advisory lock id, so two requests never reseed at once


def read_meta(conn) -> dict:
    return {r["key"]: r["value"] for r in db.query(conn, "SELECT key, value FROM app_meta")}


def reseed(conn) -> dict:
    from scripts.seed import seed  # imported late: the seed pulls in faker
    seed(conn)
    conn.execute("INSERT INTO app_meta (key, value) VALUES ('last_reset_at', %s)",
                 (datetime.now(timezone.utc).isoformat(),))
    conn.commit()
    return read_meta(conn)


def ensure_fresh(conn) -> dict:
    """The data is built relative to today. On the first request of a new day,
    rebuild it, so "data as of this morning" is always true."""
    meta = read_meta(conn)
    today = db.one(conn, "SELECT today()::text AS d")["d"]
    if meta.get("seed_as_of") == today:
        return meta
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (RESEED_LOCK,))
    meta = read_meta(conn)                     # someone else may have just done it
    if meta.get("seed_as_of") != today:
        meta = reseed(conn)
    return meta


def reset(conn) -> tuple[bool, str]:
    """Visitor pressed "Reset demo". Returns (did it, message)."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (RESEED_LOCK,))
    last = read_meta(conn).get("last_reset_at")
    if last and datetime.now(timezone.utc) - datetime.fromisoformat(last) < RESET_COOLDOWN:
        return False, "The demo was reset a moment ago. Try again in a minute."
    reseed(conn)
    return True, "Demo reset. Everything is back to this morning's data."
