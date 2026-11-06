# Headcount Desk: product requirements

**Status:** working product on synthetic data (V2) · **Owner:** Avi Sheth

## Problem

Meridian Labs (a fictional AI research lab of about 6,000 people) cannot answer a simple question quickly: *how many people can each SVP actually hire right now?*

- **The position tool is noisy.** It lists every seat, but "open" mixes together seats with a recruiter working on them, seats nobody is working on, reserve the SVP is holding back, and over-hires. Stale and duplicate records make it worse.
- **Headcount is tracked through side channels.** Finance, recruiting and each org keep their own spreadsheet, and the numbers never agree.
- **Backfills are manual.** A manager fills in a form, someone copies it to a spreadsheet, a VP approves by email, a recruiter is assigned by hand, and the recruiter re-types it into the tool. Nobody can see where a request is.
- **Nobody checks the data.** When a number moves overnight, there is no way to tell a real change from a bad load.

## Users

| User | What they need |
|---|---|
| **SVP** | One trusted number: usable open headcount for my org, and where it sits |
| **VP** | Approve or reject backfills quickly, with enough context to decide |
| **Recruiter** | A clear list of the roles I own, without re-typing anything |
| **Resource manager** | Find and clear data problems, and prove the numbers tie out |

## Top three journeys

1. **"How many people can we actually hire?"** An SVP opens Headcount and sees usable open for their org, the math behind it (approved, filled, committed, reserve, negative), and the same view for each VP. Every number opens the rows behind it.
2. **"Where is my backfill?"** A manager picks who is leaving and says why. The VP approves in one click, a recruiter is assigned automatically, and the staffing request is created without anyone re-entering it. Every step is logged with who and when.
3. **"Can I trust these numbers?"** The resource manager works an exceptions list (stale opens, duplicates, ghost fills, mis-coded seats, misplaced reserve) grouped by owner, and reads a daily data health report written in plain sentences.

## Usable open headcount

```
usable open = approved (latest locked plan)
            − filled
            − committed (open staffing requests + offers out)
            − reserve held centrally
            − negative headcount (over-hires netted against the org that is over)
```

## Success metrics

| Metric | Today (manual) | Target |
|---|---|---|
| Median time from backfill request to open staffing request | weeks | under 3 days |
| Share of positions with an open exception | unknown | under 2% |
| Daily data checks passing | not measured | 8 of 8 |
| Orgs projected over budget, seen before quarter end | found after the fact | flagged daily |
| Time to collect and lock the annual plan | weeks of spreadsheets | days, with a full trail |
| Time for an SVP to get usable open | a few days of email | under 10 seconds |

## What V2 added

- **Dollars.** Every seat is costed from a rate card. A Budget page answers "are we on budget?" for any org, and the cost shows at the moment of decision (backfill approval, planning).
- **Annual planning.** The second manual process: VP asks, SVP review against an envelope, lock into a new plan version.
- **Forecast.** Projected headcount and run-rate at quarter end, as a range, with the method written on the page.
- **A product, not a prototype.** One design system in light and dark, a home page per role, a command palette, detail drawers, sortable and exportable tables, and server-side permissions.

## Out of scope

- Real logins (roles are simulated with a switcher; the permission rules themselves are enforced)
- Opex other than people cost
- Splitting a locked annual plan down to teams
- Integrations with a real HR, recruiting or finance system

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| **1. Staff** | One trusted view while the process is still manual: usable open by org, exceptions, daily checks | Shipped (V1) |
| **2. Redesign** | Fix the process before automating it: one backfill path, one approval step, an audit trail; then the same for annual planning | Shipped (V1 backfills, V2 planning) |
| **3. Automate** | Remove the re-typing: auto-assigned recruiters, staffing requests created on approval, a plan version written by the lock | Shipped (V1, V2) |
| **4. Predict** | Look ahead: quarter-end headcount and spend as a range | First version shipped (V2) |
| **Next** | Real sign-in and audit of reads; nightly snapshot and vacate jobs; team-level allocation after lock; scenario planning ("what if we freeze hiring in Q3") | Not started |
