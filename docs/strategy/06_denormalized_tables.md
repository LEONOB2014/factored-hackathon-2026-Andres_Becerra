# 06 · Denormalized tables: SQL, processing and value

[← 05 dbt](05_dbt_recommendations.md) · [index](README.md) · next: [07 graph and foundation models →](07_graph_and_foundation_models.md)

Every table in this chapter except §6.12 and §6.13 is a **running dbt model** in `platform/dbt/models/`. The SQL below is
excerpted. The model file is the source of truth and runs with `dbt build`. Each section gives the grain, the consumers,
the key SQL, the processing to apply before ML, and the risks.

## 6.0 The backbone: `int_transactions_enriched`
All transaction marts read one conformed fact. It repairs `amount_usd`, adds local time, direction, decoded response
codes and **one boolean per data-quality rule**, so every consumer can filter or weight records explicitly.

```sql
-- platform/dbt/models/intermediate/int_transactions_enriched.sql (excerpt)
fx as (
    select tx.*, f.usd_per_unit
    from tx
    asof left join {{ ref('int_fx_usd') }} f              -- latest rate on or before the business date
        on f.currency = tx.currency and f.rate_date <= tx.process_date
)
select
    ...,
    case when currency = 'USD' then amount
         else coalesce(amount_usd_source, amount * usd_per_unit) end          as amount_usd,
    case transaction_type when 'Deposit' then 1 when 'Adjustment' then 0 else -1 end as direction,
    transaction_country_code <> customer_country_code                         as is_cross_border,
    hour(transaction_ts_local)                                                as local_hour,
    cast(transaction_ts_utc as date) < product_opening_date                   as dq_r01_before_product_open,
    transaction_status = 'Approved' and fx.response_code is null              as dq_r03_approved_without_code,
    customer_country_code = 'MX' and currency = 'USD'                         as dq_r17_mx_usd_label,
    ...
```

Note the currency decision. Mexican amounts have USD-scale magnitudes (median about 467, the same as every other
country after conversion). Relabelling them MXN would inflate them about 17×, so the label stays USD and the anomaly is
flagged, not "fixed".

---

## 6.1 Customer 360: `mart_customer_360` (grain: customer)
**Consumers:** agent copilot, CRM, credit pre-screening, GraphRAG entity documents, churn and propensity models.
**Content:** profile (tokenised), holdings and balances in USD, transaction behaviour over 30/90/365 days, digital
engagement, contact centre (contacts, escalations, negative-sentiment share, last reason), complaints (open,
SLA-breached, regulator channel), marketing, survey scores and DQ context.

```sql
-- excerpt: one CTE per domain, all aggregated to the customer, then left-joined to the tokenised profile
tx as (
    select customer_id,
        count(*) filter (where transaction_ts_utc >= {{ as_of() }} - interval 90 day)              as tx_count_90d,
        sum(amount_usd) filter (where direction = 1 and transaction_status = 'Approved'
                                  and transaction_ts_utc >= {{ as_of() }} - interval 90 day)        as inflow_usd_90d,
        avg((transaction_status = 'Declined')::int)
            filter (where transaction_ts_utc >= {{ as_of() }} - interval 90 day)                   as decline_rate_90d,
        ...
    from {{ ref('int_transactions_enriched') }} group by customer_id),
cc as (
    select customer_id,
        avg((detected_sentiment in ('Negativo', 'Muy Negativo'))::int)
            filter (where interaction_ts_utc >= {{ as_of() }} - interval 365 day)  as negative_sentiment_share_365d,
        arg_max(contact_reason, interaction_ts_utc)                                as last_contact_reason
    from {{ ref('stg_call_center_interactions') }} group by customer_id),
...
```

**Processing for ML:** log1p on money; ratios instead of raw sums (outflow/inflow); missing-value indicators for every
`coalesce`d zero (no activity is different from no data); drop `*_current` attributes when back-testing.
**Risk:** it is a current-state table. For training on past dates use the `feat_*` tables, not this one.

## 6.2 Account and payment inquiries: `mart_account_payment_inquiry` (grain: product)
Answers questions like "What is my balance?", "Why was my payment declined?", "Did my deposit arrive?" and "What is
pending?". Everything an agent or chatbot needs is in **one row read**, including the last 20 transactions as a nested
list:

```sql
list(struct_pack(
        ts := transaction_ts_local, type := transaction_type, amount := amount, currency := currency,
        status := transaction_status, reason := response_meaning, merchant := merchant_name,
        channel := channel, country := transaction_country_code)
     order by transaction_ts_utc desc)[1:20]                                         as last_20_transactions,
arg_max(response_meaning, transaction_ts_utc) filter (where transaction_status = 'Declined')  as last_decline_reason,
map(list(response_code), list(n))                                                   as declines_by_code_90d
```

The response codes (00/05/14/51/54) are decoded through the `response_codes` seed into a customer-safe message in
Spanish and English plus an action (`EXPLAIN_BALANCE`, `REISSUE_CARD`, `VERIFY_CARD_DATA`, `REVIEW_RISK_BLOCK`). The
LLM never guesses why a payment failed; it reads the reason.
**Value:** the most frequent contact reason is "Transaccional". Deflecting even a fraction of these to self-service
with exact answers is the fastest return in this whole plan.

## 6.3 Card support: `mart_card_support` (grain: card)
Covers decline diagnostics by code over 30 days, the **current decline streak** (declines since the last approval),
foreign use, card-not-present activity, open cases, contacts mentioning the card, and a **rule-based next best
action**:

```sql
case
    when confirmed_fraud_365d > 0 and product_status <> 'Blocked'               then 'FRAUD_REVIEW_AND_BLOCK'
    when dq_r22_active_expired_card or declines_expired_30d > 0                 then 'REISSUE_CARD'
    when expiration_date between as_of and as_of + interval 45 day              then 'PROACTIVE_RENEWAL'
    when declines_invalid_card_30d >= 3                                          then 'VERIFY_CARD_DATA'
    when declines_do_not_honor_30d >= 3                                          then 'REVIEW_RISK_BLOCK'
    when utilization >= 0.95 or declines_insufficient_funds_30d >= 3             then 'EXPLAIN_LIMIT_OR_OFFER_INCREASE_REVIEW'
    when product_status = 'Blocked'                                              then 'UNBLOCK_AFTER_STRONG_AUTH'
    else 'NONE' end as next_best_action
```

Result over 140,040 cards:

| next best action | cards |
|---|---:|
| NONE | 73,096 |
| REISSUE_CARD | 56,731 |
| UNBLOCK_AFTER_STRONG_AUTH | 6,866 |
| PROACTIVE_RENEWAL | 2,101 |
| EXPLAIN_LIMIT_OR_OFFER_INCREASE_REVIEW | 772 |
| FRAUD_REVIEW_AND_BLOCK | 474 |

The 56,731 reissues are a real operational finding: a proactive reissue campaign removes a whole class of future
declines and calls.

## 6.4 Transaction disputes: `mart_transaction_disputes` (grain: complaint)
Covers transaction and fee complaints with SLA clocks (hours to assignment, first response and resolution), the
regulator channel, prior disputes in 365 days, and a **probabilistic link to the disputed transaction with its
evidence**:

```sql
-- candidates: same customer, 60-day window, same product or amount within 1 %
  3 * coalesce(t.product_id = d.affected_product_id, false)::int
+ 3 * coalesce(abs(t.amount - d.claimed_amount) <= 0.01 * d.claimed_amount, false)::int
+ 2 * (1 - date_diff('day', t.transaction_ts_utc, d.created_ts_utc) / 60.0)          as match_score
...
qualify row_number() over (partition by complaint_id order by match_score desc, transaction_ts_utc desc) = 1
```

**Finding:** only 34 of 27,133 disputes link with medium confidence. `affected_product_id` belongs to another customer
in every case (R25), and claimed amounts are independent of transactions. **Recommendation:** make
`disputed_transaction_id` (and, for Pix, the end-to-end ID) mandatory at intake in every channel. The mart is ready for
it: the link becomes deterministic and the saga workflow (ch. 03) can start automatically.

## 6.5 Credit product information and eligibility
`feat_credit_eligibility_pit` has grain customer × month-end for 12 months. `mart_credit_eligibility` has grain
customer and holds the latest snapshot.

Point-in-time cash-flow features come from a dense customer × month grid, so months without activity count as zeros:

```sql
sum(inflow_usd)  over w3 / 3.0                           as avg_inflow_usd_3m,
stddev_samp(inflow_usd) over w6                          as inflow_volatility_6m,
count(*) filter (where inflow_usd > 0) over w6           as months_with_inflow_6m,
...
window w3 as (partition by customer_id order by month_start rows between 2 preceding and current row),
       w6 as (partition by customer_id order by month_start rows between 5 preceding and current row)
```

Product holdings use `opening_date <= snapshot_date`, which is point-in-time safe. Credit score, income and status are
current-state and named `*_current`. Eligibility returns **reason codes**, not just a flag:

| reason | customers |
|---|---:|
| R04_INSUFFICIENT_INCOME_HISTORY | 144,648 |
| R03_NO_SCORE | 22,492 |
| R01_CUSTOMER_NOT_ACTIVE | 22,300 |
| R02_PAST_DUE_OVER_30D | 12,044 |
| R07_SHORT_TENURE | 9,988 |
| R05_HIGH_PAYMENT_BURDEN | 6,746 |

Only 0.44 % of customers qualify for a card under these illustrative thresholds. The binding constraint is the
synthetic activity density: 0.81 transactions per customer per month, against dozens in real retail banking. The
lesson is to make the policy thresholds parameters, run sensitivity analysis, and calibrate on real data before
anyone reads a rate.

**Processing for ML (when labels exist):**
- target = 90+ DPD within 12 months of the snapshot, taken from the SCD2 history;
- monotonic constraints (score ↑ ⇒ risk ↓, DPD ↑ ⇒ risk ↑);
- WoE binning for a scorecard benchmark;
- reject inference documented;
- fairness on `int_customer_fairness_attributes` (approval-rate ratio, equal opportunity) at every release.

## 6.6 Real-time fraud features: `feat_fraud_realtime_pit` (grain: transaction)
Every feature uses only past rows. Windows are **time-based** (`RANGE ... INTERVAL`) with `EXCLUDE CURRENT ROW`:

```sql
count(*) over (partition by customer_id order by transaction_ts_utc
               range between interval 1 hour preceding and current row exclude current row)  as tx_count_1h,
coalesce(sum(amount_usd) over (partition by customer_id order by transaction_ts_utc
               range between interval 24 hour preceding and current row exclude current row), 0) as amount_usd_24h,
avg(log_amount) over (partition by customer_id order by transaction_ts_utc
                      rows between unbounded preceding and 1 preceding)                    as hist_mean_log_amount,
row_number() over (partition by customer_id, merchant_name order by transaction_ts_utc) = 1 as is_new_merchant,
{{ haversine_km('w.prev_lat', 'w.prev_lon', 'w.latitude', 'w.longitude') }}
    / greatest(date_diff('second', w.prev_ts, w.transaction_ts_utc) / 3600.0, 1 / 60.0)    as implied_speed_kmh,
...
-- last login at or before the transaction: point-in-time ASOF join
asof left join logins l on l.customer_id = w.customer_id and l.event_ts_utc <= w.transaction_ts_utc
```

Guards that run in `dbt build`:
- `assert_fraud_velocity_is_point_in_time` recomputes the 24-hour velocity by brute-force self-join on a deterministic
  sample and fails on any mismatch.
- `assert_login_context_not_from_future` checks the login join.
- `assert_no_label_leaking_columns` fails if any `feat_*` or `export_kumo_*` table exposes `fraud_score`.

**The Flink SQL twin** for online serving uses the same names and windows, so training/serving parity is testable:

```sql
-- Online feature view (Flink SQL). Event time = transaction_ts_utc, watermark 5 s.
CREATE TABLE tx (
  transaction_id STRING, customer_id STRING, amount_usd DOUBLE, merchant_name STRING,
  transaction_status STRING, transaction_ts_utc TIMESTAMP(3),
  WATERMARK FOR transaction_ts_utc AS transaction_ts_utc - INTERVAL '5' SECOND
) WITH ('connector' = 'kafka', 'topic' = 'transactions.enriched', 'format' = 'avro-confluent', ...);

-- Flink evaluates one OVER frame per SELECT, so each window length is its own statement writing to the
-- same feature view (upsert by transaction_id). "minus the current row" reproduces EXCLUDE CURRENT ROW.
INSERT INTO online_fraud_features_24h
SELECT transaction_id, customer_id,
  COUNT(*) OVER w - 1                                     AS tx_count_24h,
  SUM(amount_usd) OVER w - amount_usd                     AS amount_usd_24h,
  SUM(CASE WHEN transaction_status = 'Declined' THEN 1 ELSE 0 END) OVER w
    - CASE WHEN transaction_status = 'Declined' THEN 1 ELSE 0 END AS declines_24h
FROM tx
WINDOW w AS (PARTITION BY customer_id ORDER BY transaction_ts_utc
             RANGE BETWEEN INTERVAL '24' HOUR PRECEDING AND CURRENT ROW);

INSERT INTO online_fraud_features_1h
SELECT transaction_id, COUNT(*) OVER w - 1 AS tx_count_1h
FROM tx
WINDOW w AS (PARTITION BY customer_id ORDER BY transaction_ts_utc
             RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW);
```

A parity job replays a day of Kafka through Flink and compares every feature with `feat_fraud_realtime_pit` for the
same transactions. Any difference blocks the release.

Expanding-history features (`hist_mean_log_amount`, novelty flags) are kept online as keyed state: running sums and
counts per customer, and a set of seen merchants and countries (a Bloom filter or a Redis set).

**Evidence that matters:** on these PIT features, out-of-time gradient boosting reaches AUC 0.504 (base rate 0.087 %).
The labels are not behavioural. Ship rules plus the unsupervised ensemble first (notebook 10: top-3 ensemble AP 0.77
on injected anomalies). Add the supervised layer when chargeback-confirmed labels arrive.

**Processing for ML:**
- out-of-time split (`split` column) with a 7-day **embargo** between train and test, so windows do not straddle the boundary;
- class weights or focal loss, **never SMOTE** on time series;
- evaluate AP, recall at review capacity, and expected cost (notebook 09 §7);
- `RobustScaler` for distance-based detectors (notebook 08);
- calibrate thresholds with **conformal prediction** to guarantee a false-positive budget per segment.

## 6.7 AML monitoring: `mart_aml_customer_month` (grain: customer × month)
Typology indicators with **robust peer statistics** (median and MAD per segment × country × month):

```sql
(b.inflow_usd - p.med_in) / nullif(1.4826 * p.mad_in, 0)  as inflow_robust_z_vs_peers,
list_filter(list_value(
    case when b.pass_through_ratio >= 0.9 and b.inflow_usd >= 10000          then 'RAPID_IN_OUT' end,
    case when b.inflow_to_declared_income >= 5                              then 'INFLOW_INCONSISTENT_WITH_INCOME' end,
    case when b.near_threshold_tx >= 2                                      then 'NEAR_THRESHOLD_STRUCTURING' end,
    case when b.n_foreign_countries >= 3                                    then 'MULTI_JURISDICTION' end,
    case when b.cash_share >= 0.8 and b.inflow_usd + b.outflow_usd >= 10000 then 'CASH_INTENSIVE' end,
    case when (b.inflow_usd - p.med_in) / nullif(1.4826 * p.mad_in, 0) >= 6 then 'PEER_OUTLIER_INFLOW' end
), x -> x is not null) as typology_hits
```

There are 14,668 customer-months with hits. 91 % of them are "inflow inconsistent with income", which mostly reflects
the income-in-MXN vs accounts-in-USD defect. **The rule is only as good as the currency contract.** Thresholds must be
expressed in local currency per country, as regulations define them, and never in synthetic USD.
**Limitation:** no counterparty, so network typologies (fan-in/fan-out, mule chains, round-tripping) cannot be computed.
See §6.12.

## 6.8 Customer-experience journey: `mart_cx_journey` (grain: interaction)
Joins the interaction, transcript, survey, agent, next contact and complaints opened within 14 days. Labels:
`repeat_contact_7d` (a first-contact-resolution proxy, 0.66 %) and `complaint_within_14d` (0.57 %), both suitable for
escalation-risk models. Accent matching between customer and agent (81 %) is available for QA analysis. It must never
be used for routing decisions that could discriminate.
**Risk:** `transcript_is_template_artifact` is true for 100 % of transcripts. Do not train NLP on them.

## 6.9 Marketing compliance and uplift: `mart_campaign_compliance_uplift` (grain: send)
Covers consent at send (current flag), contact pressure (sends in the prior 7 and 30 days), and products already held.

```sql
not c.accepts_marketing                                   as sent_without_current_consent,
count(*) over (partition by s.customer_id order by s.send_ts_utc
               range between interval 7 day preceding and current row exclude current row)  as prior_sends_7d,
exists (select 1 from stg_products p
        where p.customer_id = s.customer_id and p.product_type = k.promoted_product
          and p.opening_date <= cast(s.send_ts_utc as date))                                as already_held_promoted_product
```

Findings:
- 50.1 % of sends went to customers without current consent.
- 26.3 % promote a product the customer already holds.
- Conversion is identical with and without consent (0.55 % vs 0.57 %).

**Uplift modelling (T-/X-learner, uplift trees) is not identifiable without randomized holdouts.** Add a 5–10 % control
group per campaign before investing in models.

## 6.10 Collections early warning: `mart_collections_early_warning` (grain: credit product)
Covers DPD bucket, payment trend (last 30 days vs the previous 60), days since last payment, NSF declines, contact and
digital signals, and a transparent 0–100 score:

| DPD bucket | products | mean score |
|---|---:|---:|
| current | 106,585 | 10.3 |
| 01–30 | 6,231 | 35.2 |
| 31–60 | 3,112 | 50.3 |
| 61–90 | 3,233 | 50.3 |
| 90+ | 6,189 | 50.4 |

The score is monotone in delinquency, which is the sanity check a transparent score must pass. A learned roll-rate
model replaces it once the DPD snapshot history exists.

## 6.11 Audit and data-quality tables
- `dq_integrity_findings`: 11.8 M rows, one per (rule, record).
- `dq_rule_summary`: 26 rules with rate vs SLO.
- `audit_partition_manifest`: 6,568 partition digests.
- `audit_backup_reconciliation`.
- `audit_scd2_change_log`.

See ch. 04. These are denormalized too: they exist so that an auditor, a data owner or an agent can answer "what is
wrong, where, since when" without joining anything.

---

## 6.12 Not buildable yet: payment fund-flow graph for Pix MED 2.0 / SPEI / Transferencias 3.0
This needs data the source lacks: counterparty account, Pix key or CLABE/CBU/CVU, and the end-to-end transaction ID.
Once it exists, chain tracing up to five layers (the MED 2.0 requirement) is a bounded recursive query:

```sql
-- Trace funds forward from a disputed Pix transfer up to 5 hops, only through transfers that happened
-- after the previous hop and within 72 h, carrying the reachable amount (min along the path).
with recursive flow(hop, account_id, e2e_id, ts, amount_reachable, path) as (
    select 0, t.beneficiary_account_id, t.e2e_id, t.ts, t.amount, [t.payer_account_id, t.beneficiary_account_id]
    from transfers t where t.e2e_id = :disputed_e2e_id
    union all
    select f.hop + 1, t.beneficiary_account_id, t.e2e_id, t.ts, least(f.amount_reachable, t.amount),
           list_append(f.path, t.beneficiary_account_id)
    from flow f
    join transfers t
      on t.payer_account_id = f.account_id
     and t.ts > f.ts and t.ts <= f.ts + interval 72 hour
     and not list_contains(f.path, t.beneficiary_account_id)        -- no cycles
    where f.hop < 5
)
select hop, account_id, sum(amount_reachable) as amount_to_block, count(*) as paths
from flow group by all order by hop, amount_to_block desc;
```

The same edges feed the temporal GNN (ch. 07) and mule-account scoring. **Data request to the source team:**
counterparty identifiers on every transfer, which is the single highest-value schema change for financial crime.

## 6.13 Further denormalizations worth building next

| table | grain | value | depends on |
|---|---|---|---|
| `mart_merchant_risk_profile` | merchant × day | chargeback, decline and fraud rates and velocity per merchant; merchant-level drift | more than 24 merchants and an MCC code |
| `mart_customer_financial_health` | customer × month | savings rate, buffer days, overdraft frequency, income stability; financial-wellbeing nudges | real activity density |
| `mart_atm_cash_forecast` | ATM × day | cash-demand forecasting (TFT / N-HiTS) and replenishment optimisation | ATM ids (only branch-level today) |
| `mart_agent_qa_sampling` | interaction | risk-based QA sampling (escalation × sentiment × new agent) | real transcripts |
| `mart_complaint_sla_risk` | open complaint × day | time-to-breach survival model; regulator-escalation risk | per-country regulatory deadlines (seed) |
| `mart_kyc_refresh` | customer | periodic KYC due dates by risk tier; document changes (SCD2) as triggers | KYC risk ratings |
| `mart_regulatory_reports` | report × period | CONDUSEF / SFC / BCRA / BCB complaint and AML report drafts generated from marts with lineage | report specifications |

## 6.14 Which denormalized dataset for which path

| path | primary dataset | complementary | first model | readiness |
|---|---|---|---|---|
| Service copilot (inquiries, cards, disputes) | `mart_account_payment_inquiry`, `mart_card_support`, `mart_transaction_disputes` | `mart_customer_360`, GraphRAG docs | none (deterministic) + LLM explanation | **now** |
| Real-time fraud | `feat_fraud_realtime_pit` | `export_temporal_tx_events`, graph | rules + unsupervised ensemble → GBDT → GNN/TGN | rules now; ML on real labels |
| AML monitoring | `mart_aml_customer_month` | fund-flow graph (§6.12) | robust peer z + isolation forest; GNN for mule rings | after counterparty data |
| Credit eligibility and pricing | `feat_credit_eligibility_pit` | snapshots, bureau | scorecard + monotone GBDT | after 12–24 months of history |
| Collections | `mart_collections_early_warning` | `mart_cx_journey` | roll-rate GBDT; contact-strategy uplift | after DPD history |
| CX and escalation | `mart_cx_journey` | `mart_customer_360` | GBDT escalation risk; TFT for volume | now (signals are weak) |
| Marketing | `mart_campaign_compliance_uplift` | 360 | uplift learners | after holdouts |
| Relational foundation models | `export_kumo_relational_complaint90d` + related tables | — | Kumo-Relational ICL baseline | **now** (probe) |
| Tabular foundation models | `export_kumo_tabular_fraud` | — | Kumo-Tabular ICL vs GBDT | now (as a probe; labels leak) |
| GNN / TGN | `export_graph_nodes/edges`, `export_temporal_tx_events` | — | HGT / R-GCN, TGN | pipeline now, value later |
| GraphRAG | `export_graphrag_entity_docs`, `export_graphrag_triples` | regulation corpus | hybrid retrieval + KG | **now** |

## 6.15 Processing checklist (applies to every ML dataset)
1. **Point-in-time:** features only from rows before the anchor; dimensions via SCD2 as-of joins; `*_current` columns
   dropped for back-tests.
2. **Splits:** out-of-time with an embargo equal to the longest feature window. Never random splits on events.
3. **Leakage list:** `fraud_score`, any post-outcome field (resolution, conversion dates, `was_resolved` for
   escalation models), and `customer_status = Closed` when predicting churn.
4. **Missingness:** indicator columns for injected nulls (about 5 % on mandatory fields). Do not impute label-correlated
   fields.
5. **Scale and tails:** log1p on money; winsorize at p99.9 per currency; robust scaling for distance methods.
6. **Categoricals:** native GBDT categorical handling, or target encoding fitted inside time folds only.
7. **Currency and time:** USD at the daily rate (and note that ARS is flat in this feed); local hour by country; DST-free
   offsets.
8. **Duplicates and clones:** dedupe on business key + version. The backup's 11,734 re-dated clones show why.
9. **Fairness:** protected and proxy attributes (gender, age band, marital status, **detected accent**) excluded from
   features and used only for disparate-impact testing.
10. **Text:** PII redaction (Presidio + custom LATAM recognisers for CURP, RFC, CC, DNI, CPF), template detection,
    language detection (es / pt).
