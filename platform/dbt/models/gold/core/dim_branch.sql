select branch_id, branch_code, branch_name, branch_type, city, state, country_code, geographic_zone,
       has_atms, atm_count, teller_window_count, latitude, longitude, branch_opening_date, branch_status
from {{ ref('stg_branches') }}
