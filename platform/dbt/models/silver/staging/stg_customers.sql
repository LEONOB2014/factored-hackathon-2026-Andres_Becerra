-- Silver-ready customer dimension (current state). PII stays here, in a restricted schema;
-- downstream marts use the tokens from int_customer_profile instead.
select
    c.customer_id,
    c.document_type,
    c.document_number,
    c.first_name,
    c.last_name,
    c.date_of_birth,
    c.gender,
    c.email,
    c.mobile_phone,
    c.landline_phone,
    c.address,
    c.city,
    c.state,
    cc.country_name                                as country,
    cc.iso2                                        as country_code,
    cc.home_currency,
    cc.utc_offset_hours,
    c.postal_code,
    c.detected_accent,
    c.segment,
    cast(c.credit_score as integer)                as credit_score,
    c.estimated_monthly_income                     as monthly_income_local,   -- local currency (MXN for MX!)
    c.occupation,
    c.marital_status,
    c.education_level,
    c.registration_date,
    c.registration_branch_id,
    c.customer_status,
    c.last_updated,
    c.accepts_marketing,
    {{ row_hash(cols_customers()) }}               as row_hash
from {{ ref('typed_customers') }} c
left join {{ ref('country_codes') }} cc on cc.raw_name = c.country
where {{ not_held('c', 'customers') }}
