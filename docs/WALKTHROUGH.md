# Walkthrough

A ten-minute guided read of how Headcount Desk works: what to click, how a request moves through the code, the schema in plain English, the main design questions, and what is still rough.

**Live:** https://headcount-desk-yf5labkepq-ue.a.run.app · **Read next:** [SCHEMA.md](SCHEMA.md), [DECISIONS.md](DECISIONS.md)

---

## 1. The two-minute tour

1. Open the live site. You land on **Headcount** as the Research SVP. The big number is usable open. Click a bar in the chart, or any number in the table: you get the rows behind it.
2. Click **Request a backfill** on the Requests page (or step 2 on the "Try this" card). Pick someone who is leaving, type a reason, submit. You land on the tracker with a stepper.
3. Use the "Switch to VP" tip. You are now Priya Shah with an approval inbox. Click **Approve**. The card updates in place and a recruiter is assigned automatically.
4. Switch to **Recruiter**, open the staffing request, then mark it filled. Look at the timeline: five events, each with a person and a time.
5. Open **Exceptions** as the Resource Manager. Mark one resolved, then press Undo on the toast.
6. Open **Data health**. One check needs a look. Follow "See the rows behind this" to the snapshot table and find the row that jumped.

## 2. How a request flows through the code

### Reading a page: `GET /` (Headcount)

```
browser ── GET /?org=2 ──► app/routes/overview.py: headcount()
                              │  db.get_conn()            one pooled connection (app/db.py)
                              │  web.page_context()       role, persona, "data as of" (app/web.py)
                              │  SELECT * FROM v_usable_open WHERE org_id = 2
                              │  SELECT * FROM v_usable_open WHERE parent_id = 2
                              ▼
                           templates/headcount.html  ──► HTML back to the browser
```

The route does no arithmetic. `v_usable_open` (in `db/views.sql`) is built from three smaller views, and you can read them top to bottom:

1. `v_position_status` puts each seat in exactly one bucket: reserve, negative, filled, committed, or open with no request.
2. `v_headcount_direct` counts buckets and approved headcount for the seats that sit directly in each org.
3. `v_usable_open` joins that to `v_org_closure` (every org paired with each of its ancestors) and sums, so each org gets its whole subtree. Then it applies the formula.

Clicking a number goes to `/positions?org=2&bucket=committed`, which lists rows from the same `v_position_status` view. That is why the list always matches the number.

### Changing something: approving a backfill

```
browser ── POST /requests/1042/approve ──► app/routes/backfill.py: approve()
                                              │
                                              ▼
                               app/workflow.py: approve(conn, 1042, vp_id)
                                 transition(→ vp_approved)        checks the move is legal,
                                                                  updates status, inserts a
                                                                  request_events row
                                 pick recruiter from v_recruiter_load (lowest load, same job family)
                                 transition(→ recruiter_assigned) actor = the system
                                              │
                                 commit (the route's `with db.get_conn()` block ends)
                                              ▼
                               templates/_request_card_done.html  ──► HTMX swaps just that card
```

Three things to notice:

- **`transition()` is the only place a status changes.** It reads the row `FOR UPDATE`, checks `ALLOWED[current]`, updates, and inserts the audit row. If the move is not allowed it raises and nothing is written.
- **Everything in one request is one transaction.** `db.get_conn()` commits when the block ends and rolls back on an error, so you never get "approved but no recruiter".
- **HTMX is why the page does not reload.** The button has `hx-post` and `hx-target`; the server returns a small piece of HTML and HTMX swaps it in. The page title updates through an "out of band" swap in the same response.

### Running the checks

`app/checks.py: run_checks()` is three statements: insert a `check_runs` row, `INSERT INTO check_results SELECT ... FROM v_check_all`, then count how many checks passed. Each check is its own view in `db/checks.sql` with the same six columns.

## 3. The schema in plain English

- **`orgs`** is the org chart, as a tree. Each row points to its parent. Company → SVP → VP → director → team.
- **`people`** is everyone, past and present. No `end_date` means active. A future `end_date` means they have resigned and are working their notice.
- **`positions`** is the list of seats. A seat with a `person_id` is filled. Two special types: `reserve` (an SVP is holding it back) and `negative` (an over-hire with no approved headcount behind it).
- **`staffing_requests`** means a recruiter is working to fill a seat. At most one active request per seat.
- **`plan_versions` and `plan_lines`** are the approved headcount, by org and job family. A version is locked, and then never changes. A refresh is a new version.
- **`backfill_requests`** is a manager asking to replace someone. **`request_events`** is its audit trail: one row per status change, never edited.
- **`daily_snapshots`** is one row of totals per org per day. It exists so today can be compared with yesterday.
- **`check_runs` and `check_results`** are what the data checks found, one row per org tested.
- **`exception_resolutions`** records that someone has dealt with a data problem. The problems themselves are not stored; they are derived by `v_exceptions`.

The four ideas that hold it together:

1. **Derived status.** "Open" is never stored, so it can never be stale.
2. **Locked, versioned plans.** A trigger prevents edits; a fingerprint detects them.
3. **One function for workflow changes.** Legal moves only, always with an audit row.
4. **Snapshots.** You cannot tie out to yesterday unless you kept yesterday.

## 4. Ten design questions, answered

**1. What is the shape of the schema?**
There are three groups of tables. First the org chart, people and positions: that is the current state. Second the plan, which is versioned and locked: that is what we are allowed to have. Usable open is the plan minus the current state. Third, the things that change over time: backfill requests with an append-only event log, daily snapshots, and check results. Business rules sit in views on top, so the tables stay simple.

**2. Why is "open" derived instead of stored?**
A stored status is a second copy of the truth. A seat is filled if someone is in it, committed if a recruiter has an active request on it, and open otherwise. If that were a column, every hire, exit and request would have to update it, and the first missed update would make the number wrong. A view reads the facts, so it cannot drift.

**3. How do I know the numbers are accurate?**
Three ways. Every number on the page opens the rows behind it, so anyone can spot-check. Six checks run every morning: a tie-out to yesterday plus hires minus exits, a roll-up check, referential checks, a ratio check for sudden swings, a fingerprint check on the locked plan, and an exception-volume check. And the formula itself is pinned by a ten-position test worked out by hand (`tests/test_usable_open.py`).

**4. What stops someone editing the plan?**
Two controls. A trigger on `plan_lines` rejects any insert, update or delete once the version is locked, so a change has to be a new version. And at lock time a hash of the lines is stored; a daily check recomputes it. The trigger is prevention. The hash is detection, for the case where someone switches the trigger off.

**5. What happens in a reorg, when positions move between orgs?**
Today `positions.org_id` is the current org, and a reorg is an update to `orgs.parent_id` or to the position. That loses history. The fix is effective dating: a `position_org_assignments` table with position, org, valid-from and valid-to. The current-state views filter to the row that is valid today, and historical reports can ask "as of" any date. Snapshots already protect past totals, because they were stored at the time.

**6. How would a second level of approval be added?**
The allowed moves are a small dictionary in `workflow.py`, and the approver is one column. For two levels, add a status such as `svp_approved` and one more entry in that dictionary. If approvals needed to vary by org or by cost, move to an `approval_steps` table: request, step number, approver, decision, decided-at. The request advances when every required step is approved. The audit trail does not change.

**7. What would an opex request flow look like?**
The same shape as backfills. `opex_requests` with requester, cost center, vendor, amount, period and status. `opex_request_events` as the append-only log. `budget_lines` by cost center and account, versioned and locked like the headcount plan. The equivalent of usable open is budget remaining: approved budget, minus actuals, minus commitments such as approved requests and open purchase orders. Checks would tie actuals out to the ledger.

**8. Would this scale to 50,000 positions?**
It is indexed on the columns the views join on: `positions.org_id`, `positions.person_id`, and the partial unique index on active staffing requests. At 50,000 positions the views are still fast. If the roll-up became slow, `v_usable_open` could become a materialized view refreshed after each load, since most people read numbers as of this morning anyway. The org closure is the piece to watch, and that can be a real table maintained on reorg.

**9. Why SQL views and not Python?**
The rules are the product. Someone in finance can open `views.sql`, read the usable-open formula in one place, and disagree with it. The same view feeds the page, the API and the tests, so there is one definition. Python is left with routing and rendering.

**10. Why does usable open differ from what the position tool shows as open?**
The tool lists every empty seat with no request. Some of those are stale records the plan does not fund. For the Research SVP the tool shows about twice as many open seats as the plan supports, and the Exceptions page explains the gap. Related: negative headcount is an over-hire, someone in a seat the plan never approved. It is recorded as its own seat type, so it is visible and it uses up one of that org's usable seats.

## 5. What's rough, and what to fix next

Honest list, most important first.

1. **People who leave are not vacated automatically.** A seat is vacated when the recruiter opens the request, and only if the person's last day has passed. In real life a nightly job would vacate seats on the last day. Without it, a departed person shows up as a ghost fill, which the Exceptions page does catch.
2. **"Mark resolved" is a note, not a fix.** It records who dealt with an exception. The underlying row is unchanged, so the exception still counts toward the gap on the Headcount page. A real version would offer the fix itself (vacate, recode, close).
3. **Roles are a cookie.** There are no logins and no permissions. Anyone can switch to VP and approve. Fine for a demo; the first thing to replace in a real system.
4. **Snapshots are generated, not captured.** The 60 days of history are built by walking backwards from today. A real system would write a snapshot every night from `v_usable_open`.
5. **The daily refresh rebuilds everything.** On the first visit of a new day the app reseeds (about three seconds). It keeps "data as of this morning" true, but it is a demo trick.
6. **Reserve parked on a team makes that VP look short.** The plan funds it at the SVP, so the SVP total is right, but the VP row is understated by the misplaced seats. The exception explains it; the table does not.
7. **The waterfall's small bars are small.** Filled is about 93% of approved, so the last four bars are thin. The value labels and the math row carry the detail. A zoomed "last 150 seats" view would read better.
8. **No header search on phones.** It is hidden under 720px to keep the top bar clean.
9. **Keyboard focus after an inline action.** After Approve or Mark resolved, focus falls back to the page. It should move to the next card.
10. **About-page links point at GitHub.** "Read the PRD" and "Code on GitHub" only work for people who can see the repository.
