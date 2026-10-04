-- One row per bank market and local calendar day: the country's own calendar (statutory and bank holidays, long
-- weekends, paydays, month end) from latam_eda.country.calendar, seeded. Role-playing: any local date of any process
-- joins here on (country_code, local_date).
-- grain: country_code, local_date
select
    country_code,
    cast(local_date as date)                         as local_date,
    cast(date_trunc('month', local_date) as date)    as month_start,
    iso_weekday,
    is_weekend,
    is_holiday,
    holiday_name,
    is_long_weekend,
    is_business_day,
    is_payday,
    days_since_payday,
    is_month_start,
    is_month_end,
    week_of_month,
    quarter,
    is_bonus_month
from {seed_country_calendar}
