# Appendix · Sources and glossary

[← 12 from evidence to build plan](12_development_path.md) · [index](README.md)

## Internal evidence
- Notebooks 01–11: `eda/notebooks/`, HTML in `eda/reports/notebooks/`.
- Summary tables: `eda/reports/tables/*.csv`. The `warehouse_*` tables come from `eda/scripts/warehouse_validation.py`.
- dbt warehouse: `platform/dbt/` (models, snapshots, tests, seeds). Build with `cd platform/dbt && uv run dbt build`.
- ERD and data dictionary: `docs/dataset/erd.md`, `docs/dataset/*.pdf`.
- Backup summary: `docs/dataset/backup_comparison.md`.

## External sources consulted for this report (checked during writing)
- NVIDIA Kumo-Relational model card: https://huggingface.co/nvidia/Kumo-Relational
- NVIDIA Kumo-Tabular model card: https://huggingface.co/nvidia/Kumo-Tabular
- structured-data-models (code for both): https://github.com/NVIDIA/structured-data-models
- Pix MED 2.0 (BCB Res. 493/2025, mandatory 2 Feb 2026):
  - https://www.pagbrasil.com/blog/pix/med-2-0/
  - https://forbes.com.br/forbes-money/2026/02/med-2-0-do-bc-entra-em-vigor-e-permite-bloqueio-de-pix-fraudulento-entenda-regras/
  - https://analitica.auvp.com.br/noticias/banco-central-lanca-med-20-para-combater-fraudes-no-pix-e-aumentar-seguranca-2
- Brazil AI bill PL 2338/2023 status:
  - https://www.barbieriadvogados.com/brazil-ai-act/
  - https://legislacaoemercados.capitalaberto.com.br/?p=19271
- Mexico's new LFPDPPP (2025):
  - https://www.gtlaw.com/en/insights/2025/3/nueva-ley-general-proteccion-de-datos
  - https://truyo.com/lfpdppp-2025-why-businesses-cant-ignore-mexicos-new-rules-for-privacy-and-ai-governance/
- Colombia SFC AI centre of excellence and AI-based LAFT supervision:
  - https://www.superfinanciera.gov.co/publicaciones/10115843/superfinanciera-revoluciona-la-supervision-de-riesgos-de-lavado-de-activos-con-inteligencia-artificial/
  - https://www.superfinanciera.gov.co/publicaciones/10115638/centro-de-excelencia-en-inteligencia-artificial-de-la-sfc-herramientas-para-el-desarrollo-sostenible/

Other instruments named in chapter 02 are cited from general domain knowledge and **must be verified** by counsel
before use: CNBV/CUB provisions, SFC circulars on cyber and cloud, BCRA Com. "A" 7724, Res. CMN 4.893/2021,
Res. Conjunta 6/2023, Circular BCB 3.978/2020, Ley 1266/2008, Ley 25.326, LGPD articles, PCI DSS v4.0.1, BCBS 239,
SR 11-7, PRA SS1/23, ISO/IEC 42001, NIST AI RMF, OWASP LLM Top 10, MITRE ATLAS.

## Glossary
| term | meaning |
|---|---|
| PIT (point-in-time) | a feature computed only from information available at the anchor time |
| SCD2 | slowly changing dimension type 2: a new row per version with validity interval |
| bitemporal | two time axes: when a fact was true (valid time) and when it was recorded (system time) |
| ASOF join | join each row to the latest matching row at or before its timestamp |
| C2ST | classifier two-sample test: a classifier's AUC at telling two samples apart (0.5 = indistinguishable) |
| AP | average precision (area under the precision-recall curve); the right metric for rare events |
| ICL | in-context learning: the model predicts from labelled examples given at inference, without training |
| TGN | temporal graph network: a GNN with memory over a timestamped interaction stream |
| HGT / R-GCN | heterogeneous graph transformer / relational graph convolutional network |
| GraphRAG | retrieval-augmented generation over a knowledge graph plus community summaries |
| MED 2.0 | Pix special return mechanism, version 2 (in-app dispute, chain blocking up to 5 layers) |
| NBA | next best action |
| DPD | days past due |
| SLO | service level objective (here: maximum violation rate per data-quality rule) |
