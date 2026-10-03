-- Reconciliation control between the authoritative data and a copy that claims to be its backup.
-- A true backup must give: same keys, every shared record identical. Notebooks 02-06 established the
-- opposite by analysis; this model turns it into a repeatable control that fails loudly. Both sides are the
-- lossless copies, so records are compared as landed text: a backup is a copy, and a copy keeps the bytes.
{% set checks = [
    ('customers', 'customer_id', cols_customers()),
    ('products', 'product_id', cols_products()),
    ('transactions', 'transaction_id', cols_transactions()),
    ('complaints', 'complaint_id', cols_complaints()),
    ('call_center_interactions', 'interaction_id', cols_call_center_interactions()),
] %}
{% for t, pk, cols in checks %}
select
    '{{ t }}'                                                         as table_name,
    count(m.k)                                                        as main_rows,
    count(b.k)                                                        as backup_rows,
    count(*) filter (where m.k is not null and b.k is not null)       as shared_keys,
    count(*) filter (where m.k is not null and b.k is null)           as only_main,
    count(*) filter (where m.k is null and b.k is not null)           as only_backup,
    count(*) filter (where m.h = b.h)                                 as shared_identical,
    count(*) filter (where m.h <> b.h)                                as shared_changed
from (select {{ pk }} as k, {{ row_hash(cols) }} as h from {{ source('bronze_raw', t) }}) m
full outer join (select {{ pk }} as k, {{ row_hash(cols) }} as h from {{ source('quarantine_raw', t) }}) b
  on m.k = b.k
{% if not loop.last %}union all{% endif %}
{% endfor %}
