-- Tamper-evidence manifest over the bronze layer: per table and process_date, the row count, an
-- order-independent MD5 digest of all rows, and a cumulative chain digest. Re-computing the manifest
-- later and comparing it with the stored one detects any insert, delete or edit in any past partition
-- (the chain makes a change in day d alter every digest after d). In production the manifest is signed
-- and written to WORM storage (S3 Object Lock, compliance mode) at ingestion time.
{% set tables = ['transactions', 'call_center_interactions', 'complaints', 'campaign_sends',
                 'satisfaction_surveys', 'call_transcripts'] %}
with partitions as (
    {% for t in tables %}
    select '{{ t }}' as table_name, process_date, count(*) as row_count,
           md5(string_agg(row_md5, '' order by row_md5)) as partition_digest
    -- _row_md5 is computed at bronze ingestion over the source columns only (lineage columns excluded)
    from (select process_date, _row_md5 as row_md5 from {{ source('raw', t) }})
    group by all
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)
select
    table_name,
    process_date,
    row_count,
    partition_digest,
    md5(string_agg(partition_digest, '|') over (partition by table_name order by process_date
                                                rows between unbounded preceding and current row)) as chain_digest,
    current_timestamp                                                                              as computed_at
from partitions
