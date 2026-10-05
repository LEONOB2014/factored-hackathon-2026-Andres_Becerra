-- fct_channel_day: a row for every country_code x channel x local_date.
select g.* from (select * from (select distinct country_code from {{ ref('fct_country_day') }}) cross join (select distinct channel from {{ ref('int_transactions_enriched') }}) cross join (select distinct local_date from {{ ref('fct_country_day') }})) g
where not exists (select 1 from {{ ref('fct_channel_day') }} f where f.country_code = g.country_code and f.channel = g.channel and f.local_date = g.local_date)
