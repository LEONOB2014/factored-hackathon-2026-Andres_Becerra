-- Accumulating snapshot, one row per complaint case, with one column per milestone (created, assigned, first
-- response, resolved, closed) and the durations between them, in hours. A case still open at the end of the data is
-- right-censored: its duration is only known to exceed the observation time, so `hours_observed` and `resolved_event`
-- feed survival methods, never a plain average of the resolved cases (which would be biased towards fast cases).
-- prior_contacts_30d and prior_complaints_365d are measured strictly before the case was created.
-- grain: complaint_id
-- reconcile: n_cases = count(*) from {fct_complaint}
with end_ as (select max(created_ts_utc) as data_end from {fct_complaint}),
pc as (
    select c.complaint_id, count(i.interaction_id) as prior_contacts_30d
    from {fct_complaint} c left join {fct_interaction} i
      on i.customer_id = c.customer_id and i.interaction_ts_utc < c.created_ts_utc
     and i.interaction_ts_utc >= c.created_ts_utc - interval 30 day
    group by 1),
pq as (
    select c.complaint_id, count(p.complaint_id) as prior_complaints_365d
    from {fct_complaint} c left join {fct_complaint} p
      on p.customer_id = c.customer_id and p.created_ts_utc < c.created_ts_utc
     and p.created_ts_utc >= c.created_ts_utc - interval 365 day
    group by 1)
select
    c.complaint_id, c.customer_id, cu.country_code,
    md5(concat_ws('|', c.case_type, c.category, c.subcategory, c.priority)) as case_type_key,
    c.case_type, c.category, c.subcategory, c.priority, c.reception_channel, c.status,
    c.origin_interaction_id is not null as from_contact,
    c.created_ts_utc, c.assigned_ts_utc, c.first_response_ts_utc, c.resolved_ts_utc, c.closed_ts_utc,
    date_diff('minute', c.created_ts_utc, c.assigned_ts_utc) / 60.0        as hours_to_assign,
    date_diff('minute', c.created_ts_utc, c.first_response_ts_utc) / 60.0  as hours_to_first_response,
    date_diff('minute', c.created_ts_utc, c.resolved_ts_utc) / 60.0        as hours_to_resolve,
    c.resolved_ts_utc is not null                                          as resolved_event,
    date_diff('minute', c.created_ts_utc, coalesce(c.resolved_ts_utc, e.data_end)) / 60.0 as hours_observed,
    c.sla_breached, c.resolution_days, c.compensation_granted, c.is_repeat_complainer,
    pc.prior_contacts_30d, pq.prior_complaints_365d,
    1 as n_cases
from {fct_complaint} c cross join end_ e
join {int_customer_profile} cu using (customer_id)
left join pc using (complaint_id)
left join pq using (complaint_id)
