select
    agent_id, employee_code, first_name, last_name, email, native_accent, country_of_origin,
    assigned_branch_id, agent_type, experience_level, languages, specialty, hire_date, avg_csat,
    cast(total_monthly_interactions as integer) as total_monthly_interactions, agent_status, work_shift,
    {{ row_hash(cols_service_agents()) }} as row_hash
from {{ source('raw', 'service_agents') }}
