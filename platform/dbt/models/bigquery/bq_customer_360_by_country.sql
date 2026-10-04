-- Authorized view over the published customer 360. Row access policies (Terraform module bigquery)
-- restrict each analyst group to its country; policy tags on columns enforce column-level security.
{{ config(enabled=target.type == 'bigquery', materialized='view', schema='analytics') }}
select * except (document_token)
from {{ source('published', 'serving_customer_360') }}
