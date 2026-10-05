-- fct_country_hour: a row for every country_code x hour_start.
select g.* from (select * from (select distinct country_code from {{ ref('int_customer_profile') }}) cross join (select distinct hour_start from {{ ref('dim_hour') }})) g
where not exists (select 1 from {{ ref('fct_country_hour') }} f where f.country_code = g.country_code and f.hour_start = g.hour_start)
