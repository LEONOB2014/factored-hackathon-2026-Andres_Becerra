# 02 · Compliance and regulatory implications (Mexico, Colombia, Argentina, Brazil)

[← 01 evidence](01_evidence_synthesis.md) · [index](README.md) · next: [03 architecture →](03_architecture.md)

> **Not legal advice.** This chapter maps engineering findings to the regulatory themes they touch and to concrete
> controls. Instrument names were checked against public sources where marked ✓ (see [sources](appendix_sources.md)).
> Every obligation, deadline and threshold must be confirmed with local counsel and compliance before it is coded into
> a control. Regulation in all four countries changed during 2025–2026.

## 2.1 Why the findings are regulatory, not just technical

| finding (rule) | regulatory theme | why an examiner cares |
|---|---|---|
| A "backup" that is not a copy; records replaced, re-keyed, re-dated (ch. 01 §1.3) | record keeping, business continuity, data integrity (BCBS 239 principles 2–3, local IT-risk rules) | a restore would have silently replaced 97 % of customers and re-attributed every product |
| Credit scores changed without trace; `last_updated` not updated (notebook 05, SCD2 demo) | model risk, fair lending, consumer protection, data-subject right to explanation | the bank cannot explain which score drove a past decision |
| 50 % of sends to customers flagged "no marketing" (R21); 70 consent flips untraced | data protection (consent, purpose limitation, opt-out registries) | each send is potentially an individual infringement; no consent history means no defence |
| Complaints pointing to other customers' products (R25) | complaint handling and regulatory complaint reporting | regulator reports would attribute cases to the wrong products and customers |
| 56,664 active cards past expiry (R22) | card scheme rules, operational risk | authorization logic and card status disagree |
| Approved transactions without a response code (R03), missing branch IDs (R10) | transaction reporting, AML monitoring completeness | monitoring rules that key on these fields silently skip rows |
| No MXN, income in MXN but accounts in USD (R17) | AML thresholds, FX reporting, affordability | thresholds in local currency are evaluated on the wrong amounts |
| `fraud_score` defines the fraud label | model validation | a model "validated" on this label validates the legacy score, not fraud |
| Transcripts and complaint text enter LLM context | data protection, banking secrecy, AI security | customer-controlled text is an injection channel and contains personal data |

## 2.2 Country matrix

| theme | Mexico | Colombia | Argentina | Brazil (expansion) |
|---|---|---|---|---|
| **Personal data** | New LFPDPPP in force 21 Mar 2025 ✓ (oversight moved from INAI to the Secretaría Anticorrupción y Buen Gobierno ✓) | Ley 1581/2012 (+ Decreto 1377/2013), SIC as authority | Ley 25.326, AAIP as authority (reform bill pending) | LGPD (Lei 13.709/2018), ANPD; Art. 20 right to review of automated decisions |
| **Credit data** | Ley para Regular las Sociedades de Información Crediticia | Ley 1266/2008 (financial habeas data) and amendments | Ley 25.326 credit-data provisions | Cadastro Positivo (LC 166/2019) |
| **Banking secrecy** | Ley de Instituciones de Crédito (secreto bancario) | reserva bancaria / Estatuto Orgánico | Ley de Entidades Financieras (secreto financiero) | LC 105/2001 |
| **AML/CFT** | Art. 115 LIC general provisions; reports to UIF (relevant, unusual, internal-concern operations) | SARLAFT in the SFC Circular Básica Jurídica; reports to UIAF | Ley 25.246; UIF resolutions for financial entities | Lei 9.613/1998; Circular BCB 3.978/2020; reports to COAF |
| **IT, cyber, cloud** | CNBV general provisions (Circular Única de Bancos) on information security and outsourcing | SFC external circulars on cybersecurity and cloud computing | BCRA Com. "A" 7724 (technology and information-security risk) | Res. CMN 4.893/2021 (cyber policy, cloud, data abroad), Res. BCB 85/2021 for payment institutions |
| **Complaints** | CONDUSEF; specialised user-attention unit (UNE) and its response deadlines | SFC (SmartSupervision), Defensor del Consumidor Financiero, Ley 1328/2009 | BCRA user-protection rules, consumer-protection law | Ouvidoria rules, BCB complaints (RDR), consumidor.gov.br |
| **Fraud and disputes** | Rules on unrecognised charges (cargos no reconocidos) in card regulation | SFC consumer-protection rules on fraud | BCRA user-protection rules | **MED 2.0 for Pix, mandatory from 2 Feb 2026 (Res. BCB 493/2025) ✓**: in-app dispute and chain blocking up to 5 layers; Res. Conjunta 6/2023 on sharing fraud indicators |
| **Open finance** | Ley Fintech (open APIs) | Decreto 1297/2022 | — | Open Finance Brasil |
| **AI governance** | New LFPDPPP addresses automated processing ✓ | CONPES 4144 (national AI policy); SFC AI centre of excellence (CDEIA, 2025) ✓ | no AI statute | PL 2338/2023 passed the Senate (Dec 2024) ✓ and is in a Chamber special committee in 2026 ✓; credit scoring is high-risk in the Senate text |

**Brazil is the hardest market and the most instructive one.** Pix fraud cases rose sharply (the BCB reported
2.2 M fraud cases in 2025 ✓). MED 2.0 obliges institutions to trace and block funds across up to five layers of
accounts ✓. That requirement is natively a **graph problem over counterparty flows**, which this dataset cannot
represent because transfers have no counterparty. Before Brazil, the data model needs beneficiary identifiers, Pix
keys and end-to-end IDs (ch. 06 §6.12).

## 2.3 Cross-cutting frameworks to adopt as internal standards
- **BCBS 239** (risk data aggregation and reporting): accuracy, completeness, timeliness, adaptability. The DQ SLO layer
  (`dq_rule_summary`) and lineage are the evidence.
- **Model risk management.** No LATAM regulator has a direct SR 11-7 equivalent. Adopt **SR 11-7** and **PRA SS1/23**
  as the internal benchmark: model inventory, tiering, independent validation, ongoing monitoring. Treat every LLM
  prompt plus tool chain as a model.
- **ISO/IEC 42001** (AI management system) and **NIST AI RMF** for AI governance. Use the **EU AI Act** as the reference
  taxonomy: credit scoring is high-risk, and Brazil's bill follows a similar approach.
- **PCI DSS v4.0.1** for any card PAN/CVV path. The marts hold product IDs, never PANs. Keep it that way.
- **OWASP Top 10 for LLM Applications** and **MITRE ATLAS** for AI threat modelling.

## 2.4 Controls that follow from the findings

| # | control | implemented here | production form |
|---|---|---|---|
| C1 | Reconcile every copy, replica and backup against the source (keys, record hashes, counts) | `audit_backup_reconciliation`, test `backup_is_faithful` | scheduled after each backup; restore drill with verification; alert on any non-zero row |
| C2 | Tamper evidence on bronze data | `audit_partition_manifest` (per-partition MD5 + chain digest) | manifest signed with KMS, written to WORM (object lock, compliance mode); Iceberg snapshots retained per the retention policy |
| C3 | History of every regulated attribute (score, consent, KYC, limits, status) | SCD2 snapshots + `audit_scd2_change_log` | bitemporal tables; change reason and actor captured at source (outbox events) |
| C4 | Consent gate before any send | rule R21, `mart_campaign_compliance_uplift.sent_without_current_consent` | consent service checked at send time; consent history as SCD2; suppression lists per channel and country |
| C5 | Semantic integrity tests (ownership, not just existence) | R25, R26 in `dq_integrity_findings` | data contracts with producers; quarantine on breach |
| C6 | Label governance | `assert_no_label_leaking_columns`, `fraud_score` excluded | label definitions versioned; chargeback lag handled; validation independent of the legacy score |
| C7 | Protected attributes separated | `int_customer_fairness_attributes` | access limited to model-risk; disparate-impact reports per model release |
| C8 | Explainable decisions | `mart_credit_eligibility.decline_reasons`, card `next_best_action` | reason codes mapped to approved adverse-action wording per country and language |
| C9 | PII minimisation in analytics and AI | tokens in marts, PII only in restricted staging | tokenisation vault (HSM/KMS-keyed); LLM context built from tokens and masked fields only |
| C10 | DQ SLOs with severity | `dq_rule_slo` seed + `dq_slo_breach_*` tests | SLO breach on an A-rule blocks downstream publication and pages the data owner |

## 2.5 Record retention and the backup question
All four jurisdictions require multi-year retention of transactional and AML records; periods differ by record type and
country. A retention system is only compliant if it can prove three things:
1. **Completeness**: every record in scope is retained.
2. **Integrity**: retained records are unaltered.
3. **Retrievability**: they can be produced on request.

The `data_backup_20260831` folder fails all three. If it was meant as a regulatory archive, the correct response is an
incident: document it, find out who produced it and with what process, and fix the process (C1–C3). If it was a test
fixture, label it as one and move it out of the production namespace.
