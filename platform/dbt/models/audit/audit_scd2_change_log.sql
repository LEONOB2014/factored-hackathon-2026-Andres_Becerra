-- Field-level change log derived from the customer SCD2 snapshot: which business fields changed between
-- consecutive versions of a customer. This is the record an auditor asks for ("who re-scored this
-- customer, when, from what to what"). With a single load it is empty; scripts/scd2_demo.sh loads the
-- backup folder and then the main folder to show what the log would have caught.
{% set fields = ['segment', 'credit_score', 'monthly_income_local', 'customer_status', 'country', 'city',
                 'document_type', 'document_number', 'accepts_marketing', 'email', 'mobile_phone'] %}
with v as (
    select
        customer_id, dbt_valid_from, dbt_valid_to,
        {% for f in fields %}{{ f }}, lag({{ f }}) over w as prev_{{ f }},{% endfor %}
        lag(dbt_valid_from) over w as prev_valid_from
    from {{ ref('snap_customers') }}
    window w as (partition by customer_id order by dbt_valid_from)
)
select
    customer_id,
    prev_valid_from,
    dbt_valid_from                                  as changed_at,
    list_filter([
        {% for f in fields %}
        case when {{ f }} is distinct from prev_{{ f }} then struct_pack(field := '{{ f }}',
             old := cast(prev_{{ f }} as varchar), new := cast({{ f }} as varchar)) end{% if not loop.last %},{% endif %}
        {% endfor %}
    ], x -> x is not null)                          as changed_fields
from v
where prev_valid_from is not null
union all
-- keys whose current version was closed without a successor (deleted from the source)
select customer_id, dbt_valid_from, dbt_valid_to, [struct_pack(field := '<record>', old := 'present', new := 'deleted')]
from {{ ref('snap_customers') }} s
where dbt_valid_to is not null
  and not exists (select 1 from {{ ref('snap_customers') }} n
                  where n.customer_id = s.customer_id and n.dbt_valid_from >= s.dbt_valid_to)
