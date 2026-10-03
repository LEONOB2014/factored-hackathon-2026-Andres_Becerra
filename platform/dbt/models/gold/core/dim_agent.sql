-- Service agents without direct identifiers (names, email, phone stay in silver).
select agent_id, employee_code, native_accent, country_of_origin, assigned_branch_id, agent_type,
       experience_level, languages, specialty, hire_date, avg_csat, total_monthly_interactions,
       agent_status, work_shift
from {{ ref('stg_service_agents') }}
