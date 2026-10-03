-- Complaint fact. affected_product_id is kept but flagged: it points to another customer's product in
-- every non-null case (rule R25), so it must not be used for linkage.
select k.* exclude (description, resolution), cast(k.created_ts_utc as date) as date_key,
       p.customer_id is not null and p.customer_id <> k.customer_id as dq_r25_product_not_owned
from {{ ref('stg_complaints') }} k
left join {{ ref('stg_products') }} p on p.product_id = k.affected_product_id
