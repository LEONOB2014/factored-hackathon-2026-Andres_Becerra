-- The header of every landed file, read from the lossless-bronze proof manifests (one entry per file,
-- written when the file was proven byte-exact), compared with its source contract: columns the file lacks,
-- columns the contract does not know, and a changed column order. The cheapest exact schema signal there
-- is (a header is metadata the raw CSV does carry), and it covers columns silver never selects.
{% set lake = env_var('LATAM_LAKE_DIR', '../../data/lake') %}
with files as (
    select
        regexp_extract(filename, '([a-z_]+)\.json$', 1)                         as table_name,
        unnest(map_entries(json_transform(content::json -> 'files', '"MAP(VARCHAR, JSON)"'))) as f
    from read_text('{{ lake }}/manifests/bronze_raw_proof/*.json')
    where not contains(filename, '__')            -- source__table.json: the quarantined backup copies
),
headers as (
    select
        table_name,
        f.key                                                                    as source_file,
        from_json(f.value -> 'header', '["VARCHAR"]')                            as header,
        coalesce(
            try_cast(regexp_replace(regexp_extract(f.key, 'year=[0-9]{4}/month=[0-9]{2}/day=[0-9]{2}'),
                                    'year=([0-9]{4})/month=([0-9]{2})/day=([0-9]{2})', '\1-\2-\3') as date),
            date '{{ var("data_end") }}')                                        as partition_date
    from files
),
contract as (
    select table_name, list(column_name order by ordinal) as expected
    from {{ ref('source_contract_columns') }}
    group by 1
)
select
    h.table_name,
    h.partition_date,
    h.source_file,
    h.header,
    list_filter(c.expected, x -> not list_contains(h.header, x))                 as missing_columns,
    list_filter(h.header, x -> not list_contains(c.expected, x))                 as extra_columns,
    list_filter(h.header, x -> list_contains(c.expected, x))
        <> list_filter(c.expected, x -> list_contains(h.header, x))              as reordered
from headers h
join contract c using (table_name)
