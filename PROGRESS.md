# Progress

- **Live URL:** https://headcount-desk-yf5labkepq-ue.a.run.app
- **Repo:** https://github.com/avisheth2020/headcount-desk

Last updated: Fri Nov 6, evening ET.

## V3: fewer words, more visuals, work in place (Fri Nov 6)

13 front-end PRs in three waves, plus this docs PR. No schema change; the seed now stores each check's result for the last 13 mornings.

A final QA pass fixed what the suite had not covered: what-ifs now move cost and every row, Submit and Approve save what is on screen first, edits made just after a save are no longer dropped, tables fit from 320px to 1240px, and bulk resolve runs as one write.

| Wave | PRs | Contents |
|---|---|---|
| Clear the noise | 1 to 3 | Seven visible defects fixed. One freshness chip, a visible role switcher, a small tour. Explanatory text cut, one SVG icon set, one vocabulary (Over-hired, Exceptions, Req). |
| Show the numbers | 4 to 8 | Chart kit. Headcount seat map. Budget variance centered on 100%. Forecast chart with what-if sliders. Today as a compact queue with keyboard keys. |
| Work in place | 9 to 13 | Requests pipeline. Planning room gauges and steppers. Exceptions bulk resolve with undo. Data health grid. Org treemap. |

Undoing an approval is not offered: the workflow log is append-only, so a mistaken approval is corrected by a new action, not erased. A one-click "open a req" fix on an exception is also left for later because it needs a new backend action.

## Rollback point (recorded before any V2 change)

- **Code:** git tag `v1.0` (main at the end of V1: PRs #1 to #9, 77 tests).
- **Note:** V2 added tables and columns to the production database. Rolling the site back to V1 therefore also needs the V1 data rebuilt, as shown below.
- **Live site:** Cloud Run revision `headcount-desk-00006-ht7`. To roll back:
  `gcloud run services update-traffic headcount-desk --region us-east1 --to-revisions=headcount-desk-00006-ht7=100`
  then rebuild the production data for that version: `git checkout v1.0 && uv run python -m scripts.migrate --prod && uv run python -m scripts.seed --prod`.

## V2: from prototype to product (Fri Nov 6, 2:15 to 4:50 AM ET)

| PR | Contents | State |
|---|---|---|
| #10 | Foundation, Tier 1 and Tier 2: design system and full UI overhaul, cost model and Budget, security hardening | merged |
| #11 | Tier 3 and Tier 4: FY28 annual planning cycle, quarter-end forecast | merged |
| #12 | Docs, screenshots, compression, accessibility polish | merged |
| #13 | Health-check alias, staged deploys in the deploy script, final notes | merged |
| #14 | This file: final state after the last deploy (docs only, no deploy needed) | merged |
| #15 | A "Try this" step for the planning flow, a row limit on the exceptions list, position codes that do not wrap | merged |
| #16 | This file again: the final state after #15 was deployed (docs only) | merged |

**Final state: main at `6660fff` (CI green) is live as Cloud Run revision `headcount-desk-00009-mkv`, verified end to end at 4:29 AM ET (25 of 25 live checks). Commits after that are docs only.**

**What shipped**

- **Tier 1, design.** `docs/DESIGN.md` and every page rebuilt on it: sidebar shell, designed dark mode (follows the system, with a toggle), a bridge chart in place of the waterfall, detail in a deep-linkable side drawer, sortable tables with filters in the URL, pagination and CSV export, a ⌘K command palette, a Today page per role, an org explorer, and `/styleguide` showing every component in both themes.
- **Tier 2, dollars.** A rate card (`cost_rates`), a fiscal calendar, a Budget page (projected spend against the plan, drill-down to seats), cost and budget position on every backfill approval, and two new data checks (eight in total).
- **Tier 3, annual planning.** The FY28 cycle: VP asks by job family with live dollar impact, SVP review against an envelope (approve, approve fewer, send back), lock into a new plan version that takes effect next fiscal year. Append-only audit trail. Seeded mid-cycle.
- **Tier 4, forecast.** Projected people in seats and run-rate at quarter end, with a P25 to P75 range and the method written on the page. Drill-down to each open request's odds and to the exits behind the attrition rate.
- **Hardening.** CSRF on every write, a strict Content Security Policy (no inline scripts, no CDNs), security headers, a write rate limit, JSON request logs, a health endpoint with a database check (`/api/health`; Cloud Run answers `/healthz` itself, so that path only works locally), server-side role permissions, input validation, numbered migrations tracked in `schema_migrations`, indexes for the hot queries (checked with EXPLAIN), and pagination or row limits on every list (the exceptions to-do list is grouped by owner and collapsed, with a row limit).

**How it was verified**

- 142 tests pass locally and in CI: unit tests with hand-worked fixtures (usable open, budget, forecast), workflow and permission tests, and Playwright end-to-end tests (backfill flow, planning cycle, exceptions, palette, drawer, theme, org explorer).
- axe-core runs on every page in light and dark: zero serious or critical violations.
- Every page was screenshot-reviewed at 1440px, 1024px and 375px in both themes; an automated test asserts no page scrolls sideways at any of the three widths.

**Live checks (first run at 3:32 AM ET on revision `headcount-desk-00007-t8f`, repeated at 3:48 AM on `headcount-desk-00008-9nf` and at 4:29 AM on `headcount-desk-00009-mkv`)**

- A browser script drove the live site end to end: every page for every role, security headers, CSRF refusal, CSV export, the backfill flow (request, approve in place with dollars shown, open, fill), the planning cycle (edit with live dollars, submit, approve fewer, lock, and this year's plan unchanged), the palette and drawer, dark mode, the bridge chart, the org explorer, the forecast, exceptions with undo, data health, Reset demo, and no sideways scroll on a phone. On the first run 24 of 25 steps passed; the one miss was `/healthz`, which Cloud Run intercepts. `/api/health` was added, and the second and third runs passed 25 of 25.
- Lighthouse on the live Headcount page: **performance 100, accessibility 96, best practices 100**, in both mobile and desktop modes (LCP 1.0 s on mobile, 0.3 s on desktop; no layout shift).

**Rollback points for V2**

- Back to V1: tag `v1.0` and revision `headcount-desk-00006-ht7` (see the top of this file).
- Within V2: `headcount-desk-00008-9nf` (main at `1418ac8`) and `headcount-desk-00007-t8f` (main at `7d0be20`) were also verified end to end and use the same database schema as the current revision, so either is a one-command fallback:
  `gcloud run services update-traffic headcount-desk --region us-east1 --to-revisions=headcount-desk-00008-9nf=100`

**What is next**

- Real sign-in in place of the role switcher (the permission rules are already enforced).
- A nightly job to write the snapshot and vacate seats on a person's last day.
- Use what is already known in the forecast (notice given, offers signed), and split rates by job family.
- Split the locked annual plan down to teams.

## V1 Status: all eight milestones (PRs 0 to 7) built, merged and deployed, plus one follow-up PR

| PR | GitHub | Contents | State |
|---|---|---|---|
| 0 | #1 | PRD, schema doc, decisions log | merged |
| 1 | #2 | `db/schema.sql`, `scripts/migrate.py`, CI | merged |
| 2 | #3 | Seed generator and `seed_manifest.json` | merged |
| 3 | #4 | Usable open views, app shell, Headcount page | merged |
| 4 | #5 | Exceptions view and page | merged |
| 5 | #6 | Backfill workflow and audit trail | merged |
| 6 | #7 | Data checks and Data health page | merged |
| 7 | #8 | Polish, JSON API, deploy, README, walkthrough | merged |
| 8 | #9 | Follow-up fixes after the full review (over-hires under every SVP, safer name handling, fresh screenshots) | merged |

(GitHub numbers pull requests from 1, so "PR 0" is pull request #1.)

## What was verified

- **Tests:** 77 pass locally and in CI (Postgres 17 service container). They cover the usable-open formula on a hand-worked fixture, every planted error in `seed_manifest.json`, the workflow (happy path, rejection, skipped steps, append-only audit), each data check (clean data passes, broken data fails, the planted anomaly is flagged), and every page for every role.
- **Databases:** the Neon `dev` and `production` branches are migrated and seeded (6,155 active people, 6,814 positions, 240 planted exceptions, 41 backfill requests, 60 days of snapshots).
- **Browser run:** a headless Chromium script drove the full flow at 1440px and at 375px, locally and against the live URL: Try-this card, chart click-through, search, submit a backfill, approve in place, reject with a reason, Enter to approve, recruiter opens and fills, resolve an exception and undo, follow the anomaly to its rows, reset the demo, friendly 404. All steps passed.
- **Screenshots:** every page was captured at 1440px and 375px and reviewed against the UX checklist. No horizontal scroll at 375px on any page, for any role.

## UX checklist, page by page

| | Headcount | Exceptions | Requests | Data health | About |
|---|---|---|---|---|---|
| Title asks the question | yes | yes | yes (role-specific headline for VP and recruiter) | yes | n/a |
| Answer first, detail on demand | hero, math, table | progress, counts, list | inbox, pipeline, list | verdict, findings, checks | yes |
| Every number opens its rows | yes | yes | yes | yes | n/a |
| Plain language, ⓘ definitions | yes | yes | yes | yes | yes |
| Freshness and plan line | yes | yes | yes | yes | n/a |
| Works at 375px | yes | yes | yes | yes | yes |
| In-place updates (HTMX) | n/a | resolve, undo | approve, reject, open | n/a | n/a |
| Empty and error states | yes | yes | yes | yes | yes |

Also in place: demo banner with rate-limited Reset, first-visit "Try this" card (dismissal remembered), role switcher that lands each role on its own page, header search (`/` to focus; magnifier on phones), keyboard approval with Enter, visible focus rings, labels on every input.

## Known issues and rough edges

- The repo is private, so "Read the PRD" and "Code on GitHub" on the About page only work once it is public.
- The first request of each day rebuilds the demo data (about three seconds).
- See `docs/WALKTHROUGH.md` section 5 for the full list of what is rough and what to fix next.

## How to resume

1. `uv sync`, then `uv run pytest -q` (uses `DATABASE_URL` from `.env`, in a throwaway schema).
2. `uv run uvicorn app.main:app --reload --port 8765`
3. After a schema change: `uv run python -m scripts.migrate` then `uv run python -m scripts.seed` (add `--prod` for production).
4. Deploy with `./scripts/deploy.sh` (project `headcount-desk-demo`, region `us-east1`, min 0 and max 2 instances).

## Ideas for next

- A nightly job that vacates seats on a person's last day and writes the snapshot from `v_usable_open`.
- Let "Mark resolved" apply the fix (vacate, recode, close) instead of only recording it.
- A zoomed waterfall for the last few hundred seats.
- Effective-dated org assignments, so a reorg keeps history.
