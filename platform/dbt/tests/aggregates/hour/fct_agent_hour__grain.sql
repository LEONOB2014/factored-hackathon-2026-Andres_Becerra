-- fct_agent_hour: one row per (agent_id, hour_start).
select count(*) as n_rows, count(distinct (agent_id, hour_start)) as n_keys
from {{ ref('fct_agent_hour') }}
having count(*) <> count(distinct (agent_id, hour_start))
