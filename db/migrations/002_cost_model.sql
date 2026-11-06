-- 002: dollars. A loaded-cost rate card, a fiscal calendar, where each seat is
-- based, and when a plan version takes effect. Plus indexes for the hot queries.

-- Annual loaded cost (salary, benefits, equity, overhead) for one seat.
-- Synthetic but plausible numbers; see scripts/seed.py.
CREATE TABLE cost_rates (
    job_family              text NOT NULL CHECK (job_family IN ('research', 'eng', 'ops', 'g&a')),
    level                   text NOT NULL CHECK (level ~ '^L[3-9]$'),
    location                text NOT NULL,
    annual_loaded_cost_usd  numeric(12, 2) NOT NULL CHECK (annual_loaded_cost_usd > 0),
    created_at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_family, level, location)
);

-- The fiscal calendar is data, not code.
CREATE TABLE fiscal_years (
    name        text PRIMARY KEY,                    -- 'FY27'
    starts_on   date NOT NULL,
    ends_on     date NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_on > starts_on)
);

-- A seat is costed where it is based, whether or not anyone is in it.
ALTER TABLE positions ADD COLUMN location text NOT NULL DEFAULT 'Remote';

-- A plan belongs to a fiscal year and takes effect on a date. Locking next
-- year's plan must not change this year's numbers.
ALTER TABLE plan_versions
    ADD COLUMN fiscal_year    text REFERENCES fiscal_years (name),
    ADD COLUMN effective_from date;

-- Indexes for the queries the pages run most (checked with EXPLAIN; see docs/DECISIONS.md).
CREATE INDEX people_org_idx              ON people (org_id);
CREATE INDEX people_leaving_idx          ON people (end_date) WHERE end_date IS NOT NULL;
CREATE INDEX orgs_parent_idx             ON orgs (parent_id);
CREATE INDEX staffing_backfill_idx       ON staffing_requests (backfill_request_id);
CREATE INDEX backfill_approver_idx       ON backfill_requests (vp_approver_id, status);
CREATE INDEX backfill_recruiter_idx      ON backfill_requests (recruiter_id, status);
CREATE INDEX backfill_requester_idx      ON backfill_requests (requested_by);
CREATE INDEX snapshots_org_idx           ON daily_snapshots (org_id, snapshot_date DESC);
CREATE INDEX check_results_name_idx      ON check_results (check_run_id, check_name);
CREATE INDEX check_runs_recent_idx       ON check_runs (run_at DESC);
CREATE INDEX plan_lines_org_idx          ON plan_lines (org_id, job_family);
