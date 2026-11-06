# Progress

- **Live URL:** https://headcount-desk-yf5labkepq-ue.a.run.app
- **Repo:** https://github.com/avisheth2020/headcount-desk (private)

Last updated: Fri Nov 6, 1:35 AM ET.

## Done
- PR 0: scaffolding, PRD, schema doc, decisions log (merged)
- PR 1: `db/schema.sql`, `scripts/migrate.py`, CI (merged)
- PR 2: seed generator + `seed_manifest.json` (merged)
- PR 3: usable open views + Headcount page (merged)
- PR 4: exceptions view + Exceptions page (merged)
- PR 5: backfill workflow + audit trail (merged)
- PR 6: data checks + Data health page (open, CI running)
- Neon `dev` and `production` branches migrated and seeded
- First deploy to Cloud Run (project `headcount-desk-demo`, region `us-east1`)

## In progress (PR 7, branch `pr7-polish`)
- JSON API, friendly error pages, click-through on every number
- UX pass at 1440px and 375px
- README, screenshots, `docs/WALKTHROUGH.md`
- Redeploy

## How to resume
1. `uv sync`, then `uv run pytest -q` (uses `DATABASE_URL` from `.env`, in a throwaway schema)
2. `uv run uvicorn app.main:app --reload --port 8765`
3. Deploy with `./scripts/deploy.sh`

## Known issues
- The repo is private, so the "Read the PRD" and "Code on GitHub" links on the About page only work once it is made public.
