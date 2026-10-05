-- Periodic snapshot, one row per agent and UTC hour in which the agent handled a contact (sparse). The hour is placed
-- on the contact clock (−8 h, ADR-014) and joined to the agent's declared shift, so every hour says whether the work
-- happened inside the shift: shift adherence and occupancy (handle time / 3,600 s).
-- grain: agent_id, hour_start
-- reconcile: contacts = count(*) filter (where agent_id is not null) from {fct_interaction}
-- reconcile: handle_seconds = sum(coalesce(duration_seconds, 0)) filter (where agent_id is not null) from {fct_interaction}
with c as (
    select agent_id, date_trunc('hour', interaction_ts_utc) as hour_start, count(*) as contacts,
           sum(coalesce(duration_seconds, 0)) as handle_seconds, sum(coalesce(wait_time_seconds, 0)) as wait_seconds
    from {fct_interaction} where agent_id is not null group by all)
select c.*, a.work_shift,
       hour(c.hour_start - interval 8 hour) as contact_hour_of_day,
       cast(c.hour_start - interval 8 hour as date) as contact_day,
       coalesce(b.in_shift, false) as in_shift
from c left join {dim_agent} a using (agent_id)
left join {dim_agent_shift} b on b.work_shift = a.work_shift and b.hour_of_day = hour(c.hour_start - interval 8 hour)
