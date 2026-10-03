select
    b.branch_id, b.branch_code, b.branch_name, b.branch_type, b.city, b.state,
    cc.country_name as country, cc.iso2 as country_code, b.geographic_zone,
    b.opening_time, b.closing_time, b.has_atms, b.atm_count, b.has_teller_windows, b.teller_window_count,
    b.latitude, b.longitude, b.branch_opening_date, b.branch_status,
    {{ row_hash(cols_branches()) }} as row_hash
from {{ source('raw', 'branches') }} b
left join {{ ref('country_codes') }} cc on cc.raw_name = b.country
