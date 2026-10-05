-- fct_country_day: a row for every country_code x local_date.
select g.* from (select * from (select distinct country_code from {{ ref('dim_data_day') }}) cross join (select distinct local_date from {{ ref('dim_data_day') }})) g
where not exists (select 1 from {{ ref('fct_country_day') }} f where f.country_code = g.country_code and f.local_date = g.local_date)
