# Decisions

A running log. Each entry: the choice, the alternative, and why.

## Data model

**1. Position status is derived in a view, not stored in a column.**
*Alternative:* a `status` column on `positions`.
*Why:* a stored status has to be updated every time a person or a staffing request changes, and one missed update makes it wrong. The view `v_position_status` reads the facts (is there a person, is there an active request) so it is always right.

**2. Statuses are `text` with `CHECK` constraints, not Postgres enums.**
*Alternative:* `CREATE TYPE ... AS ENUM`.
*Why:* a CHECK is visible right in the table definition and is one line to change. Enums are harder to alter and add nothing here.

**3. The org chart is a simple parent pointer plus a recursive "closure" view.**
*Alternative:* store the SVP and VP on every row, or keep a separate closure table.
*Why:* `parent_id` is the single source of truth, so a reorg is one update. `v_org_closure` pairs every org with each of its ancestors, which turns any roll-up into a plain join and group-by.

**4. Plans are versioned, locked by a trigger, and verified by a hash.**
*Alternative:* trust people not to edit the plan.
*Why:* the trigger stops accidental edits. The hash catches the case where someone disables the trigger or edits around it. Prevention and detection are two different controls.

**5. `request_events` is append-only (a trigger blocks update and delete).**
*Alternative:* keep only `updated_at` on the request.
*Why:* an audit trail you can edit is not an audit trail.

**6. One active staffing request per position, and one active backfill per position, enforced by partial unique indexes.**
*Alternative:* check in application code.
*Why:* the database enforces it even if a second code path is added later. It also guarantees the status view never double counts a seat.

**7. A "mis-coded" position is one whose org and job family have no line in the current plan.**
*Alternative:* add a "home job family" column to orgs.
*Why:* the plan already says which job families each org is funded for, so no new column is needed and the rule stays in sync with the plan.

**8. Negative headcount is a position type.**
*Alternative:* let filled exceed approved and infer the overage.
*Why:* an over-hire is a decision someone made. Recording it as its own seat (type `negative`) makes it visible, countable and clickable, and it nets against the same org's usable open.

**9. `recruiter_coverage` and `exception_resolutions` were added to the original model.**
*Why:* auto-assignment needs to know which job family each recruiter hires for, and "mark resolved" needs somewhere to record who cleared an exception without hiding the underlying data.

**10. Snapshots store rolled-up totals for every org, every day.**
*Alternative:* store only team-level rows and roll up on read.
*Why:* this mirrors what a nightly export from a real tool looks like, and it gives the roll-up check something real to verify (children plus the seats held directly must equal the parent).

## Logic

**11. Business logic is in SQL views; Python only routes and renders.**
*Alternative:* compute usable open and exceptions in Python.
*Why:* anyone who knows SQL can open a view and check the rule. The same view feeds the page, the JSON API and the tests.

**12. The "business day" is defined once, in the SQL function `today()`: US Eastern, starting at 6 AM.**
*Alternative:* `current_date`, which is UTC on a hosted database.
*Why:* "90 days old" and "overnight" should not flip at 7 PM Eastern. The day starts at 6 AM because that is when the snapshot loads, so the page never claims data from a time that has not happened yet.

**13. Each data check is a view with the same six columns.**
*Alternative:* six Python functions.
*Why:* running the checks is one `INSERT ... SELECT` from `v_check_all`, and adding a check is adding a view.

**14. Reserve is counted wherever it sits, but only SVP-level reserve is "in the right place".**
*Why:* reserve parked on a team still is not hireable, so it must come out of usable open. It also shows up as an exception so someone moves it.

## Workflow

**15. One function, `transition()`, owns every status change.**
*Alternative:* update the status from each route.
*Why:* one place to check the move is legal, one place that writes the audit row, one transaction.

**16. Recruiters are auto-assigned to the least-loaded recruiter for the job family.**
*Alternative:* a recruiting manager assigns by hand.
*Why:* that hand-off is pure waiting time in the manual process. Load is active staffing requests plus backfills assigned but not yet opened.

**17. The backfill reuses the departing person's position instead of creating a new one.**
*Why:* a backfill does not change approved headcount, so usable open should not move. Reusing the seat makes that true by construction.

## App

**18. Server-rendered pages (FastAPI + Jinja2 + HTMX), no front-end framework.**
*Alternative:* a React single-page app.
*Why:* less code, faster first load, and every page works as a plain link. HTMX handles the few in-place updates (approve, resolve).

**19. Roles are simulated with a switcher, not real logins.**
*Why:* a visitor can see all four views in a minute. Each role maps to one named demo person.

**20. Synthetic data is rebuilt relative to today, and refreshes itself once a day.**
*Alternative:* fixed dates.
*Why:* "2 days waiting" and "data as of this morning" stay true whenever someone opens the link. The random seed is fixed, so the people, positions and planted errors are identical every time.

**21. "Reset demo" reruns the whole seed in one transaction.**
*Alternative:* undo only the visitor's changes.
*Why:* simplest thing that is always correct. It takes a couple of seconds and is rate-limited.

**22. An exception's owner is the VP over the seat.**
*Alternative:* the team lead.
*Why:* about 170 team leads would make 170 tiny lists. Twelve VPs gives each owner a list they can work through, and the team is still shown on every row.

**23. "Mark resolved" records who dealt with it; it does not hide or change the row.**
*Alternative:* delete or suppress the exception.
*Why:* exceptions are derived from the data. The honest way to make one disappear is to fix the source row, and a test shows that doing so clears it.

**24. A passing check still stores its rows.**
*Alternative:* store only failures.
*Why:* "13 orgs tested, all passed" with the numbers shown is more convincing than a green tick, and it gives every check a click-through.

**25. People who can be backfilled are people with an end date who still hold a seat.**
*Alternative:* add a "previous holder" column to positions.
*Why:* it needs no new column, and the seat to reuse is simply the one they are sitting in. It also means a ghost fill can be turned into a backfill.

**26. A new hire recorded through the workflow starts in two weeks.**
*Why:* that is realistic, and it keeps this morning's snapshot tie-out true. The seat counts as filled from the accepted offer.

**27. The waterfall runs sideways on a phone, and the whole lane of each bar is clickable.**
*Why:* six labels do not fit under six bars at 375px, and the small bars would be hard to tap.

**28. Tests run in a throwaway Postgres schema.**
*Alternative:* a separate test database, or mocking the database.
*Why:* the logic is SQL, so the tests need a real Postgres. A fresh schema per run isolates them from the app's data on the same database, locally and in CI.

**29. The production connection string is a Cloud Run environment variable.**
*Alternative:* Secret Manager.
*Why:* the data is synthetic and this keeps the demo inside free tiers with no extra service to enable. A real deployment would use Secret Manager.

**30. A requester can only ask for backfills in their own org.**
*Why:* it matches how the process works, and it means the request always routes to the right VP.
