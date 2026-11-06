"""Shared page plumbing: templates, formatting, the simulated roles, and the
values every page shows (who you are viewing as, how fresh the data is)."""

import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import db, demo

APP_DIR = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
templates = Jinja2Templates(directory=APP_DIR / "templates")

# role key -> (label, landing page). Each role is one named demo person (see app_meta).
ROLES = {
    "svp": ("SVP", "/"),
    "vp": ("VP", "/requests"),
    "requester": ("Requester", "/requests"),
    "recruiter": ("Recruiter", "/requests"),
    "rm": ("Resource Manager", "/exceptions"),
}
DEFAULT_ROLE = "svp"

# Plain-language definitions, used for the ⓘ tooltips and the row drill-downs.
BUCKETS = {
    "approved": ("Approved", "Headcount in the latest locked plan."),
    "filled": ("Filled", "Seats with a person in them."),
    "committed": ("Committed", "Open seats a recruiter is already working: an open staffing request or an offer out."),
    "reserve": ("Reserve", "Headcount the SVP holds centrally and hasn't assigned to a team yet."),
    "negative": ("Negative", "Over-hires: people hired beyond the plan. Each one uses up a seat."),
    "open_no_req": ("Open, no request", "Empty seats the position tool lists that nobody is recruiting for."),
    "usable_open": ("Usable open", "What is left after the rest: seats you can start hiring into today."),
}
FAMILY_LABELS = {"research": "Research", "eng": "Engineering", "ops": "Operations", "g&a": "G&A"}
LEVEL_LABELS = {"company": "Company", "svp": "SVP org", "vp": "VP org", "director": "Director org", "team": "Team"}


# ── formatting filters ───────────────────────────────────────────────────────

def fmt_num(value) -> str:
    return "–" if value is None else f"{int(value):,}".replace("-", "−")


def fmt_money(value) -> str:
    value = float(value or 0)
    if value >= 1e9:
        return f"${value / 1e9:.2f}B"
    if value >= 1e6:
        return f"${value / 1e6:.1f}M"
    return f"${value:,.0f}"


def fmt_date(value) -> str:
    if value is None:
        return "–"
    return f"{value:%b} {value.day}" if value.year == datetime.now(ET).year else f"{value:%b} {value.day}, {value.year}"


def fmt_datetime(value) -> str:
    if value is None:
        return "–"
    local = value.astimezone(ET)
    return f"{local:%a %b} {local.day}, {local:%I:%M %p}".replace(", 0", ", ")


def fmt_ago(value) -> str:
    """How long since a timestamp or date, in words: '3 hours', '2 days'."""
    if value is None:
        return "–"
    if isinstance(value, datetime):
        delta = datetime.now(ET) - value.astimezone(ET)
    elif isinstance(value, date):
        delta = datetime.now(ET).date() - value
    else:
        delta = value
    if not isinstance(delta, timedelta):
        return str(delta)
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return "less than an hour"
    if hours < 24:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''}"
    days = round(hours / 24)
    return f"{days} day{'s' if days != 1 else ''}"


templates.env.filters.update(num=fmt_num, money=fmt_money, d=fmt_date, dt=fmt_datetime, ago=fmt_ago)
templates.env.globals.update(asset_version=int(time.time()), BUCKETS=BUCKETS, FAMILY=FAMILY_LABELS, LEVELS=LEVEL_LABELS, ROLES=ROLES)


# ── what every page needs ────────────────────────────────────────────────────

def current_role(request: Request) -> str:
    role = request.cookies.get("role", DEFAULT_ROLE)
    return role if role in ROLES else DEFAULT_ROLE


def page_context(request: Request, conn) -> dict:
    """Role, persona and data freshness. Also makes sure the demo data was
    built for today (it rebuilds itself once a day)."""
    meta = demo.ensure_fresh(conn)
    role = current_role(request)
    personas = {r["key"]: r for r in db.query(conn, """
        SELECT replace(m.key, 'persona_', '') AS key, p.id, p.full_name, p.org_id, o.name AS org_name
        FROM app_meta m
        JOIN people p ON p.id = m.value::int
        JOIN orgs o ON o.id = p.org_id
        WHERE m.key LIKE 'persona_%%'""")}
    plan = db.one(conn, "SELECT name, locked_at FROM v_current_plan")
    as_of = datetime.combine(date.fromisoformat(meta["seed_as_of"]), datetime.min.time(), ET).replace(hour=6)
    return {
        "request": request,
        "role": role,
        "role_label": ROLES[role][0],
        "me": personas[role],
        "personas": personas,
        "as_of": as_of,
        "plan": plan,
        "path": request.url.path,
    }


def render(request: Request, name: str, ctx: dict, status_code: int = 200):
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
