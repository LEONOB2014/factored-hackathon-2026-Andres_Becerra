-- Bridge from a work shift to the hours of the contact-centre day it covers. The source names the shift
-- (service_agents.work_shift) but not its hours; the standard three-shift roster is assumed (Morning 06-14,
-- Afternoon 14-22, Night 22-06 on the contact clock; Rotating covers every hour). The assumption is a "missing field"
-- for the audit: a real workforce system provides the rostered hours per agent and day.
-- grain: work_shift, hour_of_day
select s.work_shift, t.hour_of_day,
       case s.work_shift
           when 'Morning' then t.hour_of_day >= 6 and t.hour_of_day < 14
           when 'Afternoon' then t.hour_of_day >= 14 and t.hour_of_day < 22
           when 'Night' then t.hour_of_day >= 22 or t.hour_of_day < 6
           else true end as in_shift
from (values ('Morning'), ('Afternoon'), ('Night'), ('Rotating')) s(work_shift)
cross join {dim_time_of_day} t
