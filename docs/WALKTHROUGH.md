# Walkthrough

A guided read of how Headcount Desk works: what to click, how a request moves through the code, the schema in plain English, the main design questions, and what is still rough.

**Live:** https://headcount-desk-yf5labkepq-ue.a.run.app · **Read next:** [SCHEMA.md](SCHEMA.md), [DESIGN.md](DESIGN.md), [DECISIONS.md](DECISIONS.md)

---

## 1. The five-minute tour

1. Open the live site. You land on **Headcount** as the Research SVP. The big number is usable open. The bar shows where the approved headcount goes; the second bar zooms into the seats nobody is in. Click a segment: you get the rows behind it.
2. Click a position code. It opens in a **side drawer**; the list stays where it was. Press Esc.
3. Press **⌘K** (or `/`), type a name, press Enter. That is the command palette.
4. Open **Budget**. The answer is a percentage of budget, with run-rate and committed underneath. Two VP orgs are over on purpose.
5. Use the role switcher (top right) to become the **Requester**, request a backfill, then switch to **VP**. You land on **Today**: an approval inbox where each card shows what the seat costs and where the org stands against its budget. Approve one.
6. Open **Planning** as the VP. Press + or −; the dollars and the room left update at once. Submit. Switch to **SVP**, open the plan, approve fewer than asked, then lock the cycle. A new plan version appears and this year's numbers do not move.
7. Open **Forecast**. Read the method note at the bottom, then click "Expected hires" to see each open request and its odds.
8. Open **Data health** as the Resource Manager and follow the anomaly to its rows.
9. Toggle dark mode (the moon), and open `/styleguide`.

## 2. How a request flows through the code

### Reading a page: `GET /budget?org=2`

```
browser ──► app/security.py: middleware          CSRF cookie, security headers, rate limit, JSON log line
        ──► app/routes/budget.py: budget()
              db.get_conn()                      one pooled connection (app/db.py)
              web.page_context()                 role, persona, "data as of" (app/web.py)
              web.sorting()                      ?sort= and ?dir= mapped through an allow-list
              SELECT * FROM v_budget WHERE org_id = 2
              SELECT * FROM v_budget WHERE parent_id = 2 ORDER BY ...
        ──► templates/budget.html ──► HTML
```

The route does no arithmetic. `v_budget` (in `db/views/30_budget.sql`) is built in the same two steps as headcount: `v_budget_direct` costs the seats that sit directly in each org, then `v_budget` joins `v_org_closure` to roll every org's numbers up to its ancestors and applies the formula. `v_usable_open` works the same way in `db/views/10_core.sql`.

Add `&format=csv` to the same URL and the same rows come back as a file. Sorting and filters are in the URL, so what you see is what you export.

### Changing something: approving a backfill

```
browser ── POST /requests/1042/approve (with the CSRF token) ──► security.csrf_protect
        ──► app/routes/backfill.py: approve()
              permissions.check_approve()        only the VP over this seat; otherwise 403
              app/workflow.py: approve()
                transition(→ vp_approved)        legal move? update status, insert request_events row
                pick the recruiter from v_recruiter_load (lowest load, same job family)
                transition(→ recruiter_assigned) actor = the system
              commit (the `with db.get_conn()` block ends)
        ──► templates/_request_card_done.html ──► HTMX swaps just that card
```

Four things to notice:

- **`transition()` is the only place a status changes.** It reads the row `FOR UPDATE`, checks `ALLOWED[current]`, updates, and inserts the audit row. If the move is not allowed it raises and nothing is written. `app/planning.py` has its own `transition()` built the same way.
- **Permission is a separate question from legality.** `app/permissions.py` decides *who* may act; the workflow decides *whether the move exists*. Both run on the server.
- **Everything in one request is one transaction.** `db.get_conn()` commits when the block ends and rolls back on an error.
- **HTMX is why the page does not reload.** The button has `hx-post` and `hx-target`; the server returns a small piece of HTML. There are no inline scripts anywhere: `app/static/app.js` wires everything by data attributes, which is what lets the Content Security Policy be strict.

### Locking the annual plan

`planning.lock_cycle()` inserts a new `plan_versions` row for FY28, writes one line per VP org and job family (this year plus the approved change), copies the lines above VP level, then sets `locked_at` and the fingerprint. From that moment the existing trigger protects it. `v_current_plan` ignores it until its `effective_from` date, so every page keeps showing this year.

### Migrations

`scripts/migrate.py` applies any file in `db/migrations/` that is not yet in the `schema_migrations` table, then drops and rebuilds every view from `db/views/`. Tables change once and are recorded; views are code and are simply rebuilt.

## 3. The schema in plain English

- **`orgs`** is the org chart, as a tree. Company → SVP → VP → director → team.
- **`people`** is everyone, past and present. A future `end_date` means they have given notice.
- **`positions`** is the list of seats, each with a job family, level and location. A seat with a `person_id` is filled. `reserve` seats are held back by an SVP; `negative` seats are over-hires.
- **`staffing_requests`** means a recruiter is working to fill a seat. Closed ones are the history the forecast learns from.
- **`plan_versions` and `plan_lines`** are approved headcount and cost, by org and job family. A version is locked and never changes; it has a fiscal year and a date it takes effect.
- **`cost_rates`** is the rate card: what one seat costs a year, by job family, level and location.
- **`fiscal_years`** is the calendar.
- **`backfill_requests`** and **`request_events`**: a manager asking to replace someone, and the audit trail of that request.
- **`planning_cycles`, `planning_envelopes`, `plan_submissions`, `plan_submission_lines`, `planning_events`**: one annual planning round, each SVP's limit, each VP's ask by job family, and the audit trail.
- **`daily_snapshots`**: one row of totals per org per day, so today can be compared with yesterday.
- **`check_runs` and `check_results`**: what the data checks found.
- **`exception_resolutions`**: someone marking a data problem as dealt with. The problems themselves are derived by `v_exceptions`.

The ideas that hold it together:

1. **Derived status.** "Open" is never stored, so it can never be stale.
2. **Locked, versioned plans with an effective date.** A trigger prevents edits; a fingerprint detects them; next year's plan does not disturb this year's.
3. **One function per workflow.** Legal moves only, always with an audit row.
4. **Snapshots.** You cannot tie out to yesterday unless you kept yesterday.
5. **Cost is a rate, not a salary.** An empty seat has a cost, which is what makes budgeting and planning possible.

## 4. Design questions, answered

**1. What is the shape of the schema?**
Three groups of tables. The org chart, people and positions are the current state. The plan (versioned, locked, costed) is what we are allowed to have. Usable open and budget variance are the plan minus the current state. Then the things that change over time: backfills and planning asks with append-only event logs, daily snapshots, check results. Business rules sit in views on top, so the tables stay simple.

**2. Why is "open" derived instead of stored?**
A stored status is a second copy of the truth. A seat is filled if someone is in it, committed if a recruiter has an active request on it, and open otherwise. A view reads the facts, so it cannot drift.

**3. How do I know the numbers are accurate?**
Every number opens the rows behind it. Eight checks run every morning: a tie-out to yesterday plus hires minus exits, a roll-up check, referential checks, a ratio check for sudden swings, a fingerprint check on the locked plan, an exception-volume check, a budget check and a check that every seat can be costed. And the formulas are pinned by small fixtures worked out by hand in the tests.

**4. What stops someone editing the plan?**
A trigger on `plan_lines` rejects any change once the version is locked, so a change has to be a new version. At lock time a hash of the lines is stored and a daily check recomputes it. The trigger is prevention; the hash is detection.

**5. How is "are we on budget" worked out?**
Projected spend is run-rate plus committed. Run-rate is the annual cost of every seat with a person in it. Committed is the open seats a recruiter is working, costed only for the months left in the fiscal year, because a seat costs nothing until someone starts. That is compared with the approved cost in the plan. Reserve and open seats nobody is recruiting for are left out.

**6. How does the annual planning cycle work, and how would a second approval level be added?**
Each VP's submission moves draft → submitted → approved, or back through sent-back. The allowed moves are a small dictionary in `planning.py`. A second level would be one more status and one more entry in that dictionary; if approvals needed to vary by org or by size, an `approval_steps` table (submission, step, approver, decision) would replace the single status.

**7. Why does the forecast show a range, and where do the numbers come from?**
Because it is an estimate. Each open request counts for its chance of being filled by quarter end, taken from how long past requests actually took, conditional on how long this one has already been open. Exits use the attrition seen in the last 60 days. Treating hires as independent coin flips and exits as a count of rare events gives a spread, and the page shows the 25th to 75th percentile. It is all in `db/views/50_forecast.sql`, and the method is printed on the page.

**8. What happens in a reorg, when positions move between orgs?**
Today `positions.org_id` is the current org, so a reorg is an update and history is lost. The fix is effective dating: a `position_org_assignments` table with valid-from and valid-to. Snapshots already protect past totals, because they were stored at the time.

**9. Would this scale to 50,000 positions?**
The hot queries are indexed (see migration 002). The first thing to change would be `v_usable_open` and `v_budget`: make them materialized views refreshed after each load, since people read numbers as of this morning anyway. Search would need a trigram index. The org closure can become a real table maintained on reorg.

**10. What do "simulated roles" mean for security?**
Who you are is a cookie, so it is not authentication. What each role may do is real: every write goes through `app/permissions.py` on the server, writes need a CSRF token, and the tests prove that the wrong role gets a 403 and nothing changes. Swapping the cookie for real sign-in would not change those rules.

## 5. What's rough, and what to fix next

1. **Identity is simulated.** There is no sign-in. The permission rules are enforced, but anyone can pick any role.
2. **People who leave are not vacated automatically.** A seat is vacated when the recruiter opens the request and the last day has passed. A nightly job should do it. Until then a departed person shows up as a ghost fill, which the Exceptions page catches.
3. **The forecast ignores what is already known.** Notice already given and offers already signed are treated like any other exit or open request. Using them directly would tighten the range.
4. **Attrition is one rate per SVP org,** and time to fill is one distribution for the whole company. Splitting by job family and level would be more accurate and needs more history.
5. **The locked FY28 plan stops at VP level.** Splitting it down to teams is not built.
6. **Budget is annual run-rate against annual plan.** It does not track actual spend to date, so an org that hired late looks the same as one that hired early.
7. **"Mark resolved" is a note, not a fix.** A real version would offer the fix itself (vacate, recode, close).
8. **Snapshots are generated, not captured.** The 60 days of history are built by walking backwards from today.
9. **The rate limit is per instance and in memory.** Fine for one or two instances; a shared store would be needed beyond that.
10. **The daily refresh rebuilds everything** on the first visit of a new day (about three seconds). It keeps the demo current; a real system would load, not rebuild.
