-- knowledge: governed knowledge base for RAG / GraphRAG (pgvector).
-- Versions are append-only; serving visibility is a view over status + effective window, so draft,
-- superseded, retired or expired content can never be retrieved even if its rows still exist.
\connect knowledge
CREATE EXTENSION IF NOT EXISTS vector;

SET ROLE publisher;
CREATE SCHEMA kb;

CREATE TABLE kb.document_version (
    doc_id          text        NOT NULL,
    version         text        NOT NULL,
    status          text        NOT NULL CHECK (status IN ('draft', 'in_review', 'approved', 'superseded', 'retired')),
    title           text        NOT NULL,
    country         text        NOT NULL,
    language        text        NOT NULL,
    classification  text        NOT NULL CHECK (classification IN ('public', 'internal')),
    owner           text        NOT NULL,
    approver        text,
    effective_from  date        NOT NULL,
    effective_to    date,
    supersedes      text,
    source          text        NOT NULL,          -- 'knowledge_repo' | 'warehouse'
    source_url      text,
    content_hash    text        NOT NULL,
    lineage_run_id  text        NOT NULL,
    registered_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, version)
);

-- Lifecycle events are appended, never edited: the status of a version is its latest event.
CREATE TABLE kb.document_status_event (
    event_id        bigserial   PRIMARY KEY,
    doc_id          text        NOT NULL,
    version         text        NOT NULL,
    status          text        NOT NULL,
    reason          text        NOT NULL,
    lineage_run_id  text        NOT NULL,
    event_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (doc_id, version) REFERENCES kb.document_version (doc_id, version)
);

CREATE TABLE kb.chunk (
    chunk_id        text        PRIMARY KEY,       -- sha256(doc_id|version|ordinal)
    doc_id          text        NOT NULL,
    version         text        NOT NULL,
    ordinal         int         NOT NULL,
    heading         text,
    content         text        NOT NULL,
    content_hash    text        NOT NULL,
    embedding       vector(384) NOT NULL,
    embedding_model text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (doc_id, version) REFERENCES kb.document_version (doc_id, version)
);
CREATE INDEX chunk_embedding_hnsw ON kb.chunk USING hnsw (embedding vector_cosine_ops);

CREATE VIEW kb.current_status AS
SELECT DISTINCT ON (doc_id, version) doc_id, version, status, reason, event_at
FROM kb.document_status_event
ORDER BY doc_id, version, event_id DESC;

-- The ONLY relation retrieval may read. Governance rules: platform/policies/kb_governance.yaml.
CREATE VIEW kb.active_chunk AS
SELECT c.*, d.title, d.country, d.language, d.classification, d.effective_from, d.effective_to, d.source
FROM kb.chunk c
JOIN kb.document_version d USING (doc_id, version)
JOIN kb.current_status s USING (doc_id, version)
WHERE s.status = 'approved'
  AND d.effective_from <= current_date
  AND (d.effective_to IS NULL OR current_date < d.effective_to);

-- Point-in-time evidence: which versions were active after each kb_sync run ("what did the KB know at T").
CREATE TABLE kb.active_set_snapshot (
    snapshot_id     bigserial   PRIMARY KEY,
    lineage_run_id  text        NOT NULL,
    taken_at        timestamptz NOT NULL DEFAULT now(),
    active_versions jsonb       NOT NULL,          -- [{doc_id, version, content_hash}]
    digest          text        NOT NULL
);

CREATE FUNCTION kb.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'kb.% is append-only (% blocked)', TG_TABLE_NAME, TG_OP; END $$;
CREATE TRIGGER doc_version_append_only BEFORE UPDATE OR DELETE ON kb.document_version
  FOR EACH ROW EXECUTE FUNCTION kb.forbid_mutation();
CREATE TRIGGER status_event_append_only BEFORE UPDATE OR DELETE ON kb.document_status_event
  FOR EACH ROW EXECUTE FUNCTION kb.forbid_mutation();
CREATE TRIGGER snapshot_append_only BEFORE UPDATE OR DELETE ON kb.active_set_snapshot
  FOR EACH ROW EXECUTE FUNCTION kb.forbid_mutation();
-- kb.chunk rows of pruned versions are deleted from the index (content stays reconstructable from the
-- immutable document_version.content_hash + the knowledge repo at that commit); deletes are logged.

GRANT USAGE ON SCHEMA kb TO app_reader;
GRANT SELECT ON kb.active_chunk TO app_reader;     -- retrieval sees ONLY the active view
RESET ROLE;
