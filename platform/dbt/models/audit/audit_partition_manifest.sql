-- Tamper-evidence manifest over lossless bronze: per table and partition (process_date), the record count,
-- an order-independent MD5 digest of the records' SHA-256 (each the hash of the record's exact landed
-- bytes), and a cumulative chain digest. Re-computing the manifest
-- later and comparing it with the stored one detects any insert, delete or edit in any past partition
-- (the chain makes a change in day d alter every digest after d). In production the manifest is signed
-- and written to WORM storage (S3 Object Lock, compliance mode) at ingestion time.
{% set tables = ['transactions', 'call_center_interactions', 'complaints', 'campaign_sends',
                 'satisfaction_surveys', 'call_transcripts'] %}
with partitions as (
    {% for t in tables %}
    select '{{ t }}' as table_name, process_date, count(*) as row_count,
           md5(string_agg(record_sha, '' order by record_sha)) as partition_digest
    -- _record_sha256 is computed at ingestion over the record's bytes as landed (lineage excluded)
    from (select cast(_partition_date as date) as process_date, _record_sha256 as record_sha
          from {{ source('bronze_raw', t) }})
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
