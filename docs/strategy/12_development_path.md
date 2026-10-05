# 12 · From evidence to build plan

[← 11 plan evaluation](11_plan_evaluation.md) · [index](README.md) · next: [data readiness audit →](13_data_readiness_audit.md)

Chapters 01–11 were written before the platform existed. Since then the platform was built (`platform/`, release
v0.2.0) and judged by these analysis series:

- **Pipeline walkthrough** (`eda/notebooks/pipeline/`): every dbt model replayed step by step in a scratch DuckDB.
- **Country series** (`eda/notebooks/country_{all,mx,co,ar}/`): the whole platform rebuilt and judged per country
  and for the whole bank.
- **Backup-as-main series** (`eda/notebooks/backup_*`, `dataset_compare/`): `data_backup_20260831` run through
  the platform as if it were the source.
- **Granularity series** (`eda/notebooks/granularity/`): the star re-grained to customer, day, month and other
  aggregates.
- **Granularity series II** (`eda/notebooks/granularity_time/`): the hour, the clock and the campaign decision cell
  (E13–E15).

This chapter turns their results into the build plan for analytics, data marts, ML, deep learning and agents. Every
figure cites the notebook or table it comes from; the tables are in `eda/reports/tables/`. It amends chapters 08
and 10 where the evidence disagrees with them (see [10 §10.0](10_roadmap_and_team.md)).

Decisions taken here are recorded as [ADR-011](../platform/adr/ADR-011.md) (country-keyed configuration),
[ADR-012](../platform/adr/ADR-012.md) (evidence-gated model portfolio),
[ADR-013](../platform/adr/ADR-013.md) (data completeness and dataset identity controls) and
[ADR-014](../platform/adr/ADR-014.md) (timestamps carry an explicit clock).

## 12.1 What the experiments established

| # | finding | evidence | consequence |
|---|---|---|---|
| E1 | `pii_hash(NULL)` gives one constant token: one IP node links 143,222 of 150,000 customers (95 %) | `country_all/10`; pipeline 10 | graph learning and entity resolution are blocked until tokens preserve NULL |
| E2 | SCD2 version 1 is valid only from registration or opening, so 19.3 % of transactions lose `customer_sk`, 19.3 % lose `product_sk` and 33.8 % lose at least one | `country_all/06`; pipeline 06 | the star schema misreports every BI slice by customer or product attribute |
| E3 | `mart_credit_eligibility` reads `feat_credit_eligibility_pit`, built in a later task group | pipeline 01 (forward dependencies) | eligibility is served from the previous run's features |
| E4 | dispute candidates trust the complaint's `affected_product_id`, which belongs to another customer (R25, 66 %): of 11,803 disputes with a transaction in the window, 24 keep a candidate | `country_all/07`; pipeline 07 | dispute intake cannot link the disputed transaction |
| E5 | AML `PEER_OUTLIER_INFLOW` is dead: a defined peer z-score on 0 of 2,626,563 customer-months (peer MAD = 0) | `country_all/08` | one typology silently never fires |
| E6 | the `confirmed_fraud*` columns count the legacy label, which is a function of `fraud_score` | pipeline 07 | a card-block rule on them blocks on a score, not on confirmed fraud |
| E7 | the bank-wide contract would hold 1,099, 1,099 and 1,098 days of Mexico, Colombia and Argentina (typical amounts 0.09×, 307× and 27× the blend); contracts with country baselines hold none | `country_{mx,co,ar}_contract.csv` | contracts, SLOs and gates must be keyed by country |
| E8 | rule rates are national: R17 is 100 % in Mexico and 0 % elsewhere; R18 exists only where pesos do | `country_*_rule_slo.csv` | bank-wide SLOs describe no country |
| E9 | behaviour is the same in every country and in both datasets: on the delivery-day clock (E13) Saturdays and Sundays are about 39 % below weekdays in every market (the earlier 31–42 % spread and the Argentine Monday dip came from legal local time); no holiday, payday, month-end or bonus effect at 1 % in any country; no abnormal day and no change point | `country_*_calendar_effects.csv`, `*_anomalies.csv`, `dataset_compare/01`, `granularity_time_reconciliation.csv` | calendar features stay, but the data cannot validate them; re-measure on real data |
| E10 | only dormancy is learnable out of time (AUC 0.728, the six-month transaction count alone 0.726); fraud, complaint in 90 days, delinquency and contact escalation show no evidence of signal; campaign conversion is weak to moderate (0.63–0.65) | `country_*_learnability.csv` | rules first; one transparent model first (§12.4) |
| E11 | the backup run as main: transactions stop on 2024-09-25 and two tables are missing, and **no control notices**; the breaker holds every call-centre and campaign day; only reconciliation names a different dataset | `dataset_compare/01`, `backup_*` | completeness and identity controls are missing ([ADR-013](../platform/adr/ADR-013.md)) |
| E12 | every testable model verdict is the same on the backup as on main | `backup_*_learnability.csv` | the conclusions are properties of the generator and do not depend on the source |
| E13 | every process runs on its delivery day: timestamp −6 h (transactions, digital, sends) or −8 h (contacts, complaints) equals `process_date` for 100 % of rows, in every market; legal local time is wrong for this source, and R15/R16 test the wrong window (their ~8 % violations are 2 of 24 hours) | `granularity_time/01`, `granularity_time_clock.csv` | declare the clock ([ADR-014](../platform/adr/ADR-014.md)); fix `enrich_transactions`, R15 and R16 |
| E14 | the hour carries no information beyond the day (dispersion index 0.98–1.01), no sub-day sequence or burst exists (0 of 35 lead tests), and hourly monitors need negative-binomial limits (Poisson over-alerts 5×) | `granularity_time/02`, `/03` | no hourly fact table; hourly monitors in the streaming layer only |
| E15 | Voice and WhatsApp record no opens, so they cannot attribute a conversion (22 % of contacts unmeasured); the conversion value is a flat ~2,550 USD whatever the product (not a margin); within a channel no cell differs; reallocating a fixed number of sends by channel converts +22 % (95 % interval +18 to +26 %) in an out-of-time replay | `granularity_time/04`, `/05`, `granularity_time_allocation.csv` | instrument before cutting; allocate under a contact budget; confirm with a randomised holdout |
| E16 | at the hour, no rate, attribute, customer habit, channel rhythm, event order or send-time effect exists (52 tests, 1 material and mechanical); 11 hour-grain models trained: 0 green, 2 amber, 9 red; teller activity ignores branch opening hours (59 % outside, as schedule-blind activity gives); agent shifts are unrelated to the hours worked; the SLA flag does not follow the regulatory clock (κ ≈ 0); the gold session date uses the UTC day | `granularity_hour/01`–`/09`, `granularity_hour_readiness.csv` | the data collection audit ([13](13_data_readiness_audit.md)); deterministic hour products ship, models wait for their gates |

All six platform defects (E1–E6) passed 107 green data tests. Each is plausible but wrong data: a key that is NULL
instead of a missing row, a token that is valid but shared, a rule that returns nothing instead of failing. **Test
the invariants of the business, not only the shape of the data.**

## 12.2 Data marts: what each one is for, and whether it is ready

Figures are from the whole-bank main run (`country_all/07`, `08`, `11`). The marts and their columns are in
`platform/dbt/models/gold/marts/_marts.yml`; bundles B1–B6 are in [08 §8.1](08_ml_dl_ai_agents.md).

**Readiness key:**
- **ready**: correct today; the caveat is documentation only.
- **after fix**: usable once the listed fix in §12.7 lands.
- **blocked**: the business purpose cannot be met until a data or process change.

| mart (serving table) | business decision it serves | consumer | readiness | what gates it |
|---|---|---|---|---|
| `mart_customer_360` (`serving_customer_360`, 150,000) | who is this customer: holdings, activity, service and risk context | B1 agent context, analysts, B4 targeting | **ready** | tokens of missing contacts are shared (E1) for any linkage use |
| `mart_account_payment_inquiry` (`serving_account_inquiry`, 400,000) | balance, pending and declined payments per product: "where is my payment" | B1 copilot | **ready** | money direction is assumed from transaction type; ask the source for signed amounts |
| `mart_product_recent_transactions` (`serving_recent_transactions`, 4.28 M) | the last 20 movements per product | B1 copilot | **ready** | none |
| `mart_card_support` (`serving_card_support`, 140,040) | next best action per card: 55,495 cards to reissue (39.6 %), 6,847 to unblock after strong authentication, 499 fraud blocks | B1 copilot, card operations | **after fix** | the fraud-block action reads the legacy label (E6) |
| `mart_transaction_disputes` (`serving_dispute_case`, 26,351) | link a complaint to the disputed transaction; SLA clock | B1 dispute intake, B2 evidence | **blocked** | candidate filter (E4) and no disputed-transaction key at intake |
| `mart_credit_eligibility` (`serving_credit_eligibility`, 150,000) | pre-approval with adverse-action reason codes: 649 card and 835 loan approvals; 96.5 % declined for insufficient income history | B3 | **after fix** | build order (E3); deposit-only inflows of 0.8 a month cannot show income (signed amounts needed) |
| `mart_collections_early_warning` | delinquency bucket and early-warning score per credit product | B3 collections | **after fix** | the score cannot separate unknown from late; no history of days past due (keep the SCD2 snapshots running) |
| `mart_aml_customer_month` | AML typologies per customer-month: income inconsistency (12,974), near-threshold structuring (1,190), multi-jurisdiction, cash-intensive, rapid in-out | B2 analysts | **after fix** | dead peer typology (E5); thresholds in USD instead of each country's line (Colombia: 2,726 cash transactions just under COP 10 M) |
| `mart_cx_journey` | contact outcomes: first-contact resolution, repeat contact in 7 days, complaint within 14 days | contact-centre operations, B1 KPIs | **ready** for reporting | transcripts are templates (R27, 100 %); the escalation label has no signal (E10) |
| `mart_campaign_compliance_uplift` | consent check and contact pressure per send: **50.06 % of sends went to customers without current consent** | B4 compliance, marketing | **ready** for compliance; **blocked** for uplift | no randomised holdout, so uplift is unidentified; consent has no history |
| `serving_online_fraud_state` (134,515) | per-card state for the real-time scorer | B2 fraud rules and anomaly monitor | **ready** as rules plus an anomaly monitor | no confirmed labels (E6, E10) |

**What to ship first from the marts** (deterministic value now, no model needed):
1. **Consent gate.** No send without current consent, reported from `mart_campaign_compliance_uplift`.
2. **Card reissue campaign** for the 55,495 cards marked `REISSUE_CARD`.
3. **Service copilot read path** over the four ready B1 tables (§12.6).
4. **AML analyst queue.** The typologies plus the isolation forest, which agrees with the rules 12–15× more than
   chance (`*_anomalies.csv`).

## 12.3 Analytics path

1. **A semantic layer over the gold star**, built only after the SCD2 fix (E2). Until then, 33.8 % of transactions
   drop out of any join to a customer or product attribute.
2. **Country-keyed metrics.** Every metric is defined per country and in USD:
   - amounts are never pooled across currencies;
   - the business day is the declared delivery clock ([ADR-014](../platform/adr/ADR-014.md)), and the country
     calendar comes from `country.calendar` (to be promoted to a dbt seed, see §12.7).
3. **KPIs per bundle** ([10 §10.2](10_roadmap_and_team.md)), each bound to its source column:

| bundle | KPI | source |
|---|---|---|
| B1 | first-contact resolution, repeat contact in 7 days, complaint conversion | `mart_cx_journey.was_resolved`, `repeat_contact_7d`, `complaint_within_14d` |
| B1 | groundedness of agent answers (target 100 %) | `genai_audit` records against the serving tables |
| B2 | alert precision at analyst capacity | AML queue outcomes (to be captured) |
| B3 | approval rate, adverse-action reasons | `mart_credit_eligibility.decline_reasons` |
| B4 | sends without consent (target 0), conversion against a holdout, attribution coverage, conversions per 1,000 sends by channel | `mart_campaign_compliance_uplift`, `fct_campaign_cell` (proposed) |
| B5 | A-rule SLO breaches, held partitions, completeness gaps, reconciliation result | `audit.dq_rule_summary`, `dq_partition_holds`, the controls of [ADR-013](../platform/adr/ADR-013.md) |

## 12.4 ML path: evidence-gated

The protocol of `eda/notebooks/country_template/14`:
- point-in-time features;
- an out-of-time split;
- gradient boosting;
- AUC with Hanley–McNeil intervals and AP against the base rate;
- a one-feature baseline;
- the leaking `fraud_score` as a positive control (AUC 0.78–0.85 on every run).

A target gets a model only when it passes this protocol. Until then it gets rules and the data collection named in
its **entry criterion** ([ADR-012](../platform/adr/ADR-012.md)).

| target | evidence (whole bank, main) | decision now | entry criterion to revisit |
|---|---|---|---|
| dormant in the next 90 days | AUC 0.728 [0.725, 0.731]; `tx_6m` alone 0.726; the same in every country and on the backup | **build first**: a per-customer rate model (P(no transaction in 90 days) = e^(−3λ)), with the one-feature rule as the benchmark | in production: average precision on recent quarters, PSI of inputs |
| campaign conversion | AUC 0.652 bank-wide (0.63–0.64 per country), AP lift 1.5; driven by send channel × segment | channel × segment contact rule; **randomised holdout per campaign** | a holdout exists, then uplift learners |
| fraud (honest) | AUC 0.504; no single feature excludes 0.5 | rules plus the unsupervised ensemble as an analyst monitor, never a decline | confirmed fraud labels with dates (chargebacks, analyst outcomes) |
| complaint in the next 90 days | AUC 0.501 | rules on contact history | real transcripts and complaint–contact keys |
| more than 30 days past due | AUC 0.503 | transparent early-warning rules | days-past-due history from the SCD2 snapshots (at least 12 months) |
| complaint within 14 days of a contact | AUC 0.494 | QA sampling rules | real interactions and transcripts |

## 12.5 Deep learning path

| family | status | unblock condition (measurable) |
|---|---|---|
| graph learning on the entity graph (`graph_*`, GraphSAGE, HGT) | **blocked** | no token links more than a handful of customers (a uniqueness test on `pii_hash`); then rebuild the graph |
| temporal graph networks (`tgn_*`) for mule rings and Brazil's MED 2.0 tracing | **blocked** | transfer counterparties in the source (a contract field, mostly filled for transfers), plus confirmed labels |
| federated graph learning (`fgl_*`, [ADR-010](../platform/adr/ADR-010.md)) | built; at chance on this data | the two conditions above; the per-country silos already match the residency design |
| sequence models on payments | phase 4 | months of real, labelled history |
| Kumo-style relational probes | keep as learnability probes | none; run them on real data as the first check of each new target |

## 12.6 Agentic path: the service copilot first

The copilot reads only the `serving_*` tables through narrow, parameterised, read-only tools. Ownership is checked
in SQL and every call goes through `genai_audit.AuditedLLM` ([platform 08](../platform/08_agentic_interfaces.md)).
The LLM explains; it never computes an amount or takes a decision.

| tool | reads | live when |
|---|---|---|
| `get_customer_summary` | `serving_customer_360` | now |
| `get_account_status` | `serving_account_inquiry` | now |
| `get_recent_transactions` | `serving_recent_transactions` | now |
| `get_card_status_and_action` | `serving_card_support` | after the fraud-label rename (E6) |
| `explain_eligibility` (reason codes only) | `serving_credit_eligibility` | after the build-order fix (E3) |
| `open_dispute` (write intent, human in the loop, captures `disputed_transaction_id`) | `serving_dispute_case` | after the candidate fix (E4) and the intake change |
| `search_policies` | `kb.active_chunk`, Neo4j | now |

**Release gates for any agent version:**
- **Groundedness:** 100 % of numbers in answers match a tool result, on a golden set drawn from the marts.
- **Prompt injection:** the red-team pass rate is above its target.
- **Regulatory clocks:** each country's deadline is read from a compliance-owned seed (CONDUSEF, Superfinanciera,
  BCRA; [ADR-011](../platform/adr/ADR-011.md)), never hard-coded.

## 12.7 Platform work, in order

**P0, before v0.3.0** (high impact, small effort):
1. `pii_hash` keeps NULL as NULL; NULL tokens excluded from graph edges; a token-uniqueness test (E1).
2. SCD2 version 1 valid from the beginning of time; `not_null` on `customer_sk` and `product_sk` (E2).
3. `mart_credit_eligibility` after the features task group; a CI check for forward dependencies (E3).
4. Dispute candidates ignore products the complainant does not own (E4).
5. Revive `PEER_OUTLIER_INFLOW` (peers over months with inflow, or a quantile rule); a planted-positive test per
   typology (E5).
6. Rename `confirmed_fraud*` to `fraud_flag*`; the card-block rule reads confirmed cases only (E6).
7. **Completeness and identity controls** ([ADR-013](../platform/adr/ADR-013.md)): an expected-partition calendar per
   fact table, row-count floors per source, empty windows and splits that fail, `source_held` carried to the
   marts, and the reconciliation fingerprint when a copy is restored. Acceptance test: the backup-as-main run is held.
8. **Country-keyed configuration** ([ADR-011](../platform/adr/ADR-011.md)): contract baselines, rule SLOs, AML lines,
   regulatory deadlines and the calendar as country seeds; gates evaluated per country.
9. **Declared clocks** ([ADR-014](../platform/adr/ADR-014.md)): the contract seed names each timestamp's clock and
   delivery window; `enrich_transactions` derives local time and `is_weekend` from it; R15 and R16 test the −8 h
   window; a clock-drift control per process and month (E13).

**P1** (medium):
- the row-count reconciliation test `stg_transactions` = `int_transactions_enriched`;
- empty-share baselines conditional on applicability, with a binomial (noise-aware) band;
- the early-warning score separates unknown from late;
- a keyed HMAC tokenisation service before any real data;
- a periodic orphan-relation check;
- `fct_campaign_cell` promoted to gold with `open_tracked` and an `attribution_method` per send, and a monthly
  empirical-Bayes table of cell rates (E15);
- the hour-grain dimensions (`dim_process_clock`, `dim_time_of_day`, `dim_branch_schedule`) and `fct_case_clock` with business
  hours and a deadline seed per country and case type (E16);
- an integrity rule "teller transaction outside the declared schedule" (severity B) and, once rosters exist, shift
  adherence (E16);
- `fct_digital_session` dated by the delivery day, not the UTC day (E16);
- hourly counts per market and process in the streaming layer, with negative-binomial limits and a day-parity test
  (E14).

**Data and process requests to the source and the business:**
- signed amounts or a debit/credit flag;
- transfer counterparties;
- `disputed_transaction_id` at complaint intake;
- consent events with history;
- explicit time zones and delivery windows per timestamp (E13);
- an attribution method for Voice and WhatsApp (tracked links or codes), and the product margin per conversion (E15);
- confirmed fraud labels with dates;
- a randomised holdout per campaign;
- rostered shifts and agent state logs from workforce management, telephony queue events, branch opening days and
  hours, ATM terminal events, and clickstream order with page and product (E16, chapter 13).

## 12.8 Exit criteria for v0.3.0

1. P0 items 1–9 are merged, each with the test that would have caught it, and all pass in CI.
2. **Invariant tests green:**
   - every fact row reaches its dimensions;
   - no token links more than a handful of entities;
   - every typology fires on a planted positive;
   - no model reads a later task group.
3. **Controls proven on the backup:** the backup-as-main run is held by the completeness control and fails the
   identity fingerprint, while main passes.
4. **Per-country gates:** the per-country contract holds no healthy day in any country, and one country's breach
   does not block another's run.
5. **Dormancy model:** a model card, the one-feature benchmark, out-of-time AP with an interval, and a monitoring
   plan (AP on recent quarters, PSI of inputs).
6. **Copilot read path:** the three "now" tools, plus `search_policies`, pass the groundedness and injection gates of
   §12.6.
