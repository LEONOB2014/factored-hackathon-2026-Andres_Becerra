-- fct_customer_month: a row for every customer_id x month_start.
select g.* from (select * from (select distinct customer_id from {{ ref('int_customer_profile') }}) cross join (select distinct month_start from {{ ref('int_customer_month_tx') }})) g
where not exists (select 1 from {{ ref('fct_customer_month') }} f where f.customer_id = g.customer_id and f.month_start = g.month_start)
