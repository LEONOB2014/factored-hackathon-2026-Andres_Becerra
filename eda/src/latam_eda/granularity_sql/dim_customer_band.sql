-- Mini-dimension (Kimball) for the customer's fast-changing behaviour, one row per combination of tiers. The
-- customer-month fact carries band_key, so a customer's band can change every month without versioning the SCD2
-- customer dimension. Tiers are fixed cut points (not quantiles of the data) so a band means the same in every month.
-- grain: band_key
with a as (select * from (values (0, 'inactive'), (1, 'light'), (2, 'regular'), (3, 'heavy')) t(activity_rank, activity_tier)),
     v as (select * from (values (0, 'no spend'), (1, 'low'), (2, 'mid'), (3, 'high')) t(value_rank, value_tier)),
     d as (select * from (values (0, 'offline'), (1, 'occasional'), (2, 'digital')) t(digital_rank, digital_tier)),
     s as (select * from (values (0, 'no contact'), (1, 'contacted')) t(service_rank, service_tier))
select
    a.activity_rank * 100 + v.value_rank * 10 + d.digital_rank * 2 + s.service_rank as band_key,
    a.activity_tier, v.value_tier, d.digital_tier, s.service_tier,
    a.activity_rank, v.value_rank, d.digital_rank, s.service_rank
from a cross join v cross join d cross join s
