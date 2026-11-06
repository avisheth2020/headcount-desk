# Headcount Desk: product requirements

**Status:** prototype on synthetic data · **Owner:** Avi Sheth

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
| Daily data checks passing | not measured | 6 of 6 |
| Time for an SVP to get usable open | a few days of email | under 10 seconds |

## Out of scope (for this prototype)

- Real logins and permissions (roles are simulated with a switcher)
- Opex and dollars beyond the approved cost on each plan line
- Editing the plan in the app (plans are loaded, then locked)
- Integrations with a real HR or recruiting system
- Forecasting

## Roadmap

| Phase | Goal | What ships |
|---|---|---|
| **1. Staff** | One trusted view while the process is still manual | Usable open by SVP and VP, exceptions list, daily checks |
| **2. Redesign** | Fix the process before automating it | One backfill path with clear owners, a single approval step, an audit trail |
| **3. Automate** | Remove the re-typing | Auto-assigned recruiters, staffing requests created on approval, scheduled checks and alerts |
| **4. Predict** | Look ahead | Forecast attrition and hiring needs by org; scenario plans against the budget |

This prototype covers a thin slice of phases 1 to 3.
