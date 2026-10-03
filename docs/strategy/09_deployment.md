# 09 · Deployment: local, cloud or hybrid

[← 08 ML, DL, AI and agents](08_ml_dl_ai_agents.md) · [index](README.md) · next: [10 roadmap →](10_roadmap_and_team.md)

## 9.1 Options compared

| criterion | local / on-prem | public cloud | **hybrid (recommended)** |
|---|---|---|---|
| data residency and supervisor comfort | strongest | depends on region and notifications | PII and ledger in-country; tokenised analytics anywhere permitted |
| GPU access for post-training and GNNs | capex, slow to scale | elastic, uses your credits | burst to cloud for training on tokenised or synthetic data |
| streaming and managed services | heavy ops | managed Kafka/Flink/K8s | managed in the chosen region |
| cost profile | fixed | variable; spot for training | fixed core + variable ML |
| developer speed | DuckDB on a laptop is excellent (this repo) | — | local dev on synthetic data, cloud CI and staging |
| concentration and exit risk | low | vendor lock-in | open formats (Iceberg, Parquet, ONNX, safetensors) keep exit cheap |

## 9.2 Recommended topology
1. **Development (local):** DuckDB + dbt-duckdb + notebooks on synthetic data, which is this repository. Real
   customer data never reaches laptops.
2. **Analytics and ML platform (cloud, in-region):** Iceberg on object storage, Spark/Trino or a cloud warehouse, dbt,
   Dagster, MLflow, a feature store. It holds **tokenised** data. The tokenisation vault and keys stay in the bank's
   control (HSM / KMS with customer-managed keys).
3. **Real-time decisioning (in-country, low latency):** Kafka + Flink + online store + model serving, close to the
   card switch and payment rails. Highly available across zones, with a rule fallback.
4. **GPU training (cloud, any permitted region):** LLM post-training, GNN/TGN and foundation-model probes on tokenised
   or synthetic data. Weights return to the in-region registry.
5. **LLM serving (in-region):** self-hosted open-weight models (vLLM / TensorRT-LLM / NIM) for anything that sees
   customer context. External LLM APIs only for non-personal tasks, or under a contract and data-processing agreement
   that satisfies each country's transfer rules.

## 9.3 Country considerations (verify with counsel and the supervisor)
- **Brazil:** Res. CMN 4.893/2021 governs contracting of cloud and data-processing services, including the conditions
  when data sit abroad (agreements between supervisors, prior notice to the BCB). LGPD governs international transfers.
  Pix and MED 2.0 integrations run against BCB infrastructure with strict availability requirements.
- **Mexico:** CNBV rules on outsourcing and information security (authorisation or notice for cloud and third
  parties); the new LFPDPPP for transfers.
- **Colombia:** SFC rules on cybersecurity and cloud computing; Ley 1581 international-transfer rules. Check available
  in-country or nearby cloud regions at design time.
- **Argentina:** BCRA Com. "A" 7724 on technology and information-security risk, including third-party and cloud
  services; Ley 25.326 international-transfer rules.

Hyperscalers have opened regions in Mexico and Brazil; coverage for Colombia and Argentina varies by provider. Choose
per country, and document the residency decision for each data class (PII, transactional, model weights, logs).

## 9.4 Data classification drives placement

| class | examples | where it may live |
|---|---|---|
| R1 restricted PII | names, documents, contact, addresses | in-country, vault and restricted staging only |
| R2 confidential financial | balances, transactions, scores | in-country analytics; tokenised copies for ML |
| R3 pseudonymised | marts, feature tables, graph exports (tokens) | analytics and ML regions permitted by transfer rules |
| R4 synthetic / public | this dataset, regulation texts | anywhere, including laptops and external APIs |
| model artefacts | weights trained on R2/R3 | treated as R3 (memorisation risk); evaluate for extraction |

## 9.5 Cost levers
- Spot or preemptible GPUs for training, reserved or committed capacity for serving.
- Quantised serving (INT4/FP8) cuts GPU memory 2–4×.
- DuckDB/dbt locally removes most dev-cluster spend. This entire warehouse builds in about 85 s on a laptop.
- Cache-heavy agent design: deterministic marts mean most answers are a single indexed lookup plus a short generation.
