# 11 · Evaluating the plan: draft, critique, revision

[← 10 roadmap](10_roadmap_and_team.md) · [index](README.md) · next: [sources →](appendix_sources.md)

The brief asked for a first draft of the plan, then an evaluation of its coherence, value, relevance, innovation,
reliability, safety, production readiness, auditability, interpretability and further dimensions. This chapter does
that openly, including what changed between the draft and the plan in this report.

## 11.1 Draft v0 (the plan one would write before looking at the data)
1. Train a supervised fraud model on `is_fraud` with GBDT + SHAP and deploy it in real time.
2. Train a credit-risk model on the customer table (score, income, DPD).
3. Fine-tune an LLM on transcripts and complaints; deploy a customer chatbot that answers account questions.
4. Build a GNN for fraud on the full schema graph, including complaint → product and event → product edges.
5. Restore missing history from `data_backup_20260831/` and use it as a second time period.
6. Wide "one big table" per customer for every use case.
7. Cloud-only deployment with a managed LLM API.

## 11.2 Critique of v0 against the evidence

| v0 item | what the evidence says | verdict |
|---|---|---|
| 1 supervised fraud | `is_fraud` is a function of `fraud_score`; PIT behavioural features give AUC 0.504 | would ship a model that learns nothing, or one that copies the legacy score |
| 2 credit model | no performance label; no history; `*_current` attributes leak the future | not learnable; any back-test would be optimistic |
| 3 LLM on transcripts | 100 % of transcripts are templates with placeholders; one intent value | the model would learn placeholders; also a privacy and injection risk on real data |
| 4 full-schema GNN | complaint → product and event → product FKs point to other customers (R25/R26) | the GNN would learn noise through broken edges |
| 5 backup as history | it is an independent realisation; shared keys are re-keyed, re-dated and re-attributed | it would fabricate history; also a record-integrity incident |
| 6 one big table | different grains (transaction, product, customer-month); PIT vs current semantics | leakage and fan-out errors; impossible to govern |
| 7 cloud-only with external API | residency and transfer rules in 4 countries; PII in context | regulatory exposure; no control over model changes |

## 11.3 Scoring (1 = poor, 5 = strong)
Scores are judgement, anchored to the evidence in chapters 01–10.

| dimension | v0 | v1 (this report) | what moved it |
|---|---:|---:|---|
| coherence (parts reinforce each other) | 2 | 5 | bundles share marts and controls (ch. 08 §8.1) |
| business value | 3 | 4 | fastest value is deterministic: 56,731 card reissues, inquiry deflection, consent fix |
| relevance to the data | 1 | 5 | every recommendation traces to a finding and a table |
| innovation | 3 | 4 | Kumo ICL as learnability probe, RL with rewards verifiable from marts, GraphRAG over regulation + lineage, detector CI |
| reliability | 1 | 4 | PIT tests, unit tests (caught two real null bugs), SLOs, parity tests |
| safety and security | 2 | 4 | intents + policy engine, injection defences, least-privilege tools |
| production readiness | 2 | 3 | the warehouse runs; streaming, vault and serving are designs, not code |
| auditability | 1 | 5 | row-level findings, manifests, reconciliation, SCD2 change log, event-sourced agent logs |
| interpretability | 3 | 4 | reason codes and rule-based NBA first; SHAP / GNNExplainer later |
| regulatory exposure (inverse) | 1 | 4 | consent gate, residency topology, model-risk tiering, separated fairness attributes |
| data readiness honesty | 1 | 5 | explicit "cannot learn yet" list with the data requests that unblock each item |
| fairness | 2 | 4 | proxies (accent) excluded and monitored |
| adversarial robustness | 1 | 4 | domain-constrained attack tests, ensembles, graph features, red-team loop |
| cost efficiency | 2 | 4 | local dev, spot training, quantised serving, deterministic caching |
| time to value | 3 | 4 | Phase 1 ships without new labels |
| reversibility / exit | 2 | 4 | open formats, engine-neutral SQL, self-hosted models |

## 11.4 Residual weaknesses of v1 (and how to close them)
1. **Production readiness is 3, not 5.** Streaming, feature store, vault and agent runtime are architecture, not code.
   Close with Phase 0–1 deliverables and a pilot in one country.
2. **Eligibility thresholds are illustrative.** On this data only 0.44 % qualify. Thresholds must come from credit
   policy, with sensitivity analysis.
3. **Regulatory mapping needs counsel.** Several items in ch. 02 are themes, not verified article-level obligations.
4. **Kumo results are predicted, not run.** The probe needs a CUDA GPU (Kumo-Relational). Running both probes is a
   one-day task in Phase 2, or as soon as a GPU is available.
5. **Graph value is unproven here.** 24 merchants and 237 shared IPs make a thin graph. The case for GNNs rests on
   counterparty data arriving.
6. **The dispute linkage is weak (34 of 27,133).** It is a data-capture problem; the fix is upstream.

## 11.5 Self-consistency checks performed while writing
- Every number in chapters 01, 05, 06 and 07 was taken from `eda/reports/tables/*.csv` or from queries on the built
  warehouse.
- The warehouse builds end to end: 133 pass, 4 expected warnings, 0 errors.
- The PIT tests and the label-leak guard are part of `dbt build`, not a one-off check.
- An earlier rule definition (R08/R09 in notebook 07) over-counted, because credit cards and loans legitimately carry
  limits and DPD. It was corrected to v2 in the warehouse, where both rules now find 0 violations.
