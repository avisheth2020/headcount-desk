"""Data health: "Can I trust these numbers?" The latest check run, in sentences."""

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import db, permissions, web
from app.checks import CHECKS, run_checks

router = APIRouter()
WORST = {"pass": 0, "warn": 1, "fail": 2}


def rows_link(check_name: str, org_id: int | None) -> str:
    """Where to see the rows behind one finding."""
    if check_name == "open_share":
        return f"/positions?org={org_id}&bucket=open_no_req"
    if check_name == "budget":
        return f"/budget?org={org_id}"
    if check_name == "cost_rates":
        return "/positions?org=1&sort=cost"
    if check_name == "plan_integrity":
        return "/plan?org=1"
    if check_name == "referential":
        return "/positions?org=1"
    return f"/health/snapshots?org={org_id or 1}"


def latest_run(conn) -> dict:
    return db.one(conn, "SELECT * FROM check_runs ORDER BY run_at DESC, id DESC LIMIT 1")


@router.get("/health", response_class=HTMLResponse, include_in_schema=False)
def health(request: Request, flash: str | None = None):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        run = latest_run(conn)
        results = db.query(conn, """
            SELECT r.*, o.name AS org_name FROM check_results r LEFT JOIN orgs o ON o.id = r.org_id
            WHERE r.check_run_id = %s ORDER BY r.id""", (run["id"],))
        cards = []
        for name, (title, asserts) in CHECKS.items():
            rows = [r for r in results if r["check_name"] == name]
            status = max((r["severity"] for r in rows), key=WORST.get, default="pass")
            cards.append({"name": name, "title": title, "asserts": asserts, "status": status, "tested": len(rows),
                          "problems": sum(r["severity"] != "pass" for r in rows)})
        problems = [{**r, "title": CHECKS[r["check_name"]][0], "link": rows_link(r["check_name"], r["org_id"])}
                    for r in results if r["severity"] != "pass"]
        history = db.query(conn, """
            SELECT * FROM (SELECT * FROM check_runs ORDER BY run_at DESC, id DESC LIMIT 14) recent ORDER BY run_at, id""")
        ctx.update(run=run, cards=cards, problems=problems, history=history, total=len(CHECKS), flash=flash,
                   clean_runs=sum(1 for h in history if h["warned"] == 0 and h["failed"] == 0))
    return web.render(request, "health.html", ctx)


@router.post("/health/run", include_in_schema=False)
def run_now(request: Request):
    with db.get_conn() as conn:
        permissions.check_run_checks(web.page_context(request, conn))
        run = db.one(conn, "SELECT * FROM check_runs WHERE id = %s", (run_checks(conn),))
    message = f"Checks ran just now: {run['passed']} of {len(CHECKS)} passed."
    return RedirectResponse(f"/health?flash={quote(message)}", status_code=303)


@router.get("/health/check/{name}", response_class=HTMLResponse, include_in_schema=False)
def check_detail(request: Request, name: str):
    """The rows behind one check: everything it tested in the latest run."""
    if name not in CHECKS:
        raise HTTPException(404, "No such check")
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        run = latest_run(conn)
        rows = db.query(conn, """
            SELECT r.*, o.name AS org_name FROM check_results r LEFT JOIN orgs o ON o.id = r.org_id
            WHERE r.check_run_id = %s AND r.check_name = %s
            ORDER BY (r.severity = 'pass'), r.id""", (run["id"], name))
        for r in rows:
            r["link"] = rows_link(name, r["org_id"])
        ctx.update(run=run, name=name, title=CHECKS[name][0], asserts=CHECKS[name][1], rows=rows)
    return web.render(request, "check_detail.html", ctx)


@router.get("/health/snapshots", response_class=HTMLResponse, include_in_schema=False)
def snapshots(request: Request, org: int = 1):
    """The stored daily snapshots for one org: the rows the tie-out and ratio checks read."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        org_row = db.one(conn, "SELECT id, name, level FROM orgs WHERE id = %s", (org,))
        if org_row is None:
            raise HTTPException(404, "No such org")
        rows = db.query(conn, """
            SELECT * FROM (
                SELECT s.*, 100.0 * s.total_people / company.total_people AS share,
                       100.0 * s.total_people / company.total_people
                         - lag(100.0 * s.total_people / company.total_people) OVER (ORDER BY s.snapshot_date) AS share_move,
                       s.total_people - lag(s.total_people) OVER (ORDER BY s.snapshot_date) AS people_move
                FROM daily_snapshots s
                JOIN daily_snapshots company ON company.snapshot_date = s.snapshot_date AND company.org_id = 1
                WHERE s.org_id = %s
            ) x ORDER BY snapshot_date DESC LIMIT 14""", (org,))
        live = db.one(conn, """
            SELECT count(*) AS people FROM people pe JOIN v_org_closure c ON c.org_id = pe.org_id
            WHERE c.ancestor_id = %s AND (pe.end_date IS NULL OR pe.end_date >= today())""", (org,))
        ctx.update(org=org_row, rows=rows, live=live)
    return web.render(request, "snapshots.html", ctx)
