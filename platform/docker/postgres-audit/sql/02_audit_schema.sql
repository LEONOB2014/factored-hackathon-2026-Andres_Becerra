-- Audit store. Every table here is append-only and hash-chained INSIDE the database: a BEFORE INSERT
-- trigger takes an advisory lock, reads the previous row hash of the same chain and computes
--   row_hash = sha256(prev_hash || chain || seq || canonical_json(payload columns))
-- so a client can neither choose its own hash nor rewrite history. The audit_anchor DAG periodically
-- copies the head of every chain to object-locked storage (MinIO / GCS bucket lock) and re-verifies.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
SET ROLE audit_owner;

CREATE SCHEMA ledger;
CREATE SCHEMA genai;
CREATE SCHEMA compliance;
CREATE SCHEMA privacy;
CREATE SCHEMA dsar;
CREATE SCHEMA keys;

-- --------------------------------------------------------------------------------------------- chain
CREATE TABLE ledger.chain_head (
    chain       text PRIMARY KEY,
    seq         bigint NOT NULL,
    row_hash    text   NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION ledger.chain_insert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_chain text := TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME;
  v_prev  text;
  v_seq   bigint;
  v_body  jsonb;
BEGIN
  -- canonical JSON must not depend on the session: timestamps are rendered in UTC
  PERFORM set_config('timezone', 'UTC', true);
  PERFORM pg_advisory_xact_lock(hashtext(v_chain));
  SELECT seq, row_hash INTO v_seq, v_prev FROM ledger.chain_head WHERE chain = v_chain;
  v_seq  := coalesce(v_seq, 0) + 1;
  v_prev := coalesce(v_prev, repeat('0', 64));
  NEW.chain_seq := v_seq;
  NEW.recorded_at := clock_timestamp();
  NEW.prev_hash := v_prev;
  v_body := to_jsonb(NEW) - 'row_hash' - 'prev_hash';
  NEW.row_hash := encode(digest(v_prev || '|' || v_chain || '|' || v_seq || '|' || v_body::text, 'sha256'), 'hex');
  INSERT INTO ledger.chain_head (chain, seq, row_hash) VALUES (v_chain, v_seq, NEW.row_hash)
  ON CONFLICT (chain) DO UPDATE SET seq = EXCLUDED.seq, row_hash = EXCLUDED.row_hash, updated_at = now();
  RETURN NEW;
END $$;

CREATE FUNCTION ledger.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit table %.% is append-only (% blocked)', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP;
END $$;

-- Recompute a chain from scratch and return the rows whose stored hash or link does not match.
CREATE FUNCTION ledger.verify_chain(tbl regclass)
RETURNS TABLE (chain_seq bigint, problem text) LANGUAGE plpgsql AS $$
DECLARE
  r record; v_prev text := repeat('0', 64); v_expected text; v_seq bigint := 0;
  v_chain text := (SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = tbl);
BEGIN
  PERFORM set_config('timezone', 'UTC', true);
  FOR r IN EXECUTE format('SELECT to_jsonb(t) AS j FROM %s t ORDER BY chain_seq', tbl) LOOP
    v_seq := v_seq + 1;
    IF (r.j->>'chain_seq')::bigint <> v_seq THEN
      chain_seq := (r.j->>'chain_seq')::bigint; problem := 'sequence gap (row inserted or deleted)'; RETURN NEXT;
    END IF;
    IF r.j->>'prev_hash' <> v_prev THEN
      chain_seq := v_seq; problem := 'broken link to previous row'; RETURN NEXT;
    END IF;
    v_expected := encode(digest(v_prev || '|' || v_chain || '|' || (r.j->>'chain_seq') || '|' ||
                         ((r.j - 'row_hash') - 'prev_hash')::text, 'sha256'), 'hex');
    IF r.j->>'row_hash' <> v_expected THEN
      chain_seq := v_seq; problem := 'content hash mismatch (row edited)'; RETURN NEXT;
    END IF;
    v_prev := r.j->>'row_hash';
  END LOOP;
END $$;

-- Helper: make a table chained + immutable. Columns chain_seq, recorded_at, prev_hash, row_hash are added.
CREATE FUNCTION ledger.make_immutable(tbl regclass) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE format('ALTER TABLE %s ADD COLUMN chain_seq bigint, ADD COLUMN recorded_at timestamptz,
                  ADD COLUMN prev_hash text, ADD COLUMN row_hash text', tbl);
  EXECUTE format('CREATE TRIGGER chain_insert BEFORE INSERT ON %s FOR EACH ROW EXECUTE FUNCTION ledger.chain_insert()', tbl);
  EXECUTE format('CREATE TRIGGER no_update_delete BEFORE UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION ledger.forbid_mutation()', tbl);
  EXECUTE format('CREATE TRIGGER no_truncate BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION ledger.forbid_mutation()', tbl);
END $$;

-- ------------------------------------------------------------------------------- platform event ledger
CREATE TABLE ledger.event (
    event_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_time      timestamptz NOT NULL,
    actor           text        NOT NULL,           -- service account / user
    event_type      text        NOT NULL,           -- e.g. bronze.partition_written, dbt.run_finished
    subject_ref     text,                           -- table, model, document, decision id
    lineage_run_id  text,                           -- joins OpenLineage (Marquez) and MLflow
    payload         jsonb       NOT NULL,           -- no raw PII: tokens or encrypted fields only
    pii_key_id      text                            -- keys.subject_key used to encrypt payload fields
);
SELECT ledger.make_immutable('ledger.event');

-- Anchors written to WORM storage (copy of chain heads at a point in time).
CREATE TABLE ledger.anchor (
    anchor_id       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    anchored_at     timestamptz NOT NULL,
    heads           jsonb       NOT NULL,           -- {chain: {seq, row_hash}}
    merkle_root     text        NOT NULL,
    object_uri      text        NOT NULL,           -- s3://audit-anchors/... (object-locked)
    verified_ok     boolean     NOT NULL,
    problems        jsonb
);
SELECT ledger.make_immutable('ledger.anchor');

-- --------------------------------------------------------------------------------------- GenAI audit
CREATE TABLE genai.model_version (
    model_version_id text       PRIMARY KEY,         -- provider/model@revision
    provider        text        NOT NULL,
    model_name      text        NOT NULL,
    revision        text        NOT NULL,           -- weights commit / API model snapshot id
    weights_sha256  text,
    quantization    text,
    serving_runtime text,
    approved_by     text,
    approval_ref    text,
    registered_by   text        NOT NULL
);
SELECT ledger.make_immutable('genai.model_version');

CREATE TABLE genai.prompt_version (
    prompt_version_id text      PRIMARY KEY,         -- name@semver
    prompt_name     text        NOT NULL,
    system_instructions text    NOT NULL,           -- exact text, never a reference
    template        text        NOT NULL,
    content_sha256  text        NOT NULL,
    effective_from  timestamptz NOT NULL,
    effective_to    timestamptz,
    approved_by     text,
    registered_by   text        NOT NULL
);
SELECT ledger.make_immutable('genai.prompt_version');

CREATE TABLE genai.request (
    request_id      uuid        PRIMARY KEY,
    trace_id        text,                           -- MLflow trace id
    caller          text        NOT NULL,
    purpose         text        NOT NULL,           -- purpose limitation (e.g. card_support)
    country         text,
    channel         text,
    subject_token   text,                           -- customer token, never raw identifiers
    received_at     timestamptz NOT NULL
);
SELECT ledger.make_immutable('genai.request');

CREATE TABLE genai.retrieval (
    request_id      uuid        NOT NULL REFERENCES genai.request,
    rank            int         NOT NULL,
    source          text        NOT NULL,           -- pgvector | neo4j | sql_tool
    doc_id          text,
    doc_version     text,
    chunk_id        text,
    chunk_sha256    text,
    score           double precision,
    kb_snapshot_id  bigint,                         -- knowledge.kb.active_set_snapshot at retrieval time
    PRIMARY KEY (request_id, rank)
);
SELECT ledger.make_immutable('genai.retrieval');

CREATE TABLE genai.generation (
    request_id      uuid        PRIMARY KEY REFERENCES genai.request,
    model_version_id text       NOT NULL REFERENCES genai.model_version,
    prompt_version_id text      NOT NULL REFERENCES genai.prompt_version,
    parameters      jsonb       NOT NULL,           -- temperature, max_tokens, seed, tools
    input_redacted  text        NOT NULL,           -- after pii_guard
    output_redacted text        NOT NULL,
    output_sha256   text        NOT NULL,           -- hash of the exact (unredacted) output shown
    guardrail_verdicts jsonb    NOT NULL,           -- input/output guards, grounding check
    tool_calls      jsonb,
    tokens_in       int,
    tokens_out      int,
    latency_ms      double precision,
    generated_at    timestamptz NOT NULL
);
SELECT ledger.make_immutable('genai.generation');

CREATE TABLE genai.human_override (
    override_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      uuid        NOT NULL REFERENCES genai.request,
    reviewer        text        NOT NULL,
    action          text        NOT NULL CHECK (action IN ('approved', 'edited', 'rejected', 'escalated')),
    original_sha256 text        NOT NULL,
    final_redacted  text,
    final_sha256    text,
    reason          text        NOT NULL,
    overridden_at   timestamptz NOT NULL
);
SELECT ledger.make_immutable('genai.human_override');

CREATE TABLE genai.feedback (
    feedback_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      uuid        NOT NULL REFERENCES genai.request,
    source          text        NOT NULL,
    rating          int,
    comment_redacted text,
    given_at        timestamptz NOT NULL
);
SELECT ledger.make_immutable('genai.feedback');

-- ----------------------------------------------------------------------------- compliance & privacy
CREATE TABLE compliance.trigger_event (
    trigger_event_id uuid       PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_id      text        NOT NULL,           -- platform/policies/regulatory_triggers.yaml
    fired_at        timestamptz NOT NULL,
    deadline_at     timestamptz,
    subject_ref     text,
    evidence        jsonb       NOT NULL,
    action          text        NOT NULL,
    status          text        NOT NULL CHECK (status IN ('open', 'actioned', 'dismissed_with_reason'))
);
SELECT ledger.make_immutable('compliance.trigger_event');

CREATE TABLE privacy.budget_ledger (
    entry_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    release_name    text        NOT NULL,
    dataset         text        NOT NULL,
    epsilon         double precision NOT NULL CHECK (epsilon > 0),
    delta           double precision NOT NULL CHECK (delta >= 0),
    mechanism       text        NOT NULL,
    requested_by    text        NOT NULL,
    approved        boolean     NOT NULL,
    reason          text,
    spent_at        timestamptz NOT NULL
);
SELECT ledger.make_immutable('privacy.budget_ledger');

CREATE TABLE privacy.budget_policy (
    dataset         text        PRIMARY KEY,
    epsilon_total   double precision NOT NULL,
    delta_total     double precision NOT NULL,
    period          text        NOT NULL           -- e.g. calendar_year
);

CREATE VIEW privacy.budget_remaining AS
SELECT p.dataset, p.epsilon_total, p.delta_total,
       p.epsilon_total - coalesce(sum(l.epsilon) FILTER (WHERE l.approved), 0) AS epsilon_remaining,
       p.delta_total   - coalesce(sum(l.delta)   FILTER (WHERE l.approved), 0) AS delta_remaining
FROM privacy.budget_policy p
LEFT JOIN privacy.budget_ledger l USING (dataset)
GROUP BY p.dataset, p.epsilon_total, p.delta_total;

CREATE TABLE dsar.request (
    dsar_id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_token   text        NOT NULL,
    country         text        NOT NULL,
    right_invoked   text        NOT NULL,           -- access | rectification | cancellation/erasure | opposition
    legal_basis     text        NOT NULL,           -- LFPDPPP ARCO, LGPD art. 18, Ley 1581, Ley 25.326
    received_at     timestamptz NOT NULL,
    due_at          timestamptz NOT NULL,
    status          text        NOT NULL,
    legal_hold      boolean     NOT NULL DEFAULT false,
    evidence        jsonb
);
SELECT ledger.make_immutable('dsar.request');

-- Crypto-shredding: per-subject data keys. Destroying a key makes every encrypted payload field of that
-- subject unreadable while the hash chains stay verifiable. Key material is the ONLY mutable thing here,
-- and its destruction is itself recorded in ledger.event. In production keys live in KMS/HSM.
CREATE TABLE keys.subject_key (
    key_id          text        PRIMARY KEY,
    subject_token   text        NOT NULL UNIQUE,
    wrapped_key     bytea,                          -- NULL after shredding
    created_at      timestamptz NOT NULL DEFAULT now(),
    shredded_at     timestamptz
);

RESET ROLE;

GRANT USAGE ON SCHEMA ledger, genai, compliance, privacy, dsar, keys TO audit_writer, audit_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA ledger, genai, compliance, privacy, dsar TO audit_reader, audit_writer;
GRANT INSERT ON ledger.event, ledger.anchor, genai.model_version, genai.prompt_version, genai.request,
                genai.retrieval, genai.generation, genai.human_override, genai.feedback,
                compliance.trigger_event, privacy.budget_ledger, dsar.request TO audit_writer;
GRANT SELECT, INSERT ON privacy.budget_policy TO audit_writer;
GRANT EXECUTE ON FUNCTION ledger.verify_chain(regclass) TO audit_reader, audit_writer;
GRANT SELECT, INSERT ON keys.subject_key TO audit_writer;
GRANT UPDATE (wrapped_key, shredded_at) ON keys.subject_key TO audit_writer;   -- shredding only
