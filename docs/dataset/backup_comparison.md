# `data_backup_20260831/` vs `data/` – summary of findings

> **Status:** first-pass summary, **superseded in detail by the notebook series** in `eda/notebooks/` (01–11) and the
> report `eda/reports/notebooks/11_evaluation_and_report.html`. An earlier version of this file described the backup as a
> "re-keyed copy" with "edited records"; the full analysis showed that reading was wrong and it has been corrected below.

## TL;DR
The backup is **not a copy** of the main data. It is a second, independently generated realisation of the same bank:
same schema, same statistical behaviour for the core tables, mostly different IDs, a small shared core of records, two
missing tables, a truncated table and a handful of targeted defects. It should not be used as a restore point and its
tables must never be joined to the main tables.

## 1 · What exists in one folder and not the other (notebook 02)
| Table | main files | backup files | notes |
|---|---:|---:|---|
| branches, marketing_campaigns, daily_exchange_rates | 1 each | 1 each | byte-identical |
| complaints | 1,097 | 1,097 | same text/dates/status; **only the 3 foreign keys differ** |
| customers, products, service_agents | 1 each | 1 each | same row counts, mostly different IDs |
| digital_events, call_center_interactions, campaign_sends | ~1,100 | ~1,100 | same volume, mostly different IDs |
| transactions | 1,097 | **453** | only 2023-07-01 → 2024-09-25 |
| call_transcripts, satisfaction_surveys | 1,097 | **absent** | – |

Primary-key overlap with main: customers 2.7 %, transactions 1.4 %, interactions 5 %, sends 3 %, events 9 %, products 32 %,
agents 50 %, complaints/branches/campaigns 100 %.

## 2 · Is it a time shift? (notebook 03)
* **Global shift: rejected.** The weekday pattern is in the same phase in every quarter; de-seasonalised daily counts are uncorrelated at every lag.
* **Row-level offsets exist only for rows that share a key** (~3 %), drift smoothly over time and differ per table
  (transactions 0…+7 d, events −18…+11, interactions −5…+5, sends −166…0, complaints 0). They are positional offsets of an ID stream, not a calendar shift.
* **11,734 transaction "clones"** (0.27 % of main) are the same transaction re-dated by a few days and attributed to another customer/product.
* Timestamps follow a UTC−6 convention relative to `process_date` in both folders (100 % of transactions).

## 3 · Alignment and what can be compared (notebooks 04–05)
* A shared customer ID is a **noisy label**: of 4,025 shared IDs, 69 % are bit-identical records (except a re-scored credit score in 22 % of scored customers),
  6 % are hybrids, **25 % are a different person**.
* Probabilistic linkage (Fellegi–Sunter) finds ≈ 10.5 k people (7 %) in both folders, ≈ 7.5 k under a **different** ID; ≈ 93 % of customers have no counterpart.
* Products: 146 k pairs via `product_number` (25 k with a different ID). The currency is **re-denominated at flat rates (4,000 COP, 350 ARS per USD)** in ≈ 52 % of cases
  and the **owner differs in 100 %** of pairs.
* Credit-score re-scoring and other value changes do **not** update `last_updated`.

## 4 · Are the folders the same process? (notebook 06)
For customers, products and transactions the backup is statistically **indistinguishable** from main (classifier two-sample AUC 0.50, effect sizes at the
noise floor). Targeted differences: `interaction_type` re-labelled in Spanish for phone calls; call `duration_seconds`/`wait_time_seconds` 14 %/30 % → 99 %/100 % null;
`has_recording` 86 % → 1 % true; `was_clicked` (+5 pp) and `was_opened` (+3.6 pp) nulls; `utm_*`/`referrer` +3.4–3.7 pp nulls.

## 5 · Anomalies common to both folders (notebook 07)
Products opened before the customer registered (50 %), transactions before the product existed (18.7 %), all Mexican transactions labelled `USD` with no `MXN`,
~5 % null injection on mandatory fields, 6 % of customers/products with `last_updated` after the end of the data, `fraud_score` ≥ 35 ⇒ 100 % fraud.

## 6 · Why does it exist?
Not answerable from the data. It is **incompatible with a compliance archive** (which would be complete and identical) and fits a **partial second generation run** or a
**deliberate distractor**. Ask the dataset owners and record the answer in the data dictionary.

## 7 · Recommendations
1. Use `data/` as the authoritative dataset; do not join across folders.
2. If the backup is used at all, treat it as an **independent replicate** for validation (distributions, not rows).
3. Flag `last_updated` / `registration_date` after 2026-06-17 before any temporal feature engineering.
4. Reproduce the checks with `eda/scripts/` and the notebooks (see `eda/README.md`).
