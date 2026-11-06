-- Annual planning: what each VP is asking for, and how the asks add up against the SVP's envelope.


-- Each line with the change that currently counts (the SVP's number if they
-- set one, otherwise the VP's) and what it costs. Cost per head is this
-- year's budget for that org and job family divided by its headcount.
CREATE VIEW v_plan_submission_lines AS
SELECT l.submission_id,
       l.job_family,
       l.base_headcount,
       l.base_cost_usd,
       l.requested_change,
       l.approved_change,
       coalesce(l.approved_change, l.requested_change) AS final_change,
       l.justification,
       round(l.base_cost_usd / nullif(l.base_headcount, 0), 2) AS cost_per_head,
       round(l.requested_change * l.base_cost_usd / nullif(l.base_headcount, 0), 2) AS requested_cost,
       round(coalesce(l.approved_change, l.requested_change) * l.base_cost_usd / nullif(l.base_headcount, 0), 2) AS final_cost
FROM plan_submission_lines l;

-- One row per VP submission, with totals and who is involved.
CREATE VIEW v_plan_submissions AS
SELECT s.id,
       s.cycle_id,
       s.status,
       s.updated_at,
       now() - s.updated_at AS time_in_status,
       s.vp_org_id,
       vp.name AS vp_name,
       vp.leader_person_id AS vp_leader_id,
       vp_leader.full_name AS vp_leader_name,
       svp.id AS svp_org_id,
       svp.name AS svp_name,
       svp.leader_person_id AS svp_leader_id,
       svp_leader.full_name AS svp_leader_name,
       t.base_headcount,
       t.base_cost_usd,
       t.requested_change,
       t.final_change,
       t.requested_cost,
       t.final_cost,
       t.base_headcount + t.final_change AS proposed_headcount,
       t.base_cost_usd + t.final_cost AS proposed_cost
FROM plan_submissions s
JOIN orgs vp ON vp.id = s.vp_org_id
JOIN orgs svp ON svp.id = vp.parent_id
JOIN people vp_leader ON vp_leader.id = vp.leader_person_id
JOIN people svp_leader ON svp_leader.id = svp.leader_person_id
JOIN LATERAL (
    SELECT coalesce(sum(base_headcount), 0)::int AS base_headcount, coalesce(sum(base_cost_usd), 0) AS base_cost_usd,
           coalesce(sum(requested_change), 0)::int AS requested_change, coalesce(sum(final_change), 0)::int AS final_change,
           coalesce(sum(requested_cost), 0) AS requested_cost, coalesce(sum(final_cost), 0) AS final_cost
    FROM v_plan_submission_lines l WHERE l.submission_id = s.id
) t ON TRUE;

-- Each SVP's envelope against what their VPs are asking for.
--   headroom = envelope − (this year + every ask that is submitted or approved)
-- Drafts and sent-back asks are shown separately: they are not on the table yet.
CREATE VIEW v_planning_envelopes AS
SELECT e.cycle_id,
       e.svp_org_id,
       o.name AS svp_name,
       e.headcount_envelope,
       e.cost_envelope_usd,
       t.base_headcount,
       t.base_cost_usd,
       t.asked_headcount,
       t.asked_cost,
       t.pending_headcount,
       t.base_headcount + t.asked_headcount AS proposed_headcount,
       t.base_cost_usd + t.asked_cost AS proposed_cost,
       e.headcount_envelope - t.base_headcount - t.asked_headcount AS headcount_headroom,
       e.cost_envelope_usd - t.base_cost_usd - t.asked_cost AS cost_headroom,
       t.n_draft, t.n_submitted, t.n_sent_back, t.n_approved
FROM planning_envelopes e
JOIN orgs o ON o.id = e.svp_org_id
JOIN LATERAL (
    SELECT sum(s.base_headcount)::int AS base_headcount,
           sum(s.base_cost_usd) AS base_cost_usd,
           coalesce(sum(s.final_change) FILTER (WHERE s.status IN ('submitted', 'approved')), 0)::int AS asked_headcount,
           coalesce(sum(s.final_cost)   FILTER (WHERE s.status IN ('submitted', 'approved')), 0) AS asked_cost,
           coalesce(sum(s.final_change) FILTER (WHERE s.status IN ('draft', 'sent_back')), 0)::int AS pending_headcount,
           count(*) FILTER (WHERE s.status = 'draft') AS n_draft,
           count(*) FILTER (WHERE s.status = 'submitted') AS n_submitted,
           count(*) FILTER (WHERE s.status = 'sent_back') AS n_sent_back,
           count(*) FILTER (WHERE s.status = 'approved') AS n_approved
    FROM v_plan_submissions s
    WHERE s.cycle_id = e.cycle_id AND s.svp_org_id = e.svp_org_id
) t ON TRUE;
