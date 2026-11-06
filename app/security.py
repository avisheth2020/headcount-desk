"""Request safety: CSRF, security headers, write rate limits and JSON request logs.

Identities are simulated, but the rules a real deployment needs are here and tested.
"""

import json
import logging
import os
import secrets
import sys
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

CSRF_COOKIE = "csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
WRITES_PER_MINUTE = int(os.environ.get("RATE_LIMIT_WRITES", "60"))

# Everything is served from this origin: no CDNs, no inline scripts.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
# FastAPI's built-in API docs page loads its own assets from a CDN.
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
            "frame-ancestors 'none'")

log = logging.getLogger("headcount")
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False

_writes: dict[str, deque] = defaultdict(deque)     # client -> timestamps of recent writes


def client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


def too_many_writes(request: Request) -> bool:
    """A sliding one-minute window per client. In memory, so it is per instance."""
    now, window = time.monotonic(), _writes[client_id(request)]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= WRITES_PER_MINUTE:
        return True
    window.append(now)
    return False


async def csrf_protect(request: Request) -> None:
    """Every write must echo the CSRF cookie, in a header (HTMX) or a hidden form field."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    sent = request.headers.get("x-csrf-token")
    if sent is None:
        sent = (await request.form()).get("csrf_token")
    if not cookie or not sent or not secrets.compare_digest(str(cookie), str(sent)):
        raise HTTPException(403, "Your session has expired. Reload the page and try again.")


async def middleware(request: Request, call_next) -> Response:
    started = time.perf_counter()
    request.state.csrf = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
    if request.method not in SAFE_METHODS and too_many_writes(request):
        response: Response = JSONResponse({"detail": "Too many changes in a minute. Wait a moment and try again."}, status_code=429)
    else:
        response = await call_next(request)

    if CSRF_COOKIE not in request.cookies:
        response.set_cookie(CSRF_COOKIE, request.state.csrf, max_age=60 * 60 * 24 * 30, samesite="lax",
                            httponly=False, secure=request.url.scheme == "https")
    docs = request.url.path in ("/docs", "/redoc", "/openapi.json")
    response.headers["Content-Security-Policy"] = DOCS_CSP if docs else CSP
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    if not request.url.path.startswith("/static/"):
        log.info(json.dumps({
            "severity": "ERROR" if response.status_code >= 500 else "INFO",
            "method": request.method, "path": request.url.path, "status": response.status_code,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "role": request.cookies.get("role", "svp"), "client": client_id(request),
        }))
    return response
