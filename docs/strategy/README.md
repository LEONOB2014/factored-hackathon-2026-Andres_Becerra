# LATAM Bank · Data, compliance and AI strategy for the next phases

This report synthesises the dataset evaluation and anomaly-detection study (notebooks 01–11) and turns it into
decisions for the next phases. It covers compliance in Mexico, Colombia, Argentina and Brazil; data, ML, DL, AI and
agent engineering; slowly changing dimensions and record integrity; dbt; deployment; and a set of denormalized tables
with **running SQL** (`platform/dbt/`, dbt-duckdb, 42 models, `dbt build` green).

| chapter | content |
|---|---|
| [01 Evidence synthesis](01_evidence_synthesis.md) | trust profile per table, backup verdict, label leakage, new integrity findings, what is learnable |
| [02 Compliance and regulation](02_compliance_and_regulation.md) | finding → regulation matrix for MX/CO/AR/BR, cross-cutting frameworks, controls C1–C10 |
| [03 Architecture](03_architecture.md) | reference architecture, design patterns mapped to problems, real-time fraud path |
| [04 SCD, adulteration, integrity](04_scd_adulteration_integrity.md) | SCD types per attribute, bitemporal, tamper evidence, integrity taxonomy |
| [05 dbt](05_dbt_recommendations.md) | why dbt, what is built, what to add next, engines, anti-patterns |
| [06 Denormalized tables](06_denormalized_tables.md) | 11 marts with SQL, Flink twin, Pix fund-flow recursion, processing checklist, dataset → path matrix |
| [07 Graphs and foundation models](07_graph_and_foundation_models.md) | heterogeneous graph, GNN/TGN recipes, Kumo-Relational / Kumo-Tabular probes, GraphRAG |
| [08 ML, DL, AI, agents](08_ml_dl_ai_agents.md) | use-case bundles, MLOps, agent guardrails, adversarial robustness, post-training plan |
| [09 Deployment](09_deployment.md) | local vs cloud vs hybrid, topology, residency, classification, cost |
| [10 Roadmap and team](10_roadmap_and_team.md) | phases, KPIs, team, risk register |
| [11 Plan evaluation](11_plan_evaluation.md) | draft v0, scored critique, revised v1, residual weaknesses |
| [12 From evidence to build plan](12_development_path.md) | what the platform and analysis phase proved; marts by business purpose and readiness; the analytics, ML, DL and agent paths; ordered platform work; v0.4.0 exit criteria |
| [13 Data readiness audit](13_data_readiness_audit.md) | every hour-grain model executed and gated; why each is not trainable; what the data collection must change, its owner and acceptance test; the re-evaluation loop |
| [Appendix](appendix_sources.md) | sources and glossary |

> **Update (v0.2.0, after the platform and analysis phase):** the platform was built and judged by three analysis
> series (pipeline walkthrough, per-country rebuilds, the backup run as main). [Chapter 12](12_development_path.md)
> turns their results into the build plan and amends chapters 08 and 10 where the evidence disagrees with them;
> the decisions are ADR-011 to ADR-013 in [`docs/platform/adr`](../platform/adr/README.md).

> **Update (platform phase):** the dbt project now lives in `platform/dbt` with medallion schemas (silver, gold, features, graph, knowledge, privacy, serving, audit); `export_*` models were renamed (`graph_*`, `tgn_*`, `ml_kumo_*`, `kb_entity_*`) and batch marts stop at the stream cutoff (2026-05-17), so mart counts differ slightly from the figures below, which describe the full-history build. See [`docs/platform`](../platform/README.md).

## Executive summary

**1. The data cannot yet support most of what a bank would want to learn from it, and the report says so precisely.**
- Fraud labels are a function of the legacy `fraud_score`. Clean point-in-time behavioural features give an
  out-of-time AUC of **0.504**.
- There is no history for credit scores, consent or delinquency.
- Transcripts are templates.
- Complaints and digital events point to products owned by **other customers** (R25: 66 % of complaints; R26: 7 % of
  events). These foreign keys pass a referential test and fail a semantic one.

The next phase builds the **platform, contracts and controls that make learning possible**, and ships the use cases
that are deterministic over trusted data.

**2. The "backup" is a record-integrity incident, not a backup.**
- 97 % of customers would be replaced on restore.
- 100 % of shared products change owner.
- Credit scores and 70 marketing consents change with no trace.

Distribution tests could not see it (two-sample AUC 0.50); key- and record-level reconciliation could. Both controls now
exist as dbt models: `audit_backup_reconciliation` and `audit_partition_manifest`. SCD2 snapshots with a field-level
change log show what history would have recorded.

**3. Compliance exposure is concrete.**
- **50 % of campaign sends went to customers without (current) marketing consent.**
- 56,664 active cards are past expiry.
- Currency semantics break AML thresholds (income in MXN, accounts in USD).

Brazil adds MED 2.0 (mandatory since 2 Feb 2026), which requires tracing funds through up to five account layers. That
is a graph problem the current schema cannot express, because transfers have no counterparty.

**4. Ten decisions for the next phase.**
1. Treat bronze as evidence: WORM storage, signed partition manifests, reconciliation after every backup, restore drills.
2. SCD2 (bitemporal where regulated) for scores, consent, KYC, limits and DPD, starting now. History cannot be
   back-filled.
3. Data contracts with source teams. The three highest-value schema additions are the **transfer counterparty**, the
   **disputed transaction ID at complaint intake**, and **consent events**.
4. Adopt dbt as the transformation standard. It is already built here with 86 data tests, 2 unit tests, SLO-graded DQ
   rules and point-in-time leakage tests.
5. Ship the **service copilot** first: inquiries, cards and dispute intake over deterministic marts. The LLM explains;
   it never computes amounts or decides.
6. Run fraud as **rules + diverse unsupervised ensemble** until confirmed labels exist (top-3 ensemble AP 0.77 vs 0.69
   for the best single detector on injected anomalies). Add GBDT, then TGN/HGT.
7. Use NVIDIA Kumo-Relational / Kumo-Tabular as **learnability probes and baselines** before investing in per-task
   feature engineering.
8. Post-train an open-weight model for agent behaviour (tool use, refusals, regional Spanish/Portuguese, injection
   robustness) with **RL rewards verifiable against the marts**. Keep knowledge in retrieval, not weights.
9. Hybrid deployment: local dev on synthetic data; in-country real-time and PII; cloud GPUs on tokenised data;
   self-hosted LLMs for anything with customer context.
10. Govern every model, including prompt + tool chains, under SR 11-7-style model risk with fairness gates that use a
    separated protected-attribute table.

## How to reproduce
```bash
uv sync
cd platform/dbt && export DBT_PROFILES_DIR=.
uv run dbt build                        # ~85 s: 133 pass, 4 expected warnings (known data defects)
bash scripts/scd2_demo.sh               # SCD2: what history would have recorded
cd ../../eda && uv run scripts/warehouse_validation.py   # refresh eda/reports/tables/warehouse_*.csv
```
