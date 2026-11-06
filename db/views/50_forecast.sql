-- Forecast: where each org will end the quarter. Arithmetic only, no model to train.
--
--   projected people in seats = today + expected hires − expected exits
--
--   expected hires = for each open staffing request, the chance it is filled by quarter end
--   expected exits = people in seats × observed monthly attrition × months left in the quarter
--
-- The range is P25 to P75, from the spread of those two estimates.


-- What we have seen: how long each staffing request took to fill, over the last year.
CREATE VIEW v_time_to_fill AS
SELECT id AS staffing_request_id, closed_at - opened_at AS days
FROM staffing_requests
WHERE status = 'filled' AND closed_at IS NOT NULL AND closed_at >= today() - 365;

-- Each open request and its chance of being filled by quarter end:
-- of the past requests that were still open at this one's age, the share that
-- were filled by the age this one will be when the quarter ends.
CREATE VIEW v_fill_probability AS
SELECT s.id AS staffing_request_id,
       s.position_id,
       p.org_id,
       s.status,
       s.opened_at,
       today() - s.opened_at AS age_days,
       f.quarter_ends_on - s.opened_at AS age_at_quarter_end,
       coalesce(odds.p_fill, 0) AS p_fill
FROM staffing_requests s
JOIN positions p ON p.id = s.position_id
CROSS JOIN v_fiscal_now f
CROSS JOIN LATERAL (
    SELECT round(count(*) FILTER (WHERE t.days > today() - s.opened_at AND t.days <= f.quarter_ends_on - s.opened_at)::numeric
                 / nullif(count(*) FILTER (WHERE t.days > today() - s.opened_at), 0), 4) AS p_fill
    FROM v_time_to_fill t
) odds
WHERE s.status IN ('open', 'offer_out');

-- Observed attrition over the last 60 days, for the company and each SVP org.
-- (A VP org on its own is too small a sample, so it uses its SVP's rate.)
CREATE VIEW v_attrition AS
SELECT o.id AS org_id,
       count(*) FILTER (WHERE pe.end_date BETWEEN today() - 60 AND today() - 1) AS exits_60d,
       count(*) FILTER (WHERE pe.end_date IS NULL OR pe.end_date >= today()) AS headcount,
       round(count(*) FILTER (WHERE pe.end_date BETWEEN today() - 60 AND today() - 1)::numeric
             / nullif(count(*) FILTER (WHERE pe.end_date IS NULL OR pe.end_date >= today()), 0) * 30.4375 / 60, 5) AS monthly_rate
FROM orgs o
JOIN v_org_closure c ON c.ancestor_id = o.id
JOIN people pe ON pe.org_id = c.org_id
WHERE o.level IN ('company', 'svp')
GROUP BY o.id;

CREATE VIEW v_forecast AS
WITH hires AS (
    SELECT c.ancestor_id AS org_id,
           count(*) AS open_requests,
           sum(fp.p_fill) AS expected,
           sum(fp.p_fill * (1 - fp.p_fill)) AS variance          -- each request is a coin with its own odds
    FROM v_fill_probability fp
    JOIN v_org_closure c ON c.org_id = fp.org_id
    GROUP BY c.ancestor_id
)
SELECT u.org_id,
       u.name,
       u.level,
       u.parent_id,
       f.quarter,
       f.quarter_ends_on,
       f.quarter_ends_on - today() AS days_left,
       u.approved,
       x.in_seats,
       coalesce(h.open_requests, 0)::int AS open_requests,
       round(x.hires, 1) AS expected_hires,
       a.monthly_rate,
       round(x.exits, 1) AS expected_exits,
       round(y.p50)::int AS projected,
       round(y.p50 - 0.674 * y.sd)::int AS projected_low,        -- P25
       round(y.p50 + 0.674 * y.sd)::int AS projected_high,       -- P75
       b.budget,
       b.run_rate,
       round(b.run_rate + (x.hires - x.exits) * z.cost_per_seat, 2) AS projected_run_rate,
       round(b.run_rate + (x.hires - x.exits - 0.674 * y.sd) * z.cost_per_seat, 2) AS projected_run_rate_low,
       round(b.run_rate + (x.hires - x.exits + 0.674 * y.sd) * z.cost_per_seat, 2) AS projected_run_rate_high,
       round(y.p50) > u.approved AS over_plan,
       b.run_rate + (x.hires - x.exits) * z.cost_per_seat > b.budget AS over_budget
FROM v_usable_open u
JOIN v_budget b ON b.org_id = u.org_id
JOIN v_org_path path ON path.org_id = u.org_id
JOIN v_attrition a ON a.org_id = coalesce(path.svp_id, 1)
LEFT JOIN hires h ON h.org_id = u.org_id
CROSS JOIN v_fiscal_now f
CROSS JOIN LATERAL (
    SELECT u.filled + u.negative AS in_seats,
           coalesce(h.expected, 0) AS hires,
           coalesce(h.variance, 0) AS hires_variance,
           (u.filled + u.negative) * a.monthly_rate * (f.quarter_ends_on - today()) / 30.4375 AS exits
) x
CROSS JOIN LATERAL (
    SELECT x.in_seats + x.hires - x.exits AS p50,
           sqrt(x.hires_variance + x.exits) AS sd               -- exits are counted events, so variance = mean
) y
CROSS JOIN LATERAL (SELECT b.run_rate / nullif(u.filled + u.negative, 0) AS cost_per_seat) z;
