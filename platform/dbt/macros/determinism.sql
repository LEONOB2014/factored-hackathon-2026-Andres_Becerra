{# Order-free aggregates: a compliance rebuild must give the same bytes as the original build.
   DOUBLE sums are not associative, and DuckDB aggregates in parallel, so `sum(double)` can differ in the last bits
   between two runs on the same input. Summing DECIMAL(38, 9) is exact (each term rounds once, deterministically,
   to 1e-9), so any order gives the same total; the result is cast back to DOUBLE so column types do not change.
   docs/platform/evidence/reproducibility/ holds the two-build check. #}

{% macro exact_sum(expr, where=none) -%}
  cast(sum(cast({{ expr }} as decimal(38, 9))){% if where %} filter (where {{ where }}){% endif %} as double)
{%- endmacro %}

{% macro exact_count(expr, where=none) -%}
  count({{ expr }}){% if where %} filter (where {{ where }}){% endif %}
{%- endmacro %}

{% macro exact_avg(expr, where=none) -%}
  ({{ exact_sum(expr, where) }} / nullif({{ exact_count(expr, where) }}, 0))
{%- endmacro %}

{# Sample standard deviation from exact sums of x and x²: deterministic (the final arithmetic runs on two exact
   totals). Same NULL rule as stddev_samp: fewer than two values -> NULL. #}
{% macro exact_stddev(expr, where=none) -%}
  case when {{ exact_count(expr, where) }} > 1 then sqrt(greatest(
      ({{ exact_sum('(' ~ expr ~ ') * (' ~ expr ~ ')', where) }}
       - {{ exact_sum(expr, where) }} * {{ exact_sum(expr, where) }} / {{ exact_count(expr, where) }})
      / ({{ exact_count(expr, where) }} - 1), 0)) end
{%- endmacro %}

{# Most frequent value with a defined tie-break (the smallest value among the most frequent), unlike mode(),
   which returns any of the tied values. NULLs are ignored, as by mode(). #}
{% macro stable_mode(expr) -%}
  (list_sort(list_transform(map_entries(histogram({{ expr }})),
                            e -> struct_pack(n := -cast(e.value as bigint), v := e.key)))[1]).v
{%- endmacro %}
