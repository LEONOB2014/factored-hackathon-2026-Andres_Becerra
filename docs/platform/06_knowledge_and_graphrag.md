# 06 · Knowledge base and GraphRAG: no draft or outdated guidance, ever

[← 05 privacy and compliance](05_privacy_and_compliance.md) · [index](README.md) · next: [07 ML and graph learning →](07_ml_and_graph_learning.md)

## 6.1 Document lifecycle

```mermaid
stateDiagram-v2
  [*] --> draft
  draft --> in_review
  in_review --> approved: approver recorded
  in_review --> draft
  approved --> superseded: new version published
  approved --> retired
  approved --> expired: effective_to passed
  note right of approved
    only approved AND inside the effective window
    is indexed and retrievable (kb.active_chunk)
  end note
  superseded --> [*]: pruned from pgvector + Neo4j, history kept
  retired --> [*]: pruned
  expired --> [*]: pruned
```

## 6.2 Sync pipeline (`kb_sync`, hourly)

```mermaid
flowchart LR
  MD[knowledge/*.md<br/>front matter] --> V{validate<br/>required fields · classification ·<br/>PII scan · immutable version}
  V -->|reject| REJ[report + ledger]
  V -->|ok| REG[(kb.document_version<br/>+ status events, append-only)]
  REG --> SERV{approved and<br/>effective today?}
  SERV -->|yes, no chunks yet| CH[chunk by heading] --> EMB[local multilingual E5<br/>384-d, no text leaves] --> PGV[(kb.chunk pgvector HNSW)]
  EMB --> NEO[(Neo4j Document–DocVersion–Chunk–Entity)]
  SERV -->|no, has chunks| PR[prune chunks + Neo4j version inactive]
  PGV & NEO & REG --> REC{reconcile active sets}
  REC -->|equal| SNAP[(kb.active_set_snapshot<br/>digest per run)]
  REC -->|differ| FAIL[run fails]
```

Guarantees (tested in `platform/libs/tests/test_kb_pipeline.py`):
* superseded, draft, retired and expired versions are never in `kb.active_chunk`, the only relation retrieval
  may read (`app_reader` has no access to the base tables);
* a new version prunes the previous one from pgvector and Neo4j while the registry keeps both and the status
  history (`approved → superseded`) as events;
* editing an existing version without bumping it is rejected (versions are content-hashed);
* a document containing personal data is rejected before anything is stored;
* each run snapshots a digest of the active set, so "what did the assistant know on date T" is answerable and
  every GenAI retrieval row references the snapshot id.

## 6.3 Graph model in Neo4j

```mermaid
graph LR
  D((Document)) -- HAS_VERSION --> V((DocVersion<br/>status, active, effective dates, hash))
  V -- SUPERSEDES --> V2((DocVersion previous))
  V -- HAS_CHUNK --> C((Chunk<br/>text, embedding))
  C -- MENTIONS --> E((Entity<br/>Regulator · Regulation · Rule · Control · DbtModel))
  E -- IMPLEMENTED_BY --> M((Entity DbtModel))
```

Entities are extracted deterministically (regulators, regulations, data-quality rules R01–R27, controls C1–C10,
dbt model names from the manifest), so the graph contains no LLM-invented facts. Controls link to the dbt models
that implement them, letting a compliance question traverse regulation → control → model → test. Chunks carry
embeddings with a Neo4j vector index (`chunk_embedding`) for hybrid vector + graph retrieval.

The entity graph from the lakehouse (`graph_load`: customers as tokens, products, merchants, branches, agents,
campaigns, complaints, shared IPs as tokens) lives in the same database under separate labels; customer-level
documents are not placed in the knowledge base (they are confidential, the KB allows public/internal only).
