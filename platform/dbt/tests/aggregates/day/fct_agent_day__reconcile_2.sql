-- fct_agent_day: sum(surveys) equals count(agent_id) of its atomic source.
with l as (select sum(surveys) as v from {{ ref('fct_agent_day') }}),
     r as (select count(agent_id) as v from {{ ref('stg_satisfaction_surveys') }})
select l.v as aggregate_value, r.v as atomic_value from l, r
where abs(coalesce(l.v, 0) - coalesce(r.v, 0)) > 1e-6 * greatest(1, abs(coalesce(r.v, 0)))
