-- Differentially private complaint statistics for cross-country/external release, using BigQuery's
-- native DP clause. Privacy unit = customer; each customer contributes to at most 3 groups; epsilon/delta
-- per query are charged against the dataset's DP analysis rule budget (configured in Terraform).
{{ config(enabled=target.type == 'bigquery', materialized='view', schema='privacy') }}
select
  with differential_privacy
    options (epsilon = 0.5, delta = 1e-6, max_groups_contributed = 3, privacy_unit_column = customer_id)
    format_date('%Y-%m', date_key)                          as year_month,
    category,
    count(*, contribution_bounds_per_group => (0, 3))       as dp_complaints
from {{ source('published', 'fct_complaint') }}
group by year_month, category
