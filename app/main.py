"""Headcount Desk: the FastAPI app. Routes live in app/routes/."""

from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import db, demo, web
from app.routes import overview

app = FastAPI(
    title="Headcount Desk",
    description="Usable open headcount, a backfill workflow and data checks for a fictional AI lab. All data is synthetic.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=web.APP_DIR / "static"), name="static")
app.include_router(overview.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.post("/role", include_in_schema=False)
def switch_role(role: str = Form(...)):
    """The role switcher. Each role lands on the page that matters most to it."""
    role = role if role in web.ROLES else web.DEFAULT_ROLE
    response = RedirectResponse(web.ROLES[role][1], status_code=303)
    response.set_cookie("role", role, max_age=60 * 60 * 24 * 30, samesite="lax")
    return response


@app.post("/reset", include_in_schema=False)
def reset_demo():
    with db.get_conn() as conn:
        _, message = demo.reset(conn)
    return RedirectResponse(f"/?flash={quote(message)}", status_code=303)


@app.get("/search", response_class=HTMLResponse, include_in_schema=False)
def search(request: Request, q: str = ""):
    """Header search: people by name, positions by code."""
    q = q.strip()
    results = []
    if len(q) >= 2:
        with db.get_conn() as conn:
            results = db.query(conn, """
                SELECT ps.position_id, ps.position_code, ps.bucket, pe.full_name, o.name AS org_name
                FROM v_position_status ps
                JOIN orgs o ON o.id = ps.org_id
                LEFT JOIN people pe ON pe.id = ps.person_id
                WHERE ps.position_code ILIKE %(code)s OR pe.full_name ILIKE %(name)s
                ORDER BY (pe.full_name ILIKE %(prefix)s) DESC, pe.full_name NULLS LAST, ps.position_code
                LIMIT 8""", {"code": f"%{q}%", "name": f"%{q}%", "prefix": f"{q}%"})
    return web.render(request, "_search_results.html", {"results": results, "q": q})


@app.get("/about", response_class=HTMLResponse, include_in_schema=False)
def about(request: Request):
    with db.get_conn() as conn:
        ctx = web.page_context(request, conn)
        ctx["counts"] = db.one(conn, """
            SELECT (SELECT count(*) FROM people WHERE end_date IS NULL OR end_date >= today()) AS people,
                   (SELECT count(*) FROM positions) AS positions,
                   (SELECT count(*) FROM orgs WHERE level = 'team') AS teams""")
    return web.render(request, "about.html", ctx)
