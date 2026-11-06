# Progress

- **Live URL:** https://headcount-desk-yf5labkepq-ue.a.run.app
- **Repo:** https://github.com/avisheth2020/headcount-desk (private)

Last updated: Fri Nov 6, 2:20 AM ET.

## Rollback point (recorded before any V2 change)

- **Code:** git tag `v1.0` (main at the end of V1: PRs #1 to #9, 77 tests).
- **Live site:** Cloud Run revision `headcount-desk-00006-ht7`. To roll back:
  `gcloud run services update-traffic headcount-desk --region us-east1 --to-revisions=headcount-desk-00006-ht7=100`
  then rebuild the production data for that version: `git checkout v1.0 && uv run python -m scripts.migrate --prod && uv run python -m scripts.seed --prod`.

## Status: all eight milestones (PRs 0 to 7) built, merged and deployed, plus one follow-up PR

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
