# 04 · Slowly changing dimensions, adulterated records and broken integrity

[← 03 architecture](03_architecture.md) · [index](README.md) · next: [05 dbt →](05_dbt_recommendations.md)

## 4.1 Why SCD is a first-order concern here
`customers` and `products` arrive as **monthly snapshots** but carry only the current state. Notebook 05 and the SCD2
demo showed that values change with no trace:
- credit scores re-scored;
- consents flipped;
- product owners re-attributed;
- currencies re-denominated at flat rates.

In addition, `last_updated` is in the future for about 6 % of rows. Without history the bank cannot:

1. **Reproduce a decision.** "Why was this customer declined in March?" needs the score, income, limits and DPD
   *as known in March*.
2. **Train without leakage.** A model trained on last month's data with today's credit score learns the future.
   `feat_credit_eligibility_pit` therefore splits columns into `*_pit` (safe) and `*_current` (unsafe until history
   accumulates).
3. **Prove consent at send time.** R21 uses the current flag because nothing else exists. That is the weakest possible
   defence.
4. **Build roll-rate and early-warning models.** Collections needs the DPD trajectory, not one value.

## 4.2 Which SCD type for which attribute

| attribute group | type | rationale |
|---|---|---|
| identity documents, date of birth | Type 2 + alert | changes are rare and suspicious (1,052 document-number changes in the demo); always reviewed |
| credit score, income, segment, limits, interest rate | **Type 2, bitemporal** | regulated decision inputs; need valid time (effective) and recorded time (when the bank learned it) |
| consent flags per channel and purpose | **Type 2, bitemporal, event-sourced** | legal evidence; store the consent event (channel, text version, timestamp, source) |
| product status, DPD | Type 2 (daily) | roll rates, collections, card authorisation state |
| address, phone, email | Type 2 for KYC; Type 1 projection for contact | KYC refresh history vs "where do we send the letter" |
| customer segment for reporting | Type 6 (1+2+3) | current segment on every historical row plus the as-was segment |
| very wide, fast-changing attributes (app version, last login) | Type 4 (history table) | keep the dimension narrow; history in a separate mini-dimension |
| reference data (branches, FX) | Type 2 (branches), insert-only (FX) | branch closures and re-zoning affect historical reporting |

**Bitemporal modelling.** Every regulated fact gets `valid_from/valid_to` (business time) and
`recorded_from/recorded_to` (system time). Two kinds of question then have exact answers:
- "What was the score on 1 March?" uses business time.
- "What did we *believe* the score was when we decided on 1 March?" uses system time.

These differ when a score is back-dated or corrected. dbt snapshots give system-time history. Business time must come
from the source (effective dates in change events).

## 4.3 Implementation in this repo
- `platform/dbt/snapshots/snapshots.yml`: SCD2 for customers, products, agents and branches.
  - **Check strategy on `row_hash`**, because `last_updated` is unreliable.
  - `hard_deletes: invalidate`, so vanished keys are closed rather than left "current".
- `macros/business_columns.sql`: the business columns that define "the same record". Technical stamps are excluded.
- `audit_scd2_change_log`: field-level diff between consecutive versions (old → new per field). It is the auditor's view.
- `scripts/scd2_demo.sh`: loads the backup as "load 1" and main as "load 2". Result:

  | change type | count |
  |---|---:|
  | records deleted (closed without successor) | 145,975 |
  | credit_score | 1,525 |
  | email | 1,236 |
  | city | 1,128 |
  | document_number | 1,052 |
  | monthly income | 929 |
  | country | 771 |
  | segment | 600 |
  | accepts_marketing | 70 |

**Point-in-time joins.** The ASOF join in `feat_fraud_realtime_pit` attaches the latest login at or before each
transaction. The same pattern joins a snapshot by `dbt_valid_from <= anchor_ts < dbt_valid_to`:

```sql
-- as-was credit score at decision time
select d.decision_id, d.decided_at, s.credit_score
from decisions d
join snapshots.snap_customers s
  on s.customer_id = d.customer_id
 and d.decided_at >= s.dbt_valid_from
 and d.decided_at <  coalesce(s.dbt_valid_to, timestamp '9999-12-31');
```

## 4.4 Adulteration: prevent, detect, prove

| layer | control | here | production |
|---|---|---|---|
| **Prevent** | least privilege, separation of duties, no UPDATE on bronze | — | IAM: writers ≠ readers ≠ approvers; bronze buckets write-once |
| | immutable storage | — | S3 Object Lock (compliance mode) / Azure immutable blobs / GCS bucket lock, retention per record class |
| **Detect** | partition fingerprints + chain digest | `audit_partition_manifest` | computed at ingestion, signed (KMS), stored in WORM; nightly re-verification |
| | reconciliation of copies | `audit_backup_reconciliation` | after every backup and restore drill |
| | semantic integrity | R23–R26 | contracts + quarantine |
| | distribution drift | notebook 06 (C2ST, PSI) | Elementary / Evidently monitors |
| **Prove** | change log with actor and reason | `audit_scd2_change_log` (no actor in source) | event-sourced changes with actor, reason, approval ID |
| | lineage | dbt docs / manifest | OpenLineage end to end |

**The lesson from notebook 06 bears repeating: distribution checks alone would have accepted the substitute data.**
Two-sample AUC was 0.50 for customers, products and transactions. Only key-level and record-level hashes detect a
same-distribution substitution. Statistical monitoring and cryptographic reconciliation are complements, not
alternatives.

**How the manifest works.** `audit_partition_manifest` computes an MD5 of every row, aggregates the sorted hashes per
`process_date`, and chains the partition digests in date order. Recomputing it later and comparing with the stored
copy detects any insert, delete or edit. Changing one row on day *d* changes the digest of day *d* and the chain digest
of every later day. MD5 is fine for change detection; use SHA-256 plus a KMS signature where the manifest is legal
evidence.

## 4.5 Broken integrity: the taxonomy we now test for

| class | example | test type |
|---|---|---|
| existence (orphan FK) | `registration_branch_id` (R23) | `relationships` |
| **ownership (semantic FK)** | complaint product of another customer (R25) | custom join test |
| temporal order | transaction before product opening (R01), product before customer (R02) | expression tests |
| state consistency | active card past expiry (R22) | expression test |
| completeness | approved without response code (R03) | `not_null` with condition |
| vocabulary | Spanish labels in the backup | `accepted_values` + normalization in staging |
| unit / currency | MX in USD; income in MXN (R17) | contract: currency per country, unit tests |
| convention | timestamp in its process's delivery window (R15/R16; the 8 % failing were a −6 h window applied to −8 h processes, [ADR-014](../platform/adr/ADR-014.md)) | expression test |
| content | unrendered template placeholders (R27) | regex test |

Each class maps to a severity, an owner and an SLO (`seeds/dq_rule_slo.csv`). A-rules block publication in prod.
B/C-rules warn and open tickets.
