# 10 · Roadmap, team and risks

[← 09 deployment](09_deployment.md) · [index](README.md) · next: [11 plan evaluation →](11_plan_evaluation.md)

## 10.0 Revision after the platform and analysis phase (v0.2.0)
The phases below were written before the platform was built. The evidence of
[chapter 12](12_development_path.md) amends them. The rows are kept as written; these amendments take precedence:

- **Phase 0:**
  - add the completeness and dataset-identity controls ([ADR-013](../platform/adr/ADR-013.md));
  - add country-keyed contracts, SLOs, AML lines, deadlines and calendars ([ADR-011](../platform/adr/ADR-011.md));
  - add the six platform fixes of §12.7 (tokens, SCD2 first version, eligibility order, dispute candidates, AML
    peer typology, fraud-label naming).
- **Phase 1:**
  - the first model is **dormancy**, a transparent rate model ([ADR-012](../platform/adr/ADR-012.md));
  - "transparent eligibility and collections scores" ship only after the eligibility build-order fix and the
    unknown-versus-late split;
  - the AML analyst queue pairs the typologies with the isolation forest.
- **Phase 2:**
  - the **escalation-risk model is withdrawn** until real interactions exist (out-of-time AUC 0.49);
  - "AML peer + isolation scoring" starts with reviving the dead peer typology;
  - GBDT fraud keeps its condition: confirmed labels.
- **Phase 3:** graph work starts only when the unblock conditions of §12.5 hold (NULL-preserving tokens, transfer
  counterparties).

## 10.1 Phases

| phase | horizon | outcomes | exit criteria |
|---|---|---|---|
| **0 Foundations** | 0–3 months | data contracts with source teams (counterparty, disputed-transaction ID, consent events, effective dates); bronze on WORM with signed manifests; dbt in CI; SCD2 live on customers/products/consents; DQ SLOs with owners; tokenisation vault; model-risk policy covering LLMs | every A-rule has an owner and an SLO; reconciliation runs after each backup; first restore drill passes |
| **1 Deterministic value** | 3–6 months | B1 service copilot (agent-assist first); card reissue campaign for the active-but-expired cards; consent gate on campaigns; transparent eligibility and collections scores; unsupervised fraud ensemble in shadow | containment / handle-time KPIs; zero sends without consent; ensemble alert precision measured by analysts |
| **2 Learned models** | 6–12 months | GBDT fraud on confirmed labels (champion/challenger vs rules); AML peer + isolation scoring; escalation-risk model; Kumo and RelBench-style probes on real data; first fine-tuned agent model (SFT + DPO) | validated model cards; fairness reports; parity tests green; red-team pass rate above target |
| **3 Network intelligence** | 12–18 months | counterparty graph; TGN / HGT for mule rings; MED 2.0 chain tracing for Brazil; GraphRAG compliance copilot; RL-hardened agents | Brazil go-live readiness; regulator walkthrough of AI governance |
| **4 Scale** | 18 months + | sequence foundation model on payments; cross-country model sharing with per-country calibration; self-service semantic layer | measured business value per bundle |

## 10.2 KPIs per bundle
- **B1:** containment rate, average handle time, first-contact resolution (`repeat_contact_7d`), complaint conversion
  rate, groundedness (share of answers whose numbers match tools, target 100 %).
- **B2:** fraud loss in basis points of volume, alert precision at analyst capacity, time to block, false-decline rate,
  MED 2.0 recovery rate.
- **B3:** approval rate at constant loss, roll rates, cure rate, adverse-action explainability audits passed.
- **B4:** sends without consent (target 0), cost per conversion, incremental conversions vs holdout.
- **B5:** A-rule SLO breaches, mean time to detect a data incident, reconciliation pass rate, lineage coverage.

## 10.3 Team (minimum viable)
- Data platform: 2–3 data engineers, 1 analytics engineer (dbt owner), 1 platform/SRE.
- ML: 2 ML engineers, 1 applied scientist (graphs and time series), 1 MLOps.
- AI: 2 AI engineers (agents, RAG, evals), 1 LLM post-training specialist (part-time or partner).
- Governance: model-risk validator (independent line), data-protection officer liaison, security engineer for AI red
  teaming.
- Domain: fraud/AML analyst, credit risk analyst, contact-centre lead (they label, review and own KPIs).

## 10.4 Risk register

| risk | likelihood | impact | mitigation |
|---|---|---|---|
| Real data has the same semantic-integrity breaks as the synthetic data | medium | high | contracts + quarantine; R25/R26-style tests from day one |
| Labels remain unreliable (fraud = legacy score) | high | high | label programme with chargebacks and analyst outcomes; unsupervised first |
| LLM states a wrong amount or decision to a customer | medium | high | tool grounding, numeric verification, deterministic decisions, HITL for writes |
| Prompt injection through customer text | high | high | sanitisation, guard models, least-privilege tools, red teaming |
| Regulatory change (Brazil AI bill, LFPDPPP rules) | high | medium | policy-as-code; regulation GraphRAG with change alerts |
| Vendor lock-in | medium | medium | open formats, engine-neutral SQL, self-hosted open-weight models |
| Fairness failures via proxies (accent, city) | medium | high | separated fairness table, disparate-impact gates per release |
| Backup and restore integrity (the original finding) | proven | high | C1–C3 controls; quarterly restore drills with reconciliation |
