-- dim_branch_schedule: a row for every branch_id x hour_of_day.
select g.* from (select * from (select distinct branch_id from {{ ref('stg_branches') }}) cross join (select distinct hour_of_day from {{ ref('dim_time_of_day') }})) g
where not exists (select 1 from {{ ref('dim_branch_schedule') }} f where f.branch_id = g.branch_id and f.hour_of_day = g.hour_of_day)
