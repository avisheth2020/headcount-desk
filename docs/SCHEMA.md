# Schema

Plain Postgres. Tables are in [`db/schema.sql`](../db/schema.sql); the business logic lives in views in [`db/views.sql`](../db/views.sql) and [`db/checks.sql`](../db/checks.sql).

## Diagram

```mermaid
erDiagram
    orgs ||--o{ orgs : "parent of"
    orgs ||--o{ people : "home org"
    orgs ||--o{ positions : "owns"
    people ||--o{ positions : "sits in"
    people ||--o{ people : "manages"
    positions ||--o{ staffing_requests : "recruited through"
    people ||--o{ staffing_requests : "recruiter"
    plan_versions ||--|{ plan_lines : "contains"
    orgs ||--o{ plan_lines : "funded for"
    people ||--o{ backfill_requests : "departing"
    positions ||--o{ backfill_requests : "seat reused"
    backfill_requests ||--|{ request_events : "audit trail"
    backfill_requests ||--o| staffing_requests : "creates"
    orgs ||--o{ daily_snapshots : "one row per day"
    check_runs ||--|{ check_results : "produces"
    positions ||--o{ exception_resolutions : "resolved"
    people ||--o| recruiter_coverage : "covers a job family"

    orgs {
        int id PK
        text name
        int parent_id FK
        text level "company, svp, vp, director, team"
        int leader_person_id FK
        text cost_center
    }
    people {
        int id PK
        text full_name
        text email
        int org_id FK
        text job_family "research, eng, ops, g&a"
        text level "L3 to L9"
        date start_date
        date end_date "null = active"
        int manager_id FK
    }
    positions {
        int id PK
        text position_code UK
        int org_id FK
        text job_family
        text level
        text position_type "standard, reserve, negative"
        int person_id FK "null = open"
        date opened_at
        text source "plan, backfill, transfer"
    }
    staffing_requests {
        int id PK
        int position_id FK
        int recruiter_id FK
        text status "open, offer_out, filled, cancelled"
        int backfill_request_id FK
        date opened_at
        date closed_at
    }
    plan_versions {
        int id PK
        text name
        timestamptz locked_at
        int locked_by FK
        text content_hash
    }
    plan_lines {
        int plan_version_id PK
        int org_id PK
        text job_family PK
        int approved_headcount
        numeric approved_cost_usd
    }
    backfill_requests {
        int id PK
        int departing_person_id FK
        int position_id FK
        int requested_by FK
        text justification
        text urgency
        text status
        int vp_approver_id FK
        int recruiter_id FK
        timestamptz updated_at
    }
    request_events {
        int id PK
        int backfill_request_id FK
        text from_status
        text to_status
        int actor_id FK "null = system"
        text note
        timestamptz at
    }
    daily_snapshots {
        date snapshot_date PK
        int org_id PK
        int filled
        int open_with_req
        int open_no_req
        int reserve
        int negative
        int total_people
    }
    check_runs {
        int id PK
        timestamptz run_at
        int passed
        int warned
        int failed
    }
    check_results {
        int id PK
        int check_run_id FK
        text check_name
        int org_id FK
        text severity "pass, warn, fail"
        numeric expected
        numeric actual
        text message
    }
    exception_resolutions {
        int id PK
        text exception_type
        int position_id FK
        int resolved_by FK
        timestamptz resolved_at
    }
    recruiter_coverage {
        int person_id PK
        text job_family
    }
```

## The tables in plain English

| Table | One row is | Notes |
|---|---|---|
| `orgs` | A box on the org chart | A tree: company → SVP → VP → director → team. `parent_id` points up. |
| `people` | A person, past or present | `end_date` null means active. A future `end_date` means they have given notice. |
| `positions` | A seat | Filled when `person_id` is set. `reserve` seats are held back by an SVP; `negative` seats are over-hires with no approved headcount behind them. |
| `staffing_requests` | A recruiter working to fill a seat | At most one active request per seat (a partial unique index enforces it). |
| `plan_versions` / `plan_lines` | A locked headcount plan and its lines | Approved headcount and cost by org and job family. |
| `backfill_requests` | A manager asking to replace someone | Moves through a fixed set of statuses. |
| `request_events` | One status change on a backfill | Append-only audit trail. |
| `daily_snapshots` | Yesterday's (and every day's) totals for one org | Rolled-up totals, stored so today can be compared to yesterday. |
| `check_runs` / `check_results` | A run of the data checks and what each found | One result row per org tested. |
| `exception_resolutions` | Someone marking a data problem as dealt with | Keeps the to-do list honest without hiding the underlying row. |
| `recruiter_coverage` | Which job family a recruiter hires for | Used for auto-assignment. |

## The views

| View | What it answers |
|---|---|
| `v_org_closure` | Every org paired with each of its ancestors (and itself). This is what makes roll-ups one join. |
| `v_org_path` | For each org: its SVP, VP and director. |
| `v_position_status` | Each seat's bucket: filled, committed, open with no request, reserve or negative. **Derived, never stored.** |
| `v_headcount_direct` | Approved headcount and seats by bucket for the seats that sit directly in each org. |
| `v_usable_open` | The same, rolled up the tree, plus `usable_open`. |
| `v_exceptions` | A union of five data-quality rules, with an owner and a suggested fix. |
| `v_check_*` | One view per data check, all with the same columns, unioned in `v_check_all`. |

## Four design decisions

1. **"Open" is derived, not stored.** A seat is *filled* if `person_id` is set, *committed* if it has an active staffing request, and otherwise *open with no request*. A status you derive cannot drift out of sync with the facts it is derived from.
2. **Plans are versioned and locked.** `plan_lines` are never edited in place; a refresh is a new `plan_version`. A trigger blocks changes to a locked plan, and `content_hash` lets a daily check prove nobody got around the trigger.
3. **Workflow state changes through one function.** `app/workflow.py: transition()` is the only code that changes a backfill's status. It checks the move is legal and writes a `request_events` row in the same transaction, so every change has an actor and a timestamp and you cannot skip a step.
4. **Snapshots exist for tie-outs.** You cannot compare today to yesterday unless yesterday's numbers were stored. `daily_snapshots` keeps one row per org per day.

More choices, with the alternatives considered, are in [DECISIONS.md](DECISIONS.md).
