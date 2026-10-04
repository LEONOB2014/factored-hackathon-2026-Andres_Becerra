-- The local days the data covers, per bank market: from the local day before the first UTC transaction (a western
-- offset moves early-UTC events to the previous local day) to the day of the last one. Every day-grain fact is dense
-- over this window, so a day without activity is a row of zeros rather than a missing row. The first and last day
-- are partial (the source starts and stops at 06:00 UTC) and is_edge marks them.
-- grain: country_code, local_date
with w as (select cast(min(transaction_ts_utc) as date) - 1 as lo, cast(max(transaction_ts_utc) as date) as hi
           from {int_transactions_enriched})
select d.*, d.local_date in (w.lo, w.lo + 1, w.hi) as is_edge
from {dim_country_day} d cross join w
where d.local_date between w.lo and w.hi
