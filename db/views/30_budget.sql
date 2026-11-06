-- Dollars. The same shape as headcount: cost each seat, count what sits
-- directly in each org, then roll up the tree.


-- Where we are in the fiscal year.
CREATE VIEW v_fiscal_now AS
SELECT fy.name,
       fy.starts_on,
       fy.ends_on,
       round(greatest(fy.ends_on - today(), 0) / 30.4375, 1) AS months_left,
       q.quarter,
       ((fy.starts_on + make_interval(months => 3 * q.quarter))::date - 1) AS quarter_ends_on
FROM fiscal_years fy
CROSS JOIN LATERAL (
    SELECT ((extract(year FROM age(today(), fy.starts_on)) * 12
             + extract(month FROM age(today(), fy.starts_on)))::int / 3) + 1 AS quarter
) q
WHERE today() BETWEEN fy.starts_on AND fy.ends_on;

-- Each seat with its annual loaded cost from the rate card.
-- annual_cost is NULL when the rate card has no row for the seat (a data check flags that).
CREATE VIEW v_position_cost AS
SELECT ps.position_id,
       ps.org_id,
       ps.bucket,
       ps.job_family,
       ps.level,
       p.location,
       cr.annual_loaded_cost_usd AS annual_cost
FROM v_position_status ps
JOIN positions p ON p.id = ps.position_id
LEFT JOIN cost_rates cr
       ON cr.job_family = ps.job_family AND cr.level = ps.level AND cr.location = p.location;

-- Step 1: dollars for the seats that sit directly in each org.
--   budget            approved cost in the current plan
--   run_rate          annual cost of every seat with a person in it (filled + over-hires)
--   committed_annual  annual cost of open seats a recruiter is working
CREATE VIEW v_budget_direct AS
WITH seats AS (
    SELECT org_id,
           coalesce(sum(annual_cost) FILTER (WHERE bucket IN ('filled', 'negative')), 0) AS run_rate,
           coalesce(sum(annual_cost) FILTER (WHERE bucket = 'committed'), 0)             AS committed_annual
    FROM v_position_cost
    GROUP BY org_id
),
plan AS (
    SELECT pl.org_id, sum(pl.approved_cost_usd) AS budget
    FROM plan_lines pl
    JOIN v_current_plan cp ON cp.id = pl.plan_version_id
    GROUP BY pl.org_id
)
SELECT o.id AS org_id,
       coalesce(plan.budget, 0)            AS budget,
       coalesce(seats.run_rate, 0)         AS run_rate,
       coalesce(seats.committed_annual, 0) AS committed_annual
FROM orgs o
LEFT JOIN seats ON seats.org_id = o.id
LEFT JOIN plan  ON plan.org_id = o.id;

-- Step 2: roll up, then answer "are we on budget?"
--
--   projected spend = run-rate
--                   + committed seats × the share of the fiscal year that is left
--
-- A committed seat only costs money once someone starts, so it is counted for
-- the months remaining, not the whole year.
CREATE VIEW v_budget AS
SELECT o.id AS org_id,
       o.name,
       o.level,
       o.parent_id,
       t.budget,
       t.run_rate,
       round(t.committed_annual * f.months_left / 12, 2)                AS committed,
       round(t.run_rate + t.committed_annual * f.months_left / 12, 2)   AS projected,
       round(t.budget - t.run_rate - t.committed_annual * f.months_left / 12, 2) AS variance,
       round(100 * (t.run_rate + t.committed_annual * f.months_left / 12) / nullif(t.budget, 0), 1) AS pct_of_budget,
       CASE WHEN t.run_rate + t.committed_annual * f.months_left / 12 > t.budget        THEN 'over'
            WHEN t.run_rate + t.committed_annual * f.months_left / 12 > 0.985 * t.budget THEN 'watch'
            ELSE 'under' END AS state
FROM orgs o
JOIN LATERAL (
    SELECT sum(d.budget) AS budget, sum(d.run_rate) AS run_rate, sum(d.committed_annual) AS committed_annual
    FROM v_org_closure c JOIN v_budget_direct d ON d.org_id = c.org_id
    WHERE c.ancestor_id = o.id
) t ON TRUE
CROSS JOIN v_fiscal_now f;


-- ── Two more data checks ────────────────────────────────────────────────────

-- 7. Budget: no VP org is projected to spend more than its approved budget.
CREATE VIEW v_check_budget (check_name, org_id, severity, expected, actual, message) AS
SELECT 'budget'::text,
       b.org_id,
       CASE WHEN b.projected > b.budget THEN 'warn' ELSE 'pass' END,
       100::numeric,
       b.pct_of_budget,
       CASE WHEN b.projected > b.budget
            THEN format('%s is projected to spend %s%% of its budget: $%sM against $%sM approved, $%sM over.',
                        b.name, b.pct_of_budget, round(b.projected / 1e6, 1), round(b.budget / 1e6, 1),
                        round(-b.variance / 1e6, 1))
            ELSE format('%s is projected to spend %s%% of its budget ($%sM of $%sM).',
                        b.name, b.pct_of_budget, round(b.projected / 1e6, 1), round(b.budget / 1e6, 1))
       END
FROM v_budget b
WHERE b.level = 'vp';

-- 8. Cost rates: every seat can be costed.
CREATE VIEW v_check_cost_rates (check_name, org_id, severity, expected, actual, message) AS
SELECT 'cost_rates'::text,
       NULL::int,
       CASE WHEN n = 0 THEN 'pass' ELSE 'fail' END,
       0::numeric,
       n::numeric,
       CASE WHEN n = 0 THEN 'Every position has a cost rate for its job family, level and location.'
            ELSE format('%s positions have no cost rate, so the budget numbers leave them out.', n) END
FROM (SELECT count(*) AS n FROM v_position_cost WHERE annual_cost IS NULL) missing;

CREATE OR REPLACE VIEW v_check_all AS
          SELECT * FROM v_check_tieout
UNION ALL SELECT * FROM v_check_rollup
UNION ALL SELECT * FROM v_check_referential
UNION ALL SELECT * FROM v_check_ratio
UNION ALL SELECT * FROM v_check_plan_integrity
UNION ALL SELECT * FROM v_check_open_share
UNION ALL SELECT * FROM v_check_budget
UNION ALL SELECT * FROM v_check_cost_rates;
