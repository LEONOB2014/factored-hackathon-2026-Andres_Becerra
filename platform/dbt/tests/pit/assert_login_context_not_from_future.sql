-- The ASOF join must only attach logins that happened at or before the transaction.
select transaction_id, minutes_since_last_login
from {{ ref('feat_fraud_realtime_pit') }}
where minutes_since_last_login < 0
