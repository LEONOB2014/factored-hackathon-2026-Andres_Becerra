# 09 · Data and model risk methodology: from raw evidence to audited correction

[← 08 agentic interfaces](08_agentic_interfaces.md) · [index](README.md)

The source tables arrive as CSV files **without metadata**. Every layer of the platform assumes a stable schema per
table, so an undeclared change in the source (a format, a vocabulary, a unit, a key convention) would propagate
silently into silver, gold and the models. This chapter is the standard for finding such changes **in the raw
data, before anything is typed**, for preserving the original data in full, and for flagging, reviewing and
correcting cells with an audit trail. Later sections cover drift and concept-drift model risk management, keys,
segmentation and text.

| section | scope | status |
|---|---|---|
| [A](#a-raw-schema-forensics) | schema evolution without metadata, from the raw CSV text | **implemented** (evidence: `eda/notebooks/model_risk/01_raw_schema_forensics`) |
| [B](#b-lossless-bronze-with-a-byte-exact-proof) | bronze that preserves every record and every original value, with a completeness proof | **implemented** (`platform/libs/latam_platform/lakehouse/bronze_raw.py`) |
| [C](#c-contract-driven-silver-and-cell-level-findings) | contract-driven typing in silver, cell-level findings, drift circuit breaker | **implemented** (`platform/contracts/sources`, `platform/dbt/models/silver/{typed,quality}`) |
| [D](#d-audited-correction-and-restore) | four-eyes correction and restore over an append-only ledger | designed |
| [E–H](#e-h-later-phases) | keys and source systems, drift MRM, segmentation, text | designed |

## A. Raw schema forensics

### A.1 Principle: infer from the raw text, audit the typed copies
Converting CSV to a typed format destroys exactly the evidence of a schema change: original formats, decimal and
thousands separators, leading zeros, timezone suffixes, fractional-second precision, the difference between an
empty string and a null, and every value that did not fit the type inferred for the whole column. The forensics
therefore read every raw file as text and only **audit** the typed copies afterwards.

Reading discipline (DuckDB, `latam_eda.raw_forensics.READ_OPTS`): pinned dialect (`,` `"` `"`), header, every
column as VARCHAR, a sentinel `nullstr` so that `''` stays `''`, `strict_mode`, `sample_size=-1`, the source file
name kept; **never `ignore_errors` and never `union_by_name`**. Probing DuckDB 1.5 showed why:

| default behaviour | consequence |
|---|---|
| empty field read as NULL | the empty-vs-null distinction is lost (3,151 cells in one transactions file) |
| one unparsable value in any file | the whole column silently becomes VARCHAR |
| `union_by_name=true` | each file is sniffed on its own; a ragged file can be read with another dialect and **lose rows**, and the strict parse agrees with the loss |
| `ignore_errors=true` | rows that do not fit are dropped |

The EDA Parquet builders now use `latam_eda.csvio.csv_to_parquet`: pinned dialect, record count reconciled against
an independent parser (Python `csv`, strict), ragged rows refused, and a VARCHAR column whose non-null values are
≥ 99% castable to a number, timestamp or boolean treated as a demotion; any of these raises instead of writing.

**Records, not lines.** A quoted field may contain newlines: `call_transcripts` has 925,351 lines but 171,321
records, the difference being exactly 754,030 embedded newlines. Every count in this chapter is by CSV grammar.

### A.2 Fingerprints
Computed for every file of every table in both copies (`scripts/raw_schema_scan.py`, cached under
`data/derived/raw_fingerprints/<copy>/`).

| level | per file / per (file, column) | why |
|---|---|---|
| **L0** physical | size, sha256, BOM, LF / CRLF / CR counts, UTF-8 decode errors, NUL bytes, records by grammar, ragged records, multi-line records, grammar errors | transport and encoding changes, truncation, replays (identical hashes), partitions out of place |
| **L1** header | names and order; BOM attached to the first name | a reader that keeps the BOM renames the primary key (`﻿transaction_id`) |
| **L2** lexical | count of each value class, first match wins: `empty`, `null_token`, `bool`, `ipv4`, `url`, `int_leading_zero`, `int`, `dec_dot`, `dec_comma`, `dec_thousands`, `sci`, `date_iso`, `date_dmy`, `ts_space`, `ts_t`, `ts_tz`, `time`, `ipv6`, `json`, `text`; length min/avg/max, non-ASCII count, untrimmed count, max fractional digits, median log10 of numeric values | format, separator, precision and type changes |
| **L3** semantic | per-file vocabulary of every column with ≤ 300 distinct values | category births and deaths, renames, translations, case and accent variants |
| **L3b** invariants | row rules on the raw text, e.g. `process_date` vs event date, FX consistency, lifecycle order, coordinates | semantic drift that a schema cannot express |
| **L4** relational | primary keys repeated across files, foreign-key coverage per day | restatements, replays, late-arriving dimensions |

**Inferred type.** A lattice of types and the classes each represents without loss:
`boolean{bool} ⊂ integer{int} ⊂ decimal{int, dec_dot, sci}`, `date{date_iso}`,
`timestamp{ts_space, ts_t, ts_tz, date_iso}`, `time`, `json`, `ip{ipv4, ipv6}`, else `string`. The inferred type is
the first type covering ≥ 99.9% of the non-empty values; the rest are **minority formats**, listed per file.
Leading-zero integers are codes: no numeric type may hold them. The inferred, versioned **contract** of a table
(type, formats and shares, empty share, length, vocabulary for low-cardinality columns; version = content hash)
is written to `eda/reports/contracts/<table>.json` and is the seed of the silver contracts (section C).

### A.3 Change detection (`latam_eda.change_detection`)
Each fingerprint becomes a daily series.

**Discrete signals** (a class, a vocabulary value, a header, a file property present on a day) are classified
with a **geometric run test**. Within its own span (first to last day seen) a value recurs with daily rate `p`;
under a stationary presence a run of `L` absent days has probability `(1 − p)^L`, so an absence of `L ≥ k` days before
the first sighting (after the last) is significant when `(1 − p)^L < α` (α = 0.001, k = 7). This separates a value
launched months after the table starts, even if sparse afterwards, from a rare value that skipped a few days.

| kind | rule | meaning |
|---|---|---|
| stable | present on ≥ 98% of days | normal |
| born / died | significant absence before the first / after the last sighting | **schema evolution**, dated |
| episode | significant absence on both sides | evolution that was later reverted |
| intermittent | no significant absence | a rare but normal value (e.g. `is_fraud = True`): not reported |
| transient | present on < k days in total | an **incident**, not an evolution |
| coexisting | ≥ 2 formats stable in one column | design or **source heterogeneity** (input to section E) |
| burst | > 50 unstable values in one column | e.g. numbers flooding a code column after a column swap: one finding, not thousands |

A died value changes on the day after it was last seen; all others on the day first seen.

**Continuous signals** (a class share, an empty share, a log10 scale) are tested for sustained shifts by **binary
segmentation with a permutation test**. For a segment `x₁..xₙ` the statistic is the maximum standardized CUSUM

  `T = max_k |Σᵢ≤ₖ (xᵢ − x̄)| / √(k (n − k) / n)`,

and its null distribution comes from 199 permutations of the segment. Permuting destroys any change point while
keeping the marginal distribution, so the false-alarm rate is controlled at α (0.01) on the data itself, without
normality or independence assumptions about the level. Significant splits recurse. A split is
reported only if the share moves by **≥ 5 percentage points** (materiality), and all material splits of one series
are reported as **one transition** (level before → level after, first and last change date): a gradual ramp
produces nested splits that a reviewer needs as one event. PELT with a permutation-calibrated penalty is available
as a slower cross-check. Also available: two-sided tabular CUSUM on
weekday-adjusted values, binomial rate tests against a reference window with Benjamini–Hochberg FDR control,
Jensen–Shannon distance between consecutive days' class shares and Jaccard similarity of vocabularies with a
robust z-score.

**Scale steps.** A step `Δ` in the daily median of log10 values is reported only if `|Δ| ≥ 0.1` (a factor of 1.26):
at millions of rows a 0.7% step is significant and meaningless, so **effect size comes first**. Steps near
log10 of a power of ten or of a known FX rate (`x1000`, `COP/USD ~4000`, `ARS/USD ~350`) are **unit changes**; any
other material step is a **level shift**, i.e. distribution drift handled by section F, not a schema change.

### A.4 Positive controls: the detectors are measured, not assumed
1. **Synthetic mutations** (`scripts/mutate_partitions.py`, `latam_eda.mutations`): ten known changes injected into
   copies of 90 real daily transaction files from day 45, keeping the original dialect: renamed category, decimal
   comma, `dd/mm/yyyy` dates, timezone suffix, ×1000 unit, swapped columns, lost leading zeros, BOM removed, ragged
   rows, an unterminated quote. Findings are compared with a clean copy of the same window, so genuine variation of
   the data is not counted as a false alarm. Output: `eda/reports/tables/forensics_detector_scorecard.csv`.
2. **The backup copy**: a real, known-different source (translated vocabularies, redenominated amounts). The raw
   text alone must reveal both.

### A.5 Results (main and backup copies, 12,504 files, 44.3 M records)
Evidence: `eda/reports/notebooks/model_risk/01_raw_schema_forensics.html`; tables `schema_change_log.csv`
(29 findings), `raw_format_anomalies.csv`, `propagation_audit.csv`, `forensics_detector_scorecard.csv` in
`eda/reports/tables/`; contracts in `eda/reports/contracts/`.

**Detectors.** 10/10 injected changes found, median delay 0 days, 0 false alarms before the change (against a clean
copy of the same 90 days).

**Structure is sound.** One header per table in every partition of both copies; raw lines − headers − embedded
newlines = records with **0 unexplained** for all 24 (copy, table) pairs; no ragged rows, grammar or encoding
errors; no duplicate, empty or cross-file primary keys; no minority formats in typed columns. Every file is BOM-
prefixed with CRLF line endings (transcripts add LF inside quoted text).

**Undeclared changes and traps found in the content:**

| finding | evidence | layer that acts |
|---|---|---|
| A null leaked into source text: `subject = "¡Oferta especial en nan!"` | 38,142 sends (6.8% with a subject), 2024-01-12 → 2026-05-09 | silver flag (V/I), report to source |
| Channels added and removed mid-stream: WhatsApp born 2023-07-10, Voice 2023-12-01 → 2026-03-23, both untracked | vocabulary birth/episode; `was_opened` empty share 6% → 25%, `open_*` ~62% → ~72% | per-channel funnel KPIs; instrumentation drift, not behaviour |
| `process_date` is a batch-window date | daily windows start at 06:00 (transactions, digital, sends), 08:00 (contact center, complaints), 10:00 / ~42 h (surveys); 25–79% of rows have a later event date; timestamps carry no timezone | date facts by event timestamp; record the timezone assumption |
| ≥ 3 source systems | the three cut-off families, identical in both copies | phase E |
| `México` / `Mexico` | `transaction_country`, `ip_country` | conformed country dimension |
| Coordinates near (0, 0) are placeholders | 407,656 USD transactions, some in scientific notation | null in silver |
| Codes with leading zeros | `postal_code`, `document_number`, `product_number`, `response_code` | must stay text (they did in the typed copies) |

**Propagation audit.** In 103 columns an empty raw field became NULL in the EDA Parquet and bronze v1; meaning
survives (the raw files have no null token) but representation does not, which lossless bronze (B) fixes. No
leading zeros or timezone suffixes were lost and no rows were dropped.

**Backup copy as a real positive control.** The raw text alone reveals the translated vocabulary
(`Inbound Call` → `Llamada Entrante`), different null semantics (`was_clicked` empty on 87,081 rows where main
writes `False`), two missing tables and 453 days of transactions. It does **not** reveal the COP → USD restatement
of products (÷ 4,000) found by record linkage: per-currency medians and the currency mix are identical, because
whole entities moved between currencies while every marginal distribution was preserved. **Column-level forensics
are necessary but not sufficient; entity-level restatements need record linkage on natural keys (E).**

## B. Lossless bronze with a byte-exact proof

### B.1 What is stored
`data/lake/bronze_raw/` (and `holdout_raw/` for facts from the stream cutoff, `quarantine/backup_20260831_raw/` for
the untrusted copy) is the **bronze of record**. Every landed record is kept with every field as the **exact text that
was written**: no trim, `''` stays `''`, nothing is typed. Each row carries `_source_file`, `_source_sha256`,
`_record_no`, `_record_sha256`, `_parse_status` (`ok`, `ragged`, `quote_error`, `encoding_error`), `_partition_date`
(from the Hive path, never from the content), `_ingest_run_id`, `_ingested_at`, and `_raw_record`: the record's exact
bytes, kept **only** when the record does not parse or its minimal-quoting re-serialisation would differ. Silver
reads this zone directly (section C); the typed bronze it replaced is archived read-only.

### B.2 The proof
`raw_records.py` splits a file on its bytes: a record ends at a newline outside quotes (RFC 4180), so quoted LF/CRLF
stay inside a record. For every file, **before anything is written** (`bronze_raw.build_table_raw`):

1. `sha256(file)` equals the landing manifest (the file did not change after it landed);
2. `sha256(BOM + header + Σ records)`, each record rebuilt from its stored fields (or its kept bytes), equals the same
   value: the stored parts **are** the file;
3. an independent strict CSV parser (Python `csv`, no shared code with the splitter) counts the same records.

Any failure raises `BronzeIntegrityError` and the run stops. **Verification is independent of the build**:
`verify_table_raw` rebuilds every file again from the Parquet **on disk** (one partition at a time, flat memory) and
compares with the landing sha256, so a changed value, a deleted record, a file stored twice or a landed file never
stored all fail. Partitions are append-only (a changed partition digest is refused); new partitions and the proof
manifests (`manifests/bronze_raw_proof/`) are copied to the object-locked `bronze-worm` bucket (`seal_raw`).

### B.3 Results (backfill, 2026-10-03)
| copy | files | records | rebuilt byte-exact at build | re-verified from storage | records needing raw bytes |
|---|---|---|---|---|---|
| main | 7,671 | 23,495,188 | 7,671 | 7,671 (0 problems) | 0 |
| backup | 4,833 | 20,804,992 | 4,833 | 4,833 (0 problems) | 0 |
| **total** | **12,504** | **44,300,180** | **all** | **all** | **0** |

Every record parsed `ok` and re-serialises canonically, so the lossless zone costs about the same as the fields alone.
Build: 8.4 min (main, 8 workers, peak 1.8 GB); verification: 3.7 min (peak 0.9 GB).

**Parity with typed bronze** (main, joined on primary keys): 552.9 M cells compared, **0 value mismatches** (each typed
value equals `try_cast` of its raw text). The only difference: **171.9 M cells where typed bronze holds NULL for an
empty string**, which the lossless zone keeps as written.

**On the running stack** (Airflow 3.1 scheduler, 4 GB limit): `build_raw` re-proved all 1,097 transaction files and
wrote 0 partitions (append-only no-op); `verify_raw` passed for transactions and for the 15.6 M digital events. The 24
proof manifests were sealed to `bronze-worm` with COMPLIANCE retention, a delete was refused, and
`audit_ledger.verify_all` reported no break in any chain. The bulk partition upload (≈ 3.1 GB locked for the
retention period) was not run on the demo laptop; it is covered by a unit test of `worm_sync` and runs on the
first scheduled `bronze_build`.

## C. Contract-driven silver and cell-level findings

### C.1 Source contracts
`platform/contracts/sources/<table>.yml` is the reviewed statement of what each source column **is**. It was seeded
once by `platform/dbt/scripts/generate_source_contracts.py` from the inferred contracts of A, the types typed bronze
had (so silver keeps exactly the types it had), and lossless bronze, and is changed only by pull request.

| per column | meaning | count (260 columns, 13 tables) |
|---|---|---|
| `type` | DuckDB target type | 93 typed, 167 text |
| `required`, `empty_share` | an empty or absent value is a finding; the baseline empty share | 157 required |
| `formats` | value classes of A accepted for the column: numbers accept every lossless spelling (`int`, `dec_dot`, `sci`), temporal and other typed columns only what the source has used | 95 |
| `key_pattern` | identifier shape, `^PREFIX-[0-9A-Z]{n}$` when every value shares one prefix and length | 36 |
| `vocabulary`, `variants` | closed set of a low-cardinality column (not PII, not free text, not multi-valued) and its other spellings, mapped to the most frequent one | 92 (variants: `Mexico` → `México` twice) |
| `scale` | baseline median and MAD of the daily log10 median magnitude | 36 (3 multimodal columns excluded, below) |
| `scan` | placeholder leaks searched in free text: a null rendered into a sentence, an unrendered `{slot}` | 10 |
| `pii` | restricted class: the value appears in findings only as a shape | 24 |

The value classes live in `platform/contracts/value_classes.yml`, which a test keeps identical to the forensics
(`latam_eda.raw_forensics.CLASSES`): a format means in silver exactly what A measured.

### C.2 Typing without loss and cell-level findings
`scripts/generate_silver_from_contracts.py` turns the contracts into SQL. **One function produces every predicate**,
so the typed models, the findings and the partition profile cannot disagree; a platform test fails CI when the
generated files are stale. `silver.typed_<table>` (13 tables plus the two holdout slices) reads lossless bronze:
`''` and absent fields become NULL, every other value is cast explicitly (`try_cast` to the contract type), and
`_dq_issues` lists each breach as `<column>:<code>`. **Every bronze record is kept.** Staging reads the typed models
instead of typed bronze, with the same column names and types, so nothing downstream changes.

| code | rule | breach | severity, SLO |
|---|---|---|---|
| G | C07 | record breaks the CSV grammar (`_parse_status` not ok) | A, 0 % |
| T | C01 | non-empty value does not cast to the contract type | A, 0.1 % |
| F | C08 | value casts but in a format the contract does not accept | B, 0.1 % |
| N | C02 | required value empty or absent | B, 0.1 % |
| K | C05 | identifier breaks the key pattern | A, 0.1 % |
| V1 / V2 | C03 / C04 | value outside the vocabulary / variant spelling | B, 0.1 % / C, measured |
| P / S | C06 / C09 | null rendered into free text / unrendered template slot | B, measured / C, 0 % |
| — | C10 | rows of a held partition | B, 0 % |

`audit.dq_cell_findings` holds one row per flagged cell with its lineage (`source_file`, `record_no`,
`record_sha256`, entity key, contract version); personal data and free text appear only as a shape (`A` letter,
`9` digit). `audit.dq_rule_summary` adds the C-rules per table next to the row rules (R01–R27), counted over the rows
that flow on to gold, and the existing `dq_gate` blocks on enforced severity-A breaches. `audit.dq_findings` shows
both in one shape: the work list for phase D.

### C.3 Schema-drift circuit breaker
Inside the silver layer, between the typed models and staging:

* `dq_partition_profile`: per partition and contract column, from the raw text: absent, empty, cast failures,
  foreign formats, broken keys, new and variant vocabulary, placeholders, log10 median magnitude;
* `dq_partition_header`: the header of every landed file (from the proof manifests of B) against the contract:
  missing and unknown columns, changed order;
* `dq_schema_drift`: every failed check with observed value and threshold. **Severity A** (holds): a header change,
  a grammar failure, an absent column, a required column more than 0.1 % empty, more than 0.1 % of values that do
  not cast or are in a foreign format, more than 0.1 % broken keys, more than 20 % new vocabulary, or a scale step
  (|Δ log10 median| ≥ 0.5 and robust z > 6 against the contract baseline). **Severity B** (reported): new vocabulary
  below 20 %, an empty share moved by 30 points or more;
* `dq_partition_holds`: severity-A partitions minus reviewed releases (seed `dq_partition_releases`). Staging
  excludes their rows (macro `not_held`), so nothing built on a partition whose schema changed reaches gold,
  features or serving; the rows stay in bronze and in the typed models. The `drift_holds` task of `dbt_lakehouse`
  opens one `schema_drift_partition_held` trigger per new hold (`latam_platform.drift_holds`, idempotent).

**A statistic must be stable before it can hold data.** The scale check first ran with every numeric column and
held 523 transaction partitions on `latitude`: the daily median magnitude of coordinates is bimodal (cities vs the
null-island points of A), so it jumps by a factor of 4 on about half of the days. The contract generator now
measures this: a column whose own history crosses the scale threshold in more than 5 % of partitions gets no scale
check, with the reason in the contract (`transactions.latitude` 47 %, `longitude` 50 %, `campaign_sends.send_cost`
45 %).

### C.4 Results (2026-10-03)
Every number below is reproducible: the tables, the scripts that produce them (`platform/dbt/scripts/verify/`) and
the commands are in [`evidence/phase3/`](evidence/phase3/README.md).

**Parity.** The typed models reproduce typed bronze exactly: 23,413,140 rows in 15 models, same counts, same column
types and identical order-independent hashes of every value. Built end to end (222 dbt nodes, 0 errors), the
lakehouse from lossless bronze was compared relation by relation with one built from typed bronze (commit
`acac8e1`) in the same environment, and two builds of that baseline were compared with each other to measure the
noise floor: they differ by themselves in 22 relations (surrogate keys hashed with the snapshot time,
floating-point sums in parallel aggregation, list and row order, ties in `mode()`). Against the switch, 60 of 84
shared relations are identical and 22 of the 24 differences lie inside that noise; the other two are intended (the
partition manifest now digests the records' landed bytes; the rule summary adds the C-rules). **No change is
attributable to the switch.** (Corrected on 2026-10-04: the first comparison combined hashes with XOR, which cancels
repeated values and under-reported the noise as 18 relations; see the evidence README.) The noise itself is removed by
the reproducibility fix: two builds now agree on all 108 relations ([evidence](evidence/reproducibility/README.md)).

**Findings on the real data** match the forensics of A: 1,078,689 `Mexico` variants (V2, `transactions` 0.92 %,
`digital_events` 6.65 %), the 38,142 campaign subjects with a rendered `nan` (P, 2.25 %), and **no** grammar,
cast, format, required, key or unknown-vocabulary breach. No partition is held. Severity B reports empty-share
shifts in 32 `campaign_sends` partitions (`was_opened`, `subject`). The gate passes; the only SLO breaches are the three row
rules already known and not enforced in dev (R21, R25, R26).

**Positive control.** Mutated copies of real partitions in a scratch lake:

| mutation | check | outcome |
|---|---|---|
| `amount` with a decimal comma (`transactions` 2025-03-13) | format, 5,016 values do not cast | held |
| `amount` × 1,000 (2025-04-04) | scale, × 1,405, robust z 58 | held |
| `transaction_type` translated to Spanish (2024-12-30) | vocabulary, 100 % new | held |
| `browser` dropped from the file (`digital_events` 2025-06-01) | absent, 9,397 of 9,397 | held |
| an unknown column in a landed header (2025-06-10) | header_extra | held |
| 5 rows with a new channel `Kiosk` (2025-05-01) | vocabulary, 0.1 % | **reported, not held** |

Exactly the 5 severe partitions were held; staging and gold lost exactly their rows (18,382 transactions, 9,397
digital events) while the typed models kept all 4,294,318 and 15,187,552; the gate reported them as C10 and not as
cast failures; `drift_holds` opened 5 reviews and none on a second run.

**Cost.** The typed, breaker and findings models build in 24 s on their own (profile 22 s, findings 23 s, in
parallel); a full build (222 nodes) takes 3 min 39 s, against 1 min 48–57 s for the 193 nodes of the typed-bronze build: every
read of a staging view now casts from text, and the profile and findings scan all 23.4 M records.

## D. Audited correction and restore
Designed. Corrections never touch bronze. A steward explores findings in a notebook workbench (pattern groups,
impact preview) and writes a proposal; an Airflow DAG validates it, records it in the hash-chained audit ledger and
asks for **four-eyes approval** through Airflow's human-in-the-loop operators (approver ≠ proposer). Silver applies
approved corrections as an overlay (`_corrected_by`); a revert removes the overlay and restores the original value.
Silver can be rebuilt as of any point of the ledger.

## E–H. Later phases
* **E. Keys and source systems:** opaqueness of the raw identifiers (per-position χ², entropy vs log₂36, order vs
  time), re-keying between copies, natural-key checksums, source-system clustering from the dialect fingerprints of
  A, and the durable-key / surrogate-key design.
* **F. Drift and concept-drift MRM:** effect-size-first battery (PSI/CSI, KS, Anderson–Darling, Cramér–von Mises,
  Wasserstein/IQR, Jensen–Shannon, Hellinger, χ²/Cramér's V, MMD, classifier two-sample test) with block-bootstrap
  null thresholds and measured power; ADWIN, DDM, Page–Hinkley, calibration and performance drift with confidence
  intervals; monitoring plan mapped to `compliance.trigger_event`.
* **G. Segmentation and feature importance:** tests that segmentation is warranted (ICC, likelihood-ratio and Chow
  tests, conditional mutual information, model-based recursive partitioning, IV/WoE) and predictive proof with
  time-split confidence intervals; SHAP and permutation importance with rank stability.
* **H. Text:** redaction, template and near-duplicate detection, sparse, topic and local-embedding representations,
  ablation lift, embedding drift, topic dimensions and marts.
