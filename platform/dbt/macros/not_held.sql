{# Staging filter: rows of a bronze partition held by the schema-drift circuit breaker stay out of silver
   staging (and so out of gold, features and serving) until the partition is released. #}
{% macro not_held(alias, table) -%}
not exists (
    select 1 from {{ ref('dq_partition_holds') }} h
    where h.table_name = '{{ table }}' and h.partition_date = {{ alias }}._partition_date
)
{%- endmacro %}
