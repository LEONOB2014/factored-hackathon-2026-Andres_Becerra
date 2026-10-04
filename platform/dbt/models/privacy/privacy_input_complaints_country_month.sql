-- Contribution-bounded input for the differentially private complaint statistics release.
-- Each customer contributes at most var('dp_max_contrib', 3) complaints per (country, month, category);
-- bounding sensitivity in SQL lets the OpenDP release (platform/libs/latam_platform/privacy) add calibrated
-- noise. Raw counts here are never published; only the noised output in privacy.dp_* leaves this zone.
with ranked as (
    select
        c.country_code,
        strftime(k.created_ts_utc, '%Y-%m')                 as year_month,
        k.category,
        k.customer_id,
        row_number() over (partition by c.country_code, strftime(k.created_ts_utc, '%Y-%m'), k.category, k.customer_id
                           order by k.created_ts_utc, k.complaint_id) as rn
    from {{ ref('stg_complaints') }} k
    join {{ ref('int_customer_profile') }} c using (customer_id)
)
select country_code, year_month, category, customer_id, count(*) as bounded_contribution
from ranked
where rn <= {{ var('dp_max_contrib', 3) }}
group by all
