-- Schema-drift circuit breaker: every bronze partition checked against its source contract.
-- Severity A means the producer changed what a column IS (header, grammar, format, key system, vocabulary,
-- unit or scale): the partition is held (dq_partition_holds) and kept out of staging, gold and the marts
-- until a reviewer releases it. Severity B is reported only. Thresholds (docs/platform/09 §C):
--   format / key: > 0.1 % of the non-empty values; vocabulary: > 20 % new values (B below);
--   scale: |Δ log10 median| >= 0.5 and robust z > 6 against the contract baseline; required empty > 0.1 %;
--   empty share moved by >= 30 points (B).
with p as (
    select
        p.*,
        p.n_rows - p.n_absent - p.n_empty                                      as n_nonempty,
        c.required, c.empty_share, c.scale_log10_median, c.scale_mad
    from {{ ref('dq_partition_profile') }} p
    join {{ ref('source_contract_columns') }} c using (table_name, column_name)
),
h as (
    select *, case when contains(source_file, 'year=') and partition_date >= date '{{ var("stream_cutoff") }}'
                   then 'holdout' else 'bronze' end as zone   -- facts on/after the cutoff live in the holdout zone
    from {{ ref('dq_partition_header') }}
),
checks as (
    select zone, table_name, partition_date, '*' as column_name, 'grammar' as check_name, 'A' as severity,
           n_grammar::double as observed, 0::double as threshold,
           n_grammar || ' record(s) break the CSV grammar' as detail
    from (select distinct zone, table_name, partition_date, n_grammar from p)
    where n_grammar > 0

    union all
    select zone, table_name, partition_date, column_name, 'absent', 'A', n_absent, 0,
           'column missing from the file header for ' || n_absent || ' of ' || n_rows || ' records'
    from p where n_absent > 0

    union all
    select zone, table_name, partition_date, column_name, 'required_empty', 'A', n_empty / n_rows, 0.001,
           n_empty || ' empty values in a required column'
    from p where required and n_empty > 0.001 * n_rows

    union all
    select zone, table_name, partition_date, column_name, 'format', 'A',
           (n_cast + n_format) / n_nonempty, 0.001,
           n_cast || ' value(s) do not cast, ' || n_format || ' in a format the contract does not accept'
    from p where n_nonempty > 0 and n_cast + n_format > 0.001 * n_nonempty

    union all
    select zone, table_name, partition_date, column_name, 'key_format', 'A', n_key / n_nonempty, 0.001,
           n_key || ' identifier(s) break the key pattern'
    from p where n_nonempty > 0 and n_key > 0.001 * n_nonempty

    union all
    select zone, table_name, partition_date, column_name, 'vocabulary',
           case when n_unknown > 0.2 * n_nonempty then 'A' else 'B' end,
           n_unknown / n_nonempty, 0.2,
           n_unknown || ' value(s) outside the contract vocabulary'
    from p where n_nonempty > 0 and n_unknown > 0

    union all
    select zone, table_name, partition_date, column_name, 'scale', 'A',
           log10_median - scale_log10_median, 0.5,
           'median magnitude moved by a factor of ' || round(power(10, abs(log10_median - scale_log10_median)), 2)
           || ' (robust z ' || round(abs(log10_median - scale_log10_median) / greatest(1.4826 * scale_mad, 0.05), 1) || ')'
    from p
    where n_nonzero >= 30 and scale_log10_median is not null
      and abs(log10_median - scale_log10_median) >= 0.5
      and abs(log10_median - scale_log10_median) / greatest(1.4826 * scale_mad, 0.05) > 6

    union all
    select zone, table_name, partition_date, column_name, 'empty_share', 'B',
           n_empty / n_rows - empty_share, 0.3,
           'empty share ' || round(100.0 * n_empty / n_rows, 1) || ' % vs ' || round(100.0 * empty_share, 1) || ' % in the contract'
    from p where abs(n_empty / n_rows - empty_share) >= 0.3

    union all
    select zone, table_name, partition_date, unnest(missing_columns), 'header_missing', 'A', 1, 0,
           source_file || ': column missing from the header'
    from h
    union all
    select zone, table_name, partition_date, unnest(extra_columns), 'header_extra', 'A', 1, 0,
           source_file || ': column not in the contract'
    from h
    union all
    select zone, table_name, partition_date, '*', 'header_order', 'A', 1, 0,
           source_file || ': columns in a different order'
    from h where reordered
)
select *, current_timestamp as checked_at
from checks
