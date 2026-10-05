# Architecture decision records

| ADR | decision |
|---|---|
| [ADR-001](ADR-001.md) | Lakehouse with medallion zones and a Kimball core |
| [ADR-002](ADR-002.md) | Airflow 3 with Astronomer Cosmos for orchestration |
| [ADR-003](ADR-003.md) | Postgres + pgvector as the operational and vector store |
| [ADR-004](ADR-004.md) | Neo4j for GraphRAG and the entity graph |
| [ADR-005](ADR-005.md) | Flink for streaming features |
| [ADR-006](ADR-006.md) | DuckDB for development, BigQuery as the analytics layer |
| [ADR-007](ADR-007.md) | Residency strategy per country |
| [ADR-008](ADR-008.md) | Crypto-shredding to reconcile immutability and erasure |
| [ADR-009](ADR-009.md) | Scope of differential privacy |
| [ADR-010](ADR-010.md) | Federated graph learning across countries |
| [ADR-011](ADR-011.md) | Country-keyed configuration, one code base |
| [ADR-012](ADR-012.md) | Evidence-gated model portfolio |
| [ADR-013](ADR-013.md) | Data completeness and dataset identity controls |
| [ADR-014](ADR-014.md) | Timestamps carry an explicit clock |
| [ADR-015](ADR-015.md) | The exploratory record and what it decided |
| [ADR-016](ADR-016.md) | Segment by country at bronze, before silver |
| [ADR-017](ADR-017.md) | A multi-grain star on top of gold |
| [ADR-018](ADR-018.md) | Model readiness gates and the data-collection audit |
| [ADR-019](ADR-019.md) | The readiness control plane is the product |
| [ADR-020](ADR-020.md) | Lateral pipeline expansion: scope × grain |
| [ADR-021](ADR-021.md) | Serve the copilot from the residency region of its customers |
