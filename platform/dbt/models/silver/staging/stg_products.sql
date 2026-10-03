select
    product_id,
    customer_id,
    product_type,
    case product_type
        when 'Cuenta Ahorro'        then 'deposit'
        when 'Cuenta Corriente'     then 'deposit'
        when 'Tarjeta Débito'       then 'debit_card'
        when 'Tarjeta Crédito'      then 'credit_card'
        when 'Préstamo Personal'    then 'loan'
        when 'Préstamo Hipotecario' then 'loan'
        when 'Inversión'            then 'investment'
        when 'Seguro'               then 'insurance'
    end                                            as product_family,
    product_type in ('Tarjeta Crédito', 'Préstamo Personal', 'Préstamo Hipotecario')
                                                   as is_credit_product,
    product_number,
    currency,
    current_balance,
    credit_limit,
    interest_rate,
    opening_date,
    expiration_date,
    opening_branch_id,
    product_status,
    opening_channel,
    has_linked_app,
    cast(days_past_due as integer)                 as days_past_due,
    last_transaction_date,
    last_updated,
    {{ row_hash(cols_products()) }}                as row_hash
from {{ ref('typed_products') }} src
where {{ not_held('src', 'products') }}
