-- Business logic lives here, in views, so anyone who reads SQL can check a rule.
-- Python only routes requests and renders pages.


-- ── Org chart helpers ───────────────────────────────────────────────────────

-- Every org paired with each of its ancestors, and with itself (depth 0).
-- Joining through this turns any roll-up into a plain GROUP BY ancestor_id.
CREATE VIEW v_org_closure AS
WITH RECURSIVE closure AS (
    SELECT id AS ancestor_id, id AS org_id, 0 AS depth
    FROM orgs
    UNION ALL
    SELECT c.ancestor_id, o.id, c.depth + 1
    FROM closure c
    JOIN orgs o ON o.parent_id = c.org_id
)
SELECT ancestor_id, org_id, depth FROM closure;

-- For each org: the SVP, VP and director it sits under (or is).
CREATE VIEW v_org_path AS
SELECT o.id AS org_id,
       o.name,
       o.level,
       max(a.id)   FILTER (WHERE a.level = 'svp')      AS svp_id,
       max(a.name) FILTER (WHERE a.level = 'svp')      AS svp_name,
       max(a.id)   FILTER (WHERE a.level = 'vp')       AS vp_id,
       max(a.name) FILTER (WHERE a.level = 'vp')       AS vp_name,
       max(a.id)   FILTER (WHERE a.level = 'director') AS director_id,
       max(a.name) FILTER (WHERE a.level = 'director') AS director_name
FROM orgs o
JOIN v_org_closure c ON c.org_id = o.id
JOIN orgs a ON a.id = c.ancestor_id
GROUP BY o.id, o.name, o.level;


-- ── Position status: derived, never stored ──────────────────────────────────

-- Each seat lands in exactly one bucket:
--   reserve      held back by an SVP, not yet given to a team
--   negative     an over-hire: a person in a seat the plan never approved
--   filled       a person is in the seat
--   committed    empty, but a recruiter is on it (open request or offer out)
--   open_no_req  empty and nobody is working on it
-- The partial unique index on staffing_requests guarantees at most one active
-- request per seat, so this join can never double a row.
CREATE VIEW v_position_status AS
SELECT p.id AS position_id,
       p.position_code,
       p.org_id,
       p.job_family,
       p.level,
       p.position_type,
       p.person_id,
       p.opened_at,
       p.source,
       sr.id           AS staffing_request_id,
       sr.status       AS request_status,
       sr.recruiter_id,
       CASE
           WHEN p.position_type = 'reserve'  THEN 'reserve'
           WHEN p.position_type = 'negative' THEN 'negative'
           WHEN p.person_id IS NOT NULL      THEN 'filled'
           WHEN sr.id IS NOT NULL            THEN 'committed'
           ELSE 'open_no_req'
       END AS bucket
FROM positions p
LEFT JOIN staffing_requests sr
       ON sr.position_id = p.id AND sr.status IN ('open', 'offer_out');


-- ── The plan ────────────────────────────────────────────────────────────────

-- "The plan" always means the most recently locked version.
CREATE VIEW v_current_plan AS
SELECT id, name, locked_at, locked_by, content_hash
FROM plan_versions
WHERE locked_at IS NOT NULL
ORDER BY locked_at DESC
LIMIT 1;


-- ── Usable open headcount ───────────────────────────────────────────────────

-- Step 1: count what sits directly in each org (no roll-up yet).
CREATE VIEW v_headcount_direct AS
WITH seats AS (
    SELECT org_id,
           count(*) FILTER (WHERE bucket = 'filled')      AS filled,
           count(*) FILTER (WHERE bucket = 'committed')   AS committed,
           count(*) FILTER (WHERE bucket = 'open_no_req') AS open_no_req,
           count(*) FILTER (WHERE bucket = 'reserve')     AS reserve,
           count(*) FILTER (WHERE bucket = 'negative')    AS negative
    FROM v_position_status
    GROUP BY org_id
),
plan AS (
    SELECT pl.org_id,
           sum(pl.approved_headcount) AS approved,
           sum(pl.approved_cost_usd)  AS approved_cost_usd
    FROM plan_lines pl
    JOIN v_current_plan cp ON cp.id = pl.plan_version_id
    GROUP BY pl.org_id
)
SELECT o.id AS org_id,
       coalesce(plan.approved, 0)::int       AS approved,
       coalesce(plan.approved_cost_usd, 0)   AS approved_cost_usd,
       coalesce(seats.filled, 0)::int        AS filled,
       coalesce(seats.committed, 0)::int     AS committed,
       coalesce(seats.open_no_req, 0)::int   AS open_no_req,
       coalesce(seats.reserve, 0)::int       AS reserve,
       coalesce(seats.negative, 0)::int      AS negative
FROM orgs o
LEFT JOIN seats ON seats.org_id = o.id
LEFT JOIN plan  ON plan.org_id = o.id;

-- Step 2: roll every org's direct counts up to each of its ancestors, then
-- apply the formula:
--
--   usable open = approved − filled − committed − reserve − negative
--
-- open_no_req is what the position tool *shows* as open. It is reported next
-- to usable_open, not used in it: the gap between the two is the noise.
CREATE VIEW v_usable_open AS
SELECT o.id AS org_id,
       o.name,
       o.level,
       o.parent_id,
       sum(d.approved)::int          AS approved,
       sum(d.approved_cost_usd)      AS approved_cost_usd,
       sum(d.filled)::int            AS filled,
       sum(d.committed)::int         AS committed,
       sum(d.reserve)::int           AS reserve,
       sum(d.negative)::int          AS negative,
       sum(d.open_no_req)::int       AS open_no_req,
       (sum(d.approved) - sum(d.filled) - sum(d.committed)
            - sum(d.reserve) - sum(d.negative))::int AS usable_open
FROM orgs o
JOIN v_org_closure c ON c.ancestor_id = o.id
JOIN v_headcount_direct d ON d.org_id = c.org_id
GROUP BY o.id, o.name, o.level, o.parent_id;
