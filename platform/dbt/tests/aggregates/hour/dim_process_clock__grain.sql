-- dim_process_clock: one row per (process).
select count(*) as n_rows, count(distinct (process)) as n_keys
from {{ ref('dim_process_clock') }}
having count(*) <> count(distinct (process))
