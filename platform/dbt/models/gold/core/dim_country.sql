-- Country dimension with the residency region each country's personal data may live in.
-- Region mapping mirrors platform/policies/residency.yaml (CO/AR: no in-country BigQuery region; legal sign-off pending).
select distinct
    iso2                                                        as country_code,
    country_name,
    home_currency,
    utc_offset_hours,
    is_bank_market,
    case iso2 when 'MX' then 'northamerica-south1'
              when 'BR' then 'southamerica-east1'
              when 'CO' then 'southamerica-east1'
              when 'AR' then 'southamerica-east1'
              else null end                                     as residency_region
from {{ ref('country_codes') }}
