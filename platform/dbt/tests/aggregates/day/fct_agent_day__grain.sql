-- fct_agent_day: one row per (agent_id, work_date).
select count(*) as n_rows, count(distinct (agent_id, work_date)) as n_keys
from {{ ref('fct_agent_day') }}
having count(*) <> count(distinct (agent_id, work_date))
