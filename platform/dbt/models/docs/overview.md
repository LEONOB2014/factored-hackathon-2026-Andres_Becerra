{% docs __overview__ %}
# BETA AID · LATAM Bank lakehouse

**BETA AID** (Banking Evolutionary Transformation and AI Deployment) is an AI customer-service copilot and the
compliance-grade data platform beneath it, built for LATAM Bank's synthetic dataset: Mexico, Colombia and Argentina,
13 source tables, 2023-06-17 → 2026-06-17. This dbt project (`platform/dbt`) is the lakehouse: every model, test and
contract from typed silver to serving.

## Why this lakehouse exists: the AI readiness factory
Most of the candidate models this data was expected to support turned out not to be learnable. Out of time and
against transparent benchmarks, the eleven hour-grain models scored 0 green, 2 amber and 9 red. The lakehouse treats
that as a diagnosis, not a dead end:
1. **Measure.** Every fact is rebuilt as a Kimball star, per country and at three grains (`gold/aggregates`).
2. **Diagnose.** A readiness gate judges each candidate model and names the root cause when it fails: insufficient
   volume, generator independence, a missing field or a data defect (ADR-018).
3. **Prescribe.** Each red gate becomes a data requirement with an owner, an acceptance test and the threshold that
   turns it green.
4. **Fix.** The pipeline repairs what can be repaired, visibly: quality rules flag, four-eyes corrections, contracts.
5. **Re-judge and ship.** New data re-runs every gate; a green gate opens the model path.

The first product off the line is the card-service copilot. Its decision data was ready, so it reads the `serving`
contracts documented here.

## How the data flows
| Zone | Folder | Trust and data class | What it holds |
|---|---|---|---|
| bronze_raw (sources) | outside dbt | lossless evidence, personal | every landed record as its original text, with per-record lineage and a byte-exact proof per file (ADR-001) |
| silver | `models/silver` | typed against reviewed source contracts, personal | `typed_*` (contract typing behind the schema-drift circuit breaker), `quality` (cell-level findings, holds, corrections), `staging` and `conformed` (`int_*`) |
| gold/core | `models/gold/core` | governed Kimball core, tokenised | SCD2 dimensions and facts at their natural grain |
| gold/marts | `models/gold/marts` | use-case marts, tokenised | one mart per product decision (card support, disputes, credit eligibility, AML, collections, campaigns, CX) |
| gold/aggregates | `models/gold/aggregates` | multi-grain star, tokenised | day, cell and hour grains, generated from the EDA SQL with grain, reconcile and density contracts (ADR-017) |
| features · graph · knowledge | `models/features`, `models/graph`, `models/knowledge` | ML-ready, tokenised | point-in-time features, graph nodes and edges, knowledge-base entity docs |
| privacy | `models/privacy` | contribution-bounded inputs | inputs to differentially private releases (ADR-009) |
| serving | `models/serving` | published contracts | the tables published to Postgres `bank_serving` for products such as the copilot (ADR-003) |
| audit | `models/audit` | evidence | data-quality findings and rule summaries, SCD2 change log, governance checks |
| bigquery | `models/bigquery` | analytics layer, designed and not applied | BigQuery-native views per residency region (ADR-006, ADR-007) |

## Rules every model follows
- **Repairs are visible:** data-quality rules flag rows (`dq_r*` columns, see the rule catalog seed `dq_rule_slo`);
  they never overwrite. Corrections are four-eyes, write-once and revertible (chapter 09 §D).
- **Clocks are explicit:** see the `process_date` and `*_ts_utc` conventions (ADR-014).
- **Tokens, not identities, from gold onward.** Direct identifiers stay in silver.
- **Residency is metadata:** every model inherits `meta.residency: customer_country` (ADR-007).

## Where the decisions are recorded
- Architecture decisions: `docs/platform/adr/` (ADR-001 to ADR-021).
- Platform chapters: `docs/platform/01_architecture.md` to `09_data_and_model_risk_methodology.md`.
- The exploratory record: `eda/`.
- What each grain can support: the readiness gates (ADR-018).

The lineage graph (bottom right) shows how every model depends on the sources.
{% enddocs %}

{% docs col_process_date %}
The **delivery day** of the record: the business day the source assigned it to. The source's clocks are shifted, so
the delivery day is not the UTC date of the timestamp (ADR-014):
- transactions, digital events and campaign sends: timestamp **−6 h**;
- contact-centre interactions and complaints: timestamp **−8 h**.

Use `process_date` for daily and weekly business views, and the `*_ts_utc` timestamp for elapsed times.
{% enddocs %}

{% docs col_ts_utc %}
Event timestamp in UTC, as received from the source. For the business day use `process_date` (ADR-014).
{% enddocs %}

{% docs col_date_key %}
Foreign key to `dim_date` (the delivery day, `process_date`).
{% enddocs %}

{% docs col_customer_id %}
Customer identifier (tokenised business key). Joins to `dim_customer`; direct identifiers such as names and documents
never reach gold.
{% enddocs %}

{% docs col_scd2_validity %}
SCD Type 2 validity. A version is valid from `valid_from` (inclusive) to `valid_to` (exclusive; NULL for the current
version):
- `is_current` marks the latest version;
- `recorded_from` is the system time the platform first saw the version;
- `row_hash` fingerprints the tracked attributes.

The first observed version is treated as valid since registration, because no earlier history exists.
{% enddocs %}

{% docs col_dq_flag %}
Data-quality flag from the rule catalog (seed `dq_rule_slo`): TRUE when the row breaks the rule. Flagged rows are
kept, never dropped or silently repaired. Each rule has a severity and a service-level threshold enforced by the
quality gate.
{% enddocs %}

{% docs col_amount_usd %}
Amount in USD, repaired in `int_transactions_enriched`:
- USD rows carry no `amount_usd` in the source and are filled from the amount;
- the 5 % of non-USD rows that miss it are recomputed from the daily rate (`int_fx_usd`) and flagged (rule R18).

Mexican transactions keep their USD label (R17): their magnitudes are USD-scale, and relabelling them MXN would inflate
them about 17×. ARS is flat at about 350/USD for three years in this synthetic feed, so inflation-sensitive features
are invalid.
{% enddocs %}

{% docs col_next_best_action %}
Rule-based next action, the first rule that applies:
1. `FRAUD_REVIEW_AND_BLOCK`: fraud confirmed in the last 365 days and the card is not blocked;
2. `REISSUE_CARD`: active but expired (R22), or any expired-card decline in 30 days;
3. `PROACTIVE_RENEWAL`: expires within 45 days;
4. `VERIFY_CARD_DATA`: 3 or more invalid-card declines in 30 days;
5. `REVIEW_RISK_BLOCK`: 3 or more do-not-honor declines in 30 days;
6. `EXPLAIN_LIMIT_OR_OFFER_INCREASE_REVIEW`: utilisation of 95 % or more, or 3 or more insufficient-funds
   declines in 30 days;
7. `UNBLOCK_AFTER_STRONG_AUTH`: the card is blocked;
8. `NONE`.

The copilot explains the action; it never invents one. Fraud, limits and unblocking are decided by a person.
{% enddocs %}

{% docs col_card_open_cases %}
Open complaints whose `affected_product_id` is this card. **Not reliable:** that key never points to the complainant's own product (rule R25: 0 of 43,345 complaints that carry it), so the count describes other customers' cases. Do not show it to the card holder.
{% enddocs %}

{% docs col_link_confidence %}
`high` (product and amount match), `medium` (amount), `low` (product) or `none`. In this data only 34 links are `medium` and the rest `none`: the product never matches, because the complaint's product key belongs to another customer (rule R25).
{% enddocs %}

{% docs col_linked_transaction_id %}
Best candidate for the disputed transaction: the customer's transactions in the 60 days before the claim, scored by product match, amount within 1 % and recency. Set for 6,062 of 26,351 disputes; read it with `link_confidence`.
{% enddocs %}

{% docs col_score_reason %}
Cut-off reason when the score is below a cut-off (`R08_SCORE_BELOW_CARD_CUTOFF`, `R09_SCORE_BELOW_LOAN_CUTOFF`); NULL otherwise. These codes belong to the illustrative credit policy, not to the data-quality rule catalog.
{% enddocs %}
