"""End-to-end tests in a real browser (Playwright), against a real server.

These run last (the file name sorts after the others) because they commit real
changes; the data is rebuilt afterwards. They cover the main flows, the
keyboard-and-drawer plumbing, both themes, and accessibility (axe-core).
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from app import db
from tests.conftest import SEEDED_SCHEMA, TEST_URL

playwright = pytest.importorskip("playwright.sync_api")
axe_module = pytest.importorskip("axe_playwright_python.sync_playwright")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url(manifest):
    """Start the app on a free port, pointed at the seeded test schema."""
    port = free_port()
    env = {**os.environ, "DATABASE_URL": TEST_URL, "DB_SCHEMA": SEEDED_SCHEMA, "RATE_LIMIT_WRITES": "100000"}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        server.kill()
        pytest.fail("the app did not start")
    yield url
    server.terminate()
    server.wait(timeout=10)
    from scripts.seed import seed
    with db.connect(TEST_URL, schema=SEEDED_SCHEMA) as conn:      # put the data back
        seed(conn)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def new_page(browser, base_url, role="svp", theme="light", width=1440, height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    if theme:
        ctx.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")
    ctx.add_cookies([{"name": "role", "value": role, "url": base_url}])
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
    return page


def switch_role(page, role):
    page.locator(".role-switch summary").click()
    page.locator(f".role-menu button[value={role}]").click()
    page.wait_for_load_state("networkidle")


def wait_until(check, timeout=10.0):
    """Poll from Python. (The app's CSP forbids eval, so the browser cannot be asked to poll.)"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError("condition was not met in time")


def test_backfill_flow_end_to_end(browser, base_url):
    """Requester submits, VP approves in place, recruiter opens and fills. Five audit events."""
    page = new_page(browser, base_url, role="requester")
    page.goto(base_url + "/backfill/new", wait_until="networkidle")
    name = page.locator(".suggest button").first.inner_text().split("\n")[0].strip()
    page.fill("#who", name[:5])
    page.wait_for_selector("#who-results button")
    page.locator("#who-results button").first.click()
    page.wait_for_selector("#form-body form")
    assert "a year, already in the budget" in page.locator("#form-body").inner_text()      # dollars at the decision
    page.fill("#why", "End-to-end test: needed to keep the evaluation work on schedule")
    page.locator(".seg label", has_text="Urgent").click()
    page.locator("#form-body button[type=submit]").click()
    page.wait_for_load_state("networkidle")
    assert "/requests/" in page.url and "Waiting on" in page.content()
    request_url = page.url.split("?")[0]
    request_id = request_url.rsplit("/", 1)[1]

    switch_role(page, "vp")                                   # lands on Today, with the approval inbox
    assert "/today" in page.url
    assert "4 requests need your approval" in page.locator("#inbox-title").inner_text()
    card = page.locator(f"#req-{request_id}")
    assert "of budget" in card.locator(".money-line").inner_text()
    card.locator("[data-approve]").click()
    page.wait_for_selector(f"#req-{request_id}.resolved")
    assert "3 requests need your approval" in page.locator("#inbox-title").inner_text()
    assert page.url.endswith("/today")                        # no page reload

    card = page.locator(".req-card:not(.resolved)").first     # rejecting needs a reason
    card.locator(".actions button", has_text="Reject").click()
    card.locator(".reject-form input").fill("End-to-end test: holding until the refresh")
    card.locator(".reject-form button").click()
    page.locator("#inbox-title", has_text="2 requests").wait_for()

    switch_role(page, "recruiter")
    page.locator(f"#req-{request_id} [data-approve]").click()
    page.wait_for_selector(f"#req-{request_id}.resolved")
    page.goto(request_url, wait_until="networkidle")
    page.fill("#hire_name", "Robin Okafor")
    page.locator("button", has_text="Mark filled").click()
    page.wait_for_load_state("networkidle")
    assert page.locator(".timeline li").count() == 5 and "Offer accepted by Robin Okafor" in page.content()
    assert page.errors == []


def test_exceptions_resolve_and_undo(browser, base_url):
    page = new_page(browser, base_url, role="rm")
    page.goto(base_url + "/exceptions", wait_until="networkidle")
    before = page.locator("#progress h2").inner_text()
    first = page.locator(".todo li").first
    row_id = first.get_attribute("id")
    first.locator("button").click()
    page.wait_for_selector(f"#{row_id}.done")
    page.wait_for_selector(".toast")
    assert page.locator("#progress h2").inner_text() != before
    page.locator(".toast button").click()                      # Undo
    page.wait_for_selector(f"#{row_id}:not(.done)")
    assert page.locator("#progress h2").inner_text() == before
    assert page.errors == []


def test_a_requester_cannot_resolve_exceptions(browser, base_url):
    page = new_page(browser, base_url, role="requester")
    page.goto(base_url + "/exceptions", wait_until="networkidle")
    assert page.locator(".todo li button").count() == 0


def test_palette_drawer_and_theme(browser, base_url):
    page = new_page(browser, base_url, theme=None)             # no stored choice: follows the system (light here)
    page.goto(base_url + "/", wait_until="networkidle")
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.locator("[data-theme-toggle]").click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    page.reload(wait_until="networkidle")
    assert page.locator("html").get_attribute("data-theme") == "dark"       # remembered

    page.keyboard.press("Control+k")                           # the command palette
    page.wait_for_selector("body.palette-open #palette-results .palette-item")
    page.keyboard.type("Dana Lee")
    page.wait_for_selector("#palette-results a[data-drawer]")
    page.locator("#palette-results .palette-item.active", has_text="Dana Lee").wait_for()
    page.keyboard.press("Enter")                               # opens the position in the side drawer
    page.wait_for_selector("body.drawer-open #drawer-body h1")
    assert "Dana Lee" in page.locator("#drawer-body h1").inner_text()
    assert page.url.split("#")[0].rstrip("/") == base_url and "#d=/positions/" in page.url    # same page, deep link
    deep_link = page.url
    page.keyboard.press("Escape")
    page.wait_for_selector("body:not(.drawer-open)")

    page.goto(deep_link, wait_until="networkidle")             # the deep link reopens the drawer
    page.wait_for_selector("body.drawer-open #drawer-body h1")
    assert "Dana Lee" in page.locator("#drawer-body h1").inner_text()

    page.goto(base_url + "/", wait_until="networkidle")        # a bridge segment opens its rows
    page.locator(".bar a.seg-committed").first.click()
    page.wait_for_url("**/positions?**bucket=committed**")
    page.locator("thead a", has_text="Cost a year").click()    # sorting lives in the URL
    page.wait_for_url("**sort=cost**")
    assert page.errors == []


def test_org_explorer_expands_and_collapses(browser, base_url):
    page = new_page(browser, base_url)
    page.goto(base_url + "/org", wait_until="networkidle")
    rows = page.locator("#org-tree tbody tr").count()
    toggle = page.locator("#org-tree .tree-toggle[aria-expanded=false]").first.element_handle()   # pin this exact button
    toggle.click()
    wait_until(lambda: page.locator("#org-tree tbody tr").count() > rows)
    opened = page.locator("#org-tree tbody tr").count()
    assert toggle.get_attribute("aria-expanded") == "true"
    toggle.click()
    wait_until(lambda: page.locator("#org-tree tbody tr").count() == rows)
    assert opened > rows
    assert page.errors == []


PAGES = [("/today", "svp"), ("/today", "vp"), ("/today", "recruiter"), ("/today", "rm"), ("/today", "requester"),
         ("/", "svp"), ("/budget", "svp"), ("/org", "svp"), ("/positions?org=2&bucket=committed", "svp"),
         ("/positions/12", "svp"), ("/plan?org=3", "svp"), ("/requests", "vp"), ("/requests/1001", "requester"),
         ("/backfill/new", "requester"), ("/exceptions", "rm"), ("/health", "rm"), ("/health/check/ratio", "rm"),
         ("/health/snapshots?org=3", "rm"), ("/about", "svp"), ("/styleguide", "svp")]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_no_serious_accessibility_violations(browser, base_url, theme):
    """axe-core on every page, in both themes: zero serious or critical violations."""
    from app import web
    extra = [(f"/{name}", "svp") for name in ("planning", "forecast") if web.FEATURES.get(name)]
    problems = []
    for path, role in PAGES + extra:
        page = new_page(browser, base_url, role=role, theme=theme)
        page.goto(base_url + path, wait_until="networkidle")
        results = axe_module.Axe().run(page)
        for v in results.response["violations"]:
            if v["impact"] in ("serious", "critical"):
                problems.append(f"{theme} {path} ({role}): {v['id']} x{len(v['nodes'])} e.g. {v['nodes'][0]['html'][:110]}")
        page.context.close()
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("width", [375, 1024, 1440])
def test_no_page_scrolls_sideways(browser, base_url, width):
    wide = []
    for path, role in PAGES:
        page = new_page(browser, base_url, role=role, width=width, height=812)
        page.goto(base_url + path, wait_until="networkidle")
        if page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") > 0:
            wide.append(path)
        page.context.close()
    assert wide == []
