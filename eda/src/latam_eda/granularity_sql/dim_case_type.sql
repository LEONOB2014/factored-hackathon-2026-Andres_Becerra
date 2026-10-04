-- Complaint case types: the combination that decides the handling path and the regulatory clock.
-- grain: case_type_key
select
    md5(concat_ws('|', case_type, category, subcategory, priority)) as case_type_key,
    case_type, category, subcategory, priority,
    count(*)                                                         as n_cases_observed
from {fct_complaint}
group by all
