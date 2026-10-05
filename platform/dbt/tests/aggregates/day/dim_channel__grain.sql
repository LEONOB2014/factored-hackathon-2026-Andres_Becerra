-- dim_channel: one row per (process, channel).
select count(*) as n_rows, count(distinct (process, channel)) as n_keys
from {{ ref('dim_channel') }}
having count(*) <> count(distinct (process, channel))
