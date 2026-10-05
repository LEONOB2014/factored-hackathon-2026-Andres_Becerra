-- fct_branch_day: a row for every branch_id x local_date.
select g.* from (select * from (select distinct branch_id from {{ ref('dim_branch') }}) cross join (select distinct local_date from {{ ref('dim_data_day') }})) g
where not exists (select 1 from {{ ref('fct_branch_day') }} f where f.branch_id = g.branch_id and f.local_date = g.local_date)
