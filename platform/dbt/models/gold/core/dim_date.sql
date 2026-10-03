-- Calendar dimension (one row per day) covering the data range plus forward-looking dates for SLAs.
select
    cast(d as date)                                     as date_key,
    year(d)                                             as year,
    quarter(d)                                          as quarter,
    month(d)                                            as month,
    strftime(d, '%Y-%m')                                as year_month,
    isodow(d)                                           as iso_weekday,
    isodow(d) >= 6                                      as is_weekend,
    cast(d as date) < date '{{ var("stream_cutoff") }}' as is_historical_zone
from range(date '2020-01-01', date '2027-01-01', interval 1 day) r(d)
