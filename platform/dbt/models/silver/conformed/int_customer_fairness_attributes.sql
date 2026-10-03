-- Protected and proxy attributes, kept apart from every feature table. Used ONLY to measure disparate
-- impact of models (credit, fraud, collections), never as model inputs. Access restricted to model-risk.
select
    customer_id,
    gender,
    case when date_diff('year', date_of_birth, {{ as_of() }}) < 25 then '18-24'
         when date_diff('year', date_of_birth, {{ as_of() }}) < 35 then '25-34'
         when date_diff('year', date_of_birth, {{ as_of() }}) < 50 then '35-49'
         when date_diff('year', date_of_birth, {{ as_of() }}) < 65 then '50-64'
         else '65+' end                         as age_band,
    marital_status,
    detected_accent,                            -- proxy for region/ethnicity: high-risk attribute
    country_code
from {{ ref('stg_customers') }}
