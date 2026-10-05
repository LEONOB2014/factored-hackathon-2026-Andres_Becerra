-- fct_customer_daypart: a row for every customer_id x daypart.
select g.* from (select * from (select distinct customer_id from {{ ref('int_customer_profile') }}) cross join (select distinct daypart from {{ ref('dim_time_of_day') }})) g
where not exists (select 1 from {{ ref('fct_customer_daypart') }} f where f.customer_id = g.customer_id and f.daypart = g.daypart)
