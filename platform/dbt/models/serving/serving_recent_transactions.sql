-- Published to Postgres serving.recent_transactions (index on product_id, recency_rank).
select *, timestamp '{{ var("as_of_date") }} 23:59:59' as as_of_ts
from {{ ref('mart_product_recent_transactions') }}
