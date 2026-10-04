# 01 · What the evidence says

[← index](README.md) · next: [02 compliance →](02_compliance_and_regulation.md)

This chapter consolidates notebooks 01–11 and the dbt warehouse into one trust profile. Every number here comes from
`eda/reports/tables/*.csv`. The tables prefixed `warehouse_` are produced by `eda/scripts/warehouse_validation.py` after `dbt build`.

## 1.1 The dataset in one paragraph
A synthetic LATAM retail bank with 150,000 customers in **Mexico, Colombia and Argentina**. The data covers 400,000 products,
4.43 M transactions (2023-06-17 → 2026-06-17), 15.6 M digital events, 686 k contact-centre interactions, 171 k transcripts,
213 k surveys, 67 k complaints and 1.75 M campaign sends. Brazil appears only as a **destination country** of 40 k
cross-border transactions; there are no Brazilian customers, no BRL and no Pix.

The second folder, `data_backup_20260831/`, is **not a backup**. It is an independent second realisation of the same
generator with a small shared core of records and targeted defects (notebooks 02–06, `docs/dataset/backup_comparison.md`).

## 1.2 Trust profile per table

| table | rows | usable for | do not use for | key defects (rule) |
|---|---:|---|---|---|
| `customers` | 150,000 | segmentation, profile, consent check | tenure features, branch analytics, anything needing history | `registration_branch_id` orphaned for 99.997 % (R23); 2.1 % minors at registration (R05); 6.2 % `last_updated` in the future (R06); income in local currency while MX accounts are USD |
| `products` | 400,000 | holdings, balances, limits, DPD snapshot | product age (50 % opened before the customer existed, R02) | 14.2 % of all products are **active cards past expiry** (R22); owner re-attributed in 100 % of shared IDs vs backup |
| `transactions` | 4,425,008 | volumes, channel/merchant mix, cash flow | supervised fraud (label = `fraud_score`), product-age logic (18.7 % before product opened, R01) | no MXN (R17), 4.6 % approved without response code (R03), 46 % ATM/POS without coordinates (R19), no counterparty, no sign |
| `digital_events` | 15,620,994 | engagement, login context | product-level digital journeys | 24 % anonymous (R20); `product_id` belongs to another customer in every row where both IDs are present (R26, 7.0 % of all rows) |
| `call_center_interactions` | 686,296 | contact volume, reasons, sentiment, escalation | linking to complaints (`origin_interaction_id` is always null) | 8.3 % fail R15, which tests the wrong window: contacts run on a −8 h delivery day, not −6 h ([ADR-014](../platform/adr/ADR-014.md)) |
| `call_transcripts` | 171,321 | pipeline prototyping only | NLP model training or evaluation | **100 % contain unrendered placeholders** like `{monto}` (R27); one intent value (`consulta_general`) |
| `satisfaction_surveys` | 212,759 | CSAT/CES trends | NPS (no "Promoter" category exists) | template comments |
| `complaints` | 67,095 | volumes, SLA, channel (incl. regulator) | dispute→transaction linkage | `affected_product_id` belongs to **another customer** in 66.4 % of all complaints, i.e. every non-null case (R25) |
| `campaign_sends` | 1,746,801 | delivery and contact pressure | causal uplift (no control group) | **50.1 % sent to customers whose current flag says no marketing consent** (R21) |
| `daily_exchange_rates` | 13,164 | currency conversion | inflation-aware features | ARS flat at ~350/USD for three years |

**Two categories of defect matter more than the rest.**

1. **Semantic integrity failures (new in this phase).** A foreign key can pass a referential test and still be wrong:
   - complaints point to products owned by other customers (R25);
   - digital events point to products owned by other customers (R26);
   - customers and agents point to branch IDs that do not exist (R23, R24).

   `dbt test` on `relationships` passes for R25 and R26. Only an ownership-consistency test catches them. That kind of
   check is what a real bank needs for disputes, chargebacks and complaint reporting.
2. **Label leakage.** `is_fraud` (0.0975 %, 4,316 rows) is a deterministic function of `fraud_score`: a score of 35 or
   more always means fraud, and about 45 % of fraud has a low or missing score.
   - Notebook 09: behavioural features alone gave AUC 0.513.
   - Warehouse point-in-time feature table, out-of-time test: gradient boosting gives **AUC 0.504, AP 0.00086 vs a base
     rate of 0.00087** (`warehouse_fraud_pit_baseline.csv`).

   The labels contain no learnable behaviour.

## 1.3 What the backup case teaches
The reconciliation control `audit_backup_reconciliation` (dbt model) reproduces the notebook verdict in one query:

| table | main | backup | shared keys | shared identical | shared changed |
|---|---:|---:|---:|---:|---:|
| customers | 150,000 | 150,000 | 4,025 | 2,239 | 1,786 |
| products | 400,000 | 400,000 | 128,599 | 0 | 128,599 |
| transactions | 4,425,008 | 1,839,229 | 61,361 | 0 | 61,361 |
| complaints | 67,095 | 67,095 | 67,095 | 0 | 67,095 |
| call_center_interactions | 686,296 | 684,107 | 35,972 | 0 | 35,972 |

A faithful backup has zero in the last two right-hand columns except "shared identical". This one fails on every table.
The SCD2 demonstration (`platform/dbt/scripts/scd2_demo.sh`) shows what a bank would have seen if the "backup" had been
loaded as the previous version of the customer master:
- 145,975 records disappear;
- 1,525 credit scores change;
- 1,052 document numbers change;
- **70 marketing consents flip**.

None of these changes appears in `last_updated`. Untraced re-scoring and untraced consent changes are exactly the
findings an examiner escalates.

## 1.4 Statistical and anomaly-detection lessons (notebooks 06–10)
- **The core tables are statistically indistinguishable between folders.** Classifier two-sample AUC is 0.4999 for
  customers, 0.5008 for products and 0.5003 for transactions. Digital events are the exception at 0.54, which matches
  the targeted null injection in UTM fields. Distribution checks alone would have accepted the substitution; key and
  record-level reconciliation is what exposes it.
- **No time shift explains the mismatch.** Shared keys drift by table-specific offsets: transactions +0…+7 d, events
  −18…+11, sends −166…0. That is an ID-stream artefact, not a calendar shift.
- **No single detector sees every anomaly type** (`method_scorecard.csv`):
  - COPOD is the best single detector (AP 0.67 in the scorecard, 0.69 on the held-out leaderboard).
  - Robust Mahalanobis catches 100 % of amount spikes but 1.5 % of low-and-slow anomalies.
  - Every method misses dormant reactivation unless the feature is engineered.
  - A diverse three-member ensemble reaches **test AP 0.77**. Averaging all 13 detectors falls to 0.26 with mean rank,
    or 0.70 with reciprocal rank fusion.
- **Detector stability across the two realisations is a useful test.** COPOD loses 0.13 AP on the backup;
  Isolation Forest gains 0.01.
- **Cost view.** Choosing the review budget by cost (VAE at about 10 k reviews, cost 17.5 k vs 100.9 k for no review)
  beats picking the best-AUC method.

## 1.5 New facts surfaced by the warehouse

| fact | value | consequence |
|---|---:|---|
| transactions per customer per month | 0.81 | cash-flow underwriting impossible: 96 % of customers fail the "3 months of inflow in 6" rule |
| active cards past expiry | 56,664 | largest single support driver; deterministic "reissue" action |
| transaction/fee complaints | 27,133 | only 34 can be linked to a transaction by amount; the source lacks `disputed_transaction_id` |
| complaints received via the regulator | 1.1 % of disputes | small but highest-severity channel |
| campaign sends promoting a product the customer already holds | 26.3 % | wasted spend and mis-attributed conversions |
| conversion with vs without current consent | 0.55 % vs 0.57 % | consent is not modelled by the generator; in reality this is a legal risk, not a lift |
| IP addresses shared by ≥ 2 customers | 237 | shared-device graph is thin but non-empty |
| customer-months with an AML typology hit | 14,668 | 91 % are "inflow inconsistent with declared income", a currency artefact for MX |

## 1.6 What the current data can and cannot support

| capability | now (synthetic) | needs before production |
|---|---|---|
| Customer 360, inquiry and card copilots (deterministic marts + LLM explanation) | **ready** | real data, PII vault, consent records |
| Rule-based next-best-action, eligibility with reason codes | **ready** (as policy demo) | approved credit policy, adverse-action wording per country |
| Unsupervised anomaly monitoring (ensemble) | **ready** (method validated on injected anomalies) | analyst feedback loop for labels |
| Supervised fraud model | **not learnable** (labels leak) | chargeback/confirmed-fraud labels with lag handling |
| Credit risk model | **not learnable** (no performance labels, no history) | 12–24 months of SCD2 DPD history, bureau data |
| Dispute automation | **blocked** (no complaint→transaction key) | capture the disputed transaction at intake |
| Graph ML / mule detection | **partially** (customer–merchant, customer–IP) | transfer counterparties (CLABE/CBU/CVU/Pix keys, beneficiary accounts) |
| NLP on transcripts | **not usable** (template text) | real transcripts, consent to record, PII redaction |
| Uplift modelling | **not identifiable** (no holdout) | randomized control groups |

The conclusion shapes everything that follows. **This phase should build the platform, controls and contracts that make
learning possible, and ship only the use cases that are deterministic over trusted marts.** Model ambitions stay gated
on data that does not exist yet.
