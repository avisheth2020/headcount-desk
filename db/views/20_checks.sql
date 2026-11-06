-- Data checks. Each check is a view with the same six columns:
--
--   check_name, org_id, severity (pass | warn | fail), expected, actual, message
--
-- One row per thing tested, so a passing check still shows its work.
-- Running the checks is one INSERT ... SELECT from v_check_all (app/checks.py).


-- The two most recent snapshot dates: "today" and "yesterday".
CREATE VIEW v_snapshot_days AS
SELECT max(snapshot_date) AS today_date,
       max(snapshot_date) FILTER (WHERE snapshot_date < (SELECT max(snapshot_date) FROM daily_snapshots)) AS prev_date
FROM daily_snapshots;


-- 1. Tie-out: today's filled seats = yesterday's + hires − exits.
--    Tested for the company and for each VP org.
CREATE VIEW v_check_tieout AS
SELECT 'tieout'::text AS check_name,
       o.id AS org_id,
       CASE WHEN cur.filled = prev.filled + m.hires - m.exits THEN 'pass' ELSE 'fail' END AS severity,
       (prev.filled + m.hires - m.exits)::numeric AS expected,
       cur.filled::numeric AS actual,
       format('%s: %s filled yesterday + %s hires − %s exits = %s. Today''s snapshot says %s.',
              o.name, to_char(prev.filled, 'FM999,999'), m.hires, m.exits,
              to_char(prev.filled + m.hires - m.exits, 'FM999,999'), to_char(cur.filled, 'FM999,999')) AS message
FROM orgs o
CROSS JOIN v_snapshot_days d
JOIN daily_snapshots cur  ON cur.org_id = o.id  AND cur.snapshot_date = d.today_date
JOIN daily_snapshots prev ON prev.org_id = o.id AND prev.snapshot_date = d.prev_date
CROSS JOIN LATERAL (
    SELECT count(*) FILTER (WHERE pe.start_date = d.today_date) AS hires,   -- started today
           count(*) FILTER (WHERE pe.end_date = d.prev_date)    AS exits    -- last day was yesterday
    FROM people pe
    JOIN v_org_closure c ON c.org_id = pe.org_id
    WHERE c.ancestor_id = o.id
) m
WHERE o.level IN ('company', 'vp');


-- 2. Roll-up: an org's seats = the orgs directly below it + the seats it holds itself.
CREATE VIEW v_check_rollup (check_name, org_id, severity, expected, actual, message) AS
WITH totals AS (
    SELECT s.org_id, s.filled + s.open_with_req + s.open_no_req + s.reserve + s.negative AS seats
    FROM daily_snapshots s
    JOIN v_snapshot_days d ON s.snapshot_date = d.today_date
)
SELECT 'rollup'::text,
       o.id,
       CASE WHEN own.seats = kids.seats + held.seats THEN 'pass' ELSE 'fail' END,
       (kids.seats + held.seats)::numeric,
       own.seats::numeric,
       format('%s: %s seats in the orgs below + %s held directly = %s. Its own row says %s.',
              o.name, to_char(kids.seats, 'FM999,999'), held.seats,
              to_char(kids.seats + held.seats, 'FM999,999'), to_char(own.seats, 'FM999,999'))
FROM orgs o
JOIN totals own ON own.org_id = o.id
CROSS JOIN LATERAL (SELECT coalesce(sum(t.seats), 0) AS seats
                    FROM totals t JOIN orgs k ON k.id = t.org_id WHERE k.parent_id = o.id) kids
CROSS JOIN LATERAL (SELECT count(*) AS seats FROM positions p WHERE p.org_id = o.id) held
WHERE o.level <> 'team';


-- 3. Referential: no seat without a real org, no active person without a seat.
CREATE VIEW v_check_referential (check_name, org_id, severity, expected, actual, message) AS
SELECT 'referential'::text,
       NULL::int,
       CASE WHEN n = 0 THEN 'pass' ELSE 'fail' END,
       0::numeric,
       n::numeric,
       CASE WHEN n = 0 THEN 'Every position belongs to a real org.'
            ELSE format('%s positions point to an org that does not exist.', n) END
FROM (SELECT count(*) AS n FROM positions p LEFT JOIN orgs o ON o.id = p.org_id WHERE o.id IS NULL) orphan_seats
UNION ALL
SELECT 'referential',
       NULL,
       CASE WHEN n = 0 THEN 'pass' ELSE 'fail' END,
       0,
       n,
       CASE WHEN n = 0 THEN 'Every active person sits in a position.'
            ELSE format('%s active people have no position.', n) END
FROM (SELECT count(*) AS n FROM people pe
      WHERE pe.end_date IS NULL AND NOT EXISTS (SELECT 1 FROM positions p WHERE p.person_id = pe.id)) seatless;


-- 4. Ratio: a VP org's share of company headcount should not move more than
--    3 points in a day. A bigger jump usually means a bad load, not real hiring.
CREATE VIEW v_check_ratio (check_name, org_id, severity, expected, actual, message) AS
WITH shares AS (
    SELECT s.snapshot_date, s.org_id,
           100.0 * s.total_people / company.total_people AS share
    FROM daily_snapshots s
    JOIN orgs o ON o.id = s.org_id AND o.level = 'vp'
    JOIN daily_snapshots company ON company.snapshot_date = s.snapshot_date
    JOIN orgs co ON co.id = company.org_id AND co.level = 'company'
),
moves AS (
    SELECT snapshot_date, org_id, share,
           lag(share) OVER (PARTITION BY org_id ORDER BY snapshot_date) AS share_before
    FROM shares
),
summary AS (
    SELECT m.org_id,
           max(m.share)        FILTER (WHERE m.snapshot_date = d.today_date) AS share_today,
           max(m.share_before) FILTER (WHERE m.snapshot_date = d.today_date) AS share_before,
           max(abs(m.share - m.share_before)) FILTER (WHERE m.snapshot_date < d.today_date) AS usual_move
    FROM moves m CROSS JOIN v_snapshot_days d
    GROUP BY m.org_id
)
SELECT 'ratio'::text,
       o.id,
       CASE WHEN abs(s.share_today - s.share_before) > 3 THEN 'warn' ELSE 'pass' END,
       round(s.share_before, 1),
       round(s.share_today, 1),
       CASE WHEN abs(s.share_today - s.share_before) > 3
            THEN format('%s went from %s%% to %s%% of headcount overnight (%s pts). It usually moves under %s.',
                        o.name, round(s.share_before, 1), round(s.share_today, 1),
                        to_char(round(s.share_today - s.share_before, 1), 'SGFM990.0'),
                        greatest(round(coalesce(s.usual_move, 0) + 0.05, 1), 0.1))
            ELSE format('%s is %s%% of headcount (%s pts from yesterday).',
                        o.name, round(s.share_today, 1), to_char(round(s.share_today - s.share_before, 1), 'SGFM990.0'))
       END
FROM summary s
JOIN orgs o ON o.id = s.org_id;


-- 5. Plan integrity: a locked plan's lines still match the fingerprint stored at lock time.
CREATE VIEW v_check_plan_integrity (check_name, org_id, severity, expected, actual, message) AS
SELECT 'plan_integrity'::text,
       NULL::int,
       CASE WHEN v.content_hash = plan_hash(v.id) THEN 'pass' ELSE 'fail' END,
       1::numeric,
       (v.content_hash = plan_hash(v.id))::int::numeric,
       CASE WHEN v.content_hash = plan_hash(v.id)
            THEN format('%s: unchanged since it was locked on %s (fingerprint %s…).',
                        v.name, to_char(v.locked_at AT TIME ZONE 'America/New_York', 'Mon FMDD'), left(v.content_hash, 8))
            ELSE format('%s: the plan lines no longer match the fingerprint stored when it was locked on %s. Someone edited a locked plan.',
                        v.name, to_char(v.locked_at AT TIME ZONE 'America/New_York', 'Mon FMDD'))
       END
FROM plan_versions v
WHERE v.locked_at IS NOT NULL;


-- 6. Exception volume: in any VP org, seats that are open with nobody
--    recruiting should stay under 8% of all seats.
CREATE VIEW v_check_open_share (check_name, org_id, severity, expected, actual, message) AS
SELECT 'open_share'::text,
       u.org_id,
       CASE WHEN share.pct > 8 THEN 'warn' ELSE 'pass' END,
       8::numeric,
       share.pct,
       format('%s: %s%% of seats are open with no staffing request (%s of %s). The limit is 8%%.',
              u.name, share.pct, u.open_no_req, to_char(share.seats, 'FM999,999'))
FROM v_usable_open u
CROSS JOIN LATERAL (
    SELECT u.filled + u.committed + u.open_no_req + u.reserve + u.negative AS seats,
           round(100.0 * u.open_no_req
                 / nullif(u.filled + u.committed + u.open_no_req + u.reserve + u.negative, 0), 1) AS pct
) share
WHERE u.level = 'vp';


CREATE VIEW v_check_all AS
          SELECT * FROM v_check_tieout
UNION ALL SELECT * FROM v_check_rollup
UNION ALL SELECT * FROM v_check_referential
UNION ALL SELECT * FROM v_check_ratio
UNION ALL SELECT * FROM v_check_plan_integrity
UNION ALL SELECT * FROM v_check_open_share;
