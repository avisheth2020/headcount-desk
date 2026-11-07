"""Headcount Desk: the FastAPI app. Routes live in app/routes/."""

from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import db, demo, permissions, security, web
from app.checks import CHECKS
from app.routes import api, backfill, budget, exceptions, forecast, health, overview, planning, today

app = FastAPI(
    title="Headcount Desk",
    description="Usable open headcount, budget, planning, a backfill workflow and data checks for a fictional AI lab. All data is synthetic.",
    version="2.0.0",
    dependencies=[Depends(security.csrf_protect)],      # every write must carry the CSRF token
)
app.middleware("http")(security.middleware)             # headers, rate limit, JSON request log
app.add_middleware(GZipMiddleware, minimum_size=1024)   # pages and assets compress to about a fifth
app.mount("/static", StaticFiles(directory=web.APP_DIR / "static"), name="static")
for module in (today, overview, budget, planning, forecast, exceptions, backfill, health, api):
    app.include_router(module.router)
web.FEATURES.update(budget=True, planning=True, forecast=True)


def wants_html(request: Request) -> bool:
    return not request.url.path.startswith("/api") and "hx-request" not in request.headers


@app.exception_handler(StarletteHTTPException)
async def friendly_http_error(request: Request, exc: StarletteHTTPException):
    """Errors that read like a sentence, not a stack trace. The API and HTMX still get JSON."""
    if not wants_html(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    title = {404: "We couldn't find that", 403: "You can't do that in this role", 429: "Slow down a little"}.get(exc.status_code, "That didn't work")
    message = "The page, org, position or request you asked for doesn't exist. It may have been removed when the demo was reset." \
        if exc.status_code == 404 else str(exc.detail)
    return web.render(request, "error.html", {"code": exc.status_code, "title": title, "message": message}, exc.status_code)


@app.exception_handler(RequestValidationError)
async def friendly_bad_link(request: Request, exc: RequestValidationError):
    """A mistyped link, like ?org=abc, gets the same page as any other link that goes nowhere."""
    if not wants_html(request):
        return await request_validation_exception_handler(request, exc)
    return web.render(request, "error.html", {"code": 404, "title": "We couldn't find that",
                                              "message": "That link isn't quite right. Check it, or start again from the menu."}, 404)


@app.exception_handler(Exception)
async def friendly_server_error(request: Request, exc: Exception):
    security.log.error('{"severity": "ERROR", "path": "%s", "error": "%s"}', request.url.path, type(exc).__name__)
    if not wants_html(request):
        return JSONResponse({"detail": "Something went wrong"}, status_code=500)
    return web.render(request, "error.html", {
        "code": 500, "title": "Something went wrong on our side",
        "message": "Nothing you did. Try again, or reset the demo to start clean."}, 500)


@app.get("/healthz", include_in_schema=False)
@app.get("/api/health", tags=["API"], summary="Is the app up, and can it reach the database?")
def healthz():
    """Liveness and readiness. Served at /api/health as well, because Cloud Run
    answers /healthz itself and the request never reaches the app there."""
    try:
        with db.get_conn() as conn:
            as_of = db.one(conn, "SELECT value FROM app_meta WHERE key = 'seed_as_of'")
        return {"ok": True, "database": "ok", "data_as_of": as_of["value"] if as_of else None}
    except Exception:
        return JSONResponse({"ok": False, "database": "unreachable"}, status_code=503)


@app.post("/role", include_in_schema=False)
def switch_role(role: str = Form(...)):
    """The role switcher. Each role lands on its own Today page."""
    role = role if role in web.ROLES else web.DEFAULT_ROLE
    response = RedirectResponse(web.ROLES[role][1], status_code=303)
    response.set_cookie("role", role, max_age=60 * 60 * 24 * 30, samesite="lax")
    return response


@app.post("/reset", include_in_schema=False)
def reset_demo():
    with db.get_conn() as conn:
        _, message = demo.reset(conn)
    return RedirectResponse(f"/?flash={quote(message)}", status_code=303)


GO_TO = [("Today", "/today"), ("Headcount", "/"), ("Budget", "/budget"), ("Planning", "/planning"), ("Forecast", "/forecast"),
         ("Org explorer", "/org"), ("Requests", "/requests"), ("Exceptions", "/exceptions"), ("Data health", "/health"),
         ("Request a backfill", "/backfill/new"), ("Styleguide", "/styleguide"), ("About", "/about")]


@app.get("/palette", response_class=HTMLResponse, include_in_schema=False)
def palette(request: Request, q: str = ""):
    """The ⌘K palette: jump to a page, a person, a position or an org, or run an action."""
    q = q.strip()[:60]
    needle = q.lower()
    go = [(label, href) for label, href in GO_TO
          if needle in label.lower() and web.FEATURES.get(href.strip("/"), True)]
    people, orgs, backfills = [], [], []
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        if len(q) >= 2:
            like = f"%{q}%"
            people = db.query(conn, """
                SELECT ps.position_id, ps.position_code, ps.bucket, pe.full_name, o.name AS org_name
                FROM v_position_status ps
                JOIN orgs o ON o.id = ps.org_id
                LEFT JOIN people pe ON pe.id = ps.person_id
                WHERE ps.position_code ILIKE %(like)s OR pe.full_name ILIKE %(like)s
                ORDER BY (pe.full_name ILIKE %(prefix)s) DESC, pe.full_name NULLS LAST, ps.position_code
                LIMIT 6""", {"like": like, "prefix": f"{q}%"})
            orgs = db.query(conn, "SELECT id, name, level FROM orgs WHERE name ILIKE %s ORDER BY (level = 'team'), name LIMIT 5", (like,))
            if permissions.can_request_backfill(ctx["role"]):
                backfills = db.query(conn, """
                    SELECT k.person_id, k.full_name, k.team_name FROM v_backfill_candidates k
                    JOIN v_org_closure c ON c.org_id = k.org_id
                    WHERE c.ancestor_id = %s AND k.full_name ILIKE %s ORDER BY k.full_name LIMIT 3""",
                    (permissions.backfill_scope(ctx), like))
    roles = [(key, label) for key, (label, _) in web.ROLES.items()
             if key != ctx["role"] and (not needle or needle in f"switch role to {label}".lower())]
    ctx.update(q=q, go=go if needle else go[:7], people=people, orgs=orgs, backfills=backfills, roles=roles)
    return web.render(request, "_palette_results.html", ctx)


@app.get("/styleguide", response_class=HTMLResponse, include_in_schema=False)
def styleguide(request: Request):
    """Every component, in both themes, side by side."""
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
    return web.render(request, "styleguide.html", ctx)


@app.get("/about", response_class=HTMLResponse, include_in_schema=False)
def about(request: Request):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        ctx["counts"] = db.one(conn, """
            SELECT (SELECT count(*) FROM people WHERE end_date IS NULL OR end_date >= today()) AS people,
                   (SELECT count(*) FROM positions) AS positions,
                   (SELECT count(*) FROM orgs WHERE level = 'team') AS teams""")
        ctx["checks"] = len(CHECKS)
    return web.render(request, "about.html", ctx)
