-- valid split of the point-in-time fraud features (embargo rows excluded). fraud_score is absent by design.
select * exclude (split)
from {{ ref('feat_fraud_realtime_pit') }}
where split = 'valid'
