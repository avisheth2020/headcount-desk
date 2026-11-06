"""Shared page plumbing: templates, formatting, the simulated roles, and the
values every page shows (who you are viewing as, how fresh the data is)."""

import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app import charts, db, demo

APP_DIR = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
templates = Jinja2Templates(directory=APP_DIR / "templates")

# role key -> (label, landing page). Each role is one named demo person (see app_meta).
ROLES = {
    "svp": ("SVP", "/today"),
    "vp": ("VP", "/today"),
    "requester": ("Requester", "/today"),
    "recruiter": ("Recruiter", "/today"),
    "rm": ("Resource Manager", "/today"),
}
# Which optional areas are switched on. A tier only appears in the nav once it is finished.
FEATURES = {"budget": False, "planning": False, "forecast": False}
DEFAULT_ROLE = "svp"

# Plain-language definitions, used for the ⓘ tooltips and the row drill-downs.
BUCKETS = {
    "approved": ("Approved", "Headcount in the latest locked plan."),
    "filled": ("Filled", "Seats with a person in them."),
    "committed": ("Committed", "Open seats a recruiter is already working: an open req or an offer out."),
    "reserve": ("Reserve", "Headcount the SVP holds centrally and hasn't assigned to a team yet."),
    "negative": ("Over-hired", "People hired beyond the plan. Each one uses up a seat."),
    "open_no_req": ("Open, no req", "Empty seats the position tool lists that nobody is recruiting for."),
    "usable_open": ("Usable open", "What is left after the rest: seats you can start hiring into today."),
}
# One icon set. Every status chip, banner and button draws from this list, in the sidebar's line style.
ICONS = {
    "check": "M5 12.5l4.5 4.5L19 7.5",
    "x": "M6 6l12 12M18 6 6 18",
    "alert": "M12 9v4m0 3.5v.5M10.3 3.9 2.6 17.3A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.7L13.7 3.9a2 2 0 0 0-3.4 0Z",
    "up": "M12 19V5m-6 6 6-6 6 6",
    "down": "M12 5v14m-6-6 6 6 6-6",
    "clock": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 2",
    "progress": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 3v18",
    "circle": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
    "diamond": "M12 3l9 9-9 9-9-9 9-9Z",
    "person": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21c0-4 4-6 8-6s8 2 8 6",
    "undo": "M9 7 4 12l5 5M4 12h11a5 5 0 0 1 5 5v1",
    "lock": "M6 11h12v9H6zM8.5 11V7.5a3.5 3.5 0 0 1 7 0V11",
    "pencil": "M4 20l1-4L16 5l3 3L8 19l-4 1Z",
    "bulb": "M9 18h6m-5 3h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3Z",
    "refresh": "M20 11a8 8 0 0 0-14.3-4L4 9m0-5v5h5m-5 4a8 8 0 0 0 14.3 4l1.7-2m0 5v-5h-5",
    "download": "M12 4v11m-5-5 5 5 5-5M5 20h14",
}


def ico(name: str) -> Markup:
    return Markup(f'<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{ICONS[name]}"/></svg>')


FAMILY_LABELS = {"research": "Research", "eng": "Engineering", "ops": "Operations", "g&a": "G&A"}
LEVEL_LABELS = {"company": "Company", "svp": "SVP org", "vp": "VP org", "director": "Director org", "team": "Team"}


# ── formatting filters ───────────────────────────────────────────────────────

def fmt_num(value) -> str:
    return "–" if value is None else f"{int(value):,}".replace("-", "−")


def fmt_money(value) -> str:
    """Compact dollars: $1.86B, $187.8M, $412K."""
    if value is None:
        return "–"
    value = float(value)
    sign, value = ("−" if value < 0 else ""), abs(value)
    if value >= 1e9:
        return f"{sign}${value / 1e9:.2f}B"
    if value >= 1e6:
        return f"{sign}${value / 1e6:.1f}M"
    if value >= 1e3:
        return f"{sign}${value / 1e3:,.0f}K"
    return f"{sign}${value:,.0f}"


def fmt_date(value) -> str:
    if value is None:
        return "–"
    return f"{value:%b} {value.day}" if value.year == datetime.now(ET).year else f"{value:%b} {value.day}, {value.year}"


def fmt_datetime(value) -> str:
    if value is None:
        return "–"
    local = value.astimezone(ET)
    return f"{local:%a %b} {local.day}, {local:%I:%M %p}".replace(", 0", ", ")


def fmt_clock(value) -> str:
    return f"{value.astimezone(ET):%I:%M %p}".lstrip("0")


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


# ── tables: sorting, filters in the URL, CSV ─────────────────────────────────

def url_with(request: Request, **changes) -> str:
    """The current URL with some query parameters changed (None removes one)."""
    params = dict(request.query_params)
    for key, value in changes.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return request.url.path + ("?" + urlencode(params) if params else "")


def sorting(request: Request, columns: dict[str, str], default: str, default_dir: str = "asc") -> tuple[str, str, str]:
    """Read ?sort= and ?dir= safely. `columns` maps a public name to a SQL
    expression, so nothing from the URL is ever placed into SQL directly."""
    key = request.query_params.get("sort", default)
    if key not in columns:
        key = default
    direction = request.query_params.get("dir", default_dir if key == default else "asc")
    direction = "desc" if direction == "desc" else "asc"
    return f"{columns[key]} {direction.upper()} NULLS LAST", key, direction


def csv_response(filename: str, columns: list[tuple[str, str]], rows: list[dict]):
    """Rows as a CSV download. `columns` is (header, row key)."""
    import csv
    import io

    from fastapi.responses import Response
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow(["" if row.get(key) is None else row[key] for _, key in columns])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def csrf_input(request: Request) -> Markup:
    return Markup(f'<input type="hidden" name="csrf_token" value="{request.state.csrf}">')


templates.env.filters.update(num=fmt_num, money=fmt_money, d=fmt_date, dt=fmt_datetime, ago=fmt_ago, clock=fmt_clock)
templates.env.globals.update(asset_version=int(time.time()), BUCKETS=BUCKETS, FAMILY=FAMILY_LABELS, LEVELS=LEVEL_LABELS,
                             ROLES=ROLES, FEATURES=FEATURES, url_with=url_with, csrf_input=csrf_input, ico=ico,
                             sparkline=charts.sparkline, variance_bar=charts.variance)


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
        # Detail pages render inside the side drawer when asked for a partial.
        "layout": "_drawer.html" if request.query_params.get("partial") else "base.html",
    }


def render(request: Request, name: str, ctx: dict, status_code: int = 200):
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
