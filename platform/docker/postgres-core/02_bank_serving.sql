-- bank_serving: low-latency operational store.
--   serving.*          tables published from the lakehouse (contracts in platform/dbt/models/serving)
--   online_features.*  streaming feature state (Flink JDBC upserts, scorer reads)
--   decisions.*        append-only fraud decision log (written by the scorer, never updated)
\connect bank_serving

SET ROLE publisher;
CREATE SCHEMA serving;
CREATE SCHEMA online_features;
CREATE SCHEMA decisions;

-- Publication registry: which lakehouse run produced each serving table (lineage join key).
CREATE TABLE serving.publication_log (
    publication_id   bigserial PRIMARY KEY,
    table_name       text        NOT NULL,
    dbt_invocation   text        NOT NULL,
    lineage_run_id   text        NOT NULL,
    row_count        bigint      NOT NULL,
    content_digest   text        NOT NULL,
    as_of_ts         timestamptz,
    published_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE online_features.customer_state (
    customer_id            text PRIMARY KEY,
    hist_tx_count          bigint,
    hist_sum_log_amount    double precision,
    hist_sumsq_log_amount  double precision,
    hist_max_amount_usd    double precision,
    hist_sum_hour          double precision,
    seen_merchants         jsonb,
    seen_countries         jsonb,
    seen_channels          jsonb,
    last_tx_ts             timestamptz,
    last_lat               double precision,
    last_lon               double precision,
    updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE online_features.tx_window_features (       -- Flink JDBC sink (upsert by transaction_id)
    transaction_id   text PRIMARY KEY,
    customer_id      text NOT NULL,
    anchor_ts        timestamptz NOT NULL,
    tx_count_1h      bigint,
    tx_count_24h     bigint,
    tx_count_7d      bigint,
    amount_usd_24h   double precision,
    declines_24h     bigint,
    computed_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE decisions.fraud_decision_log (
    decision_id      bigserial PRIMARY KEY,
    transaction_id   text        NOT NULL,
    customer_id      text        NOT NULL,
    event_ts         timestamptz NOT NULL,
    decided_at       timestamptz NOT NULL DEFAULT now(),
    decision         text        NOT NULL CHECK (decision IN ('APPROVE', 'STEP_UP', 'DECLINE')),
    risk_score       double precision NOT NULL,
    reason_codes     text[]      NOT NULL,
    model_uri        text        NOT NULL,          -- e.g. models:/fraud_ensemble/3 (resolved alias)
    model_version    text        NOT NULL,
    feature_snapshot jsonb       NOT NULL,          -- exact inputs used (replayable decision)
    latency_ms       double precision,
    lineage_run_id   text
);
CREATE INDEX ON decisions.fraud_decision_log (customer_id, event_ts);

-- Append-only enforcement: no UPDATE / DELETE / TRUNCATE, even for the owner.
CREATE FUNCTION decisions.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'decisions.% is append-only (% blocked)', TG_TABLE_NAME, TG_OP;
END $$;
CREATE TRIGGER fraud_decision_log_append_only BEFORE UPDATE OR DELETE ON decisions.fraud_decision_log
  FOR EACH ROW EXECUTE FUNCTION decisions.forbid_mutation();
CREATE TRIGGER fraud_decision_log_no_truncate BEFORE TRUNCATE ON decisions.fraud_decision_log
  FOR EACH STATEMENT EXECUTE FUNCTION decisions.forbid_mutation();

GRANT USAGE ON SCHEMA serving, online_features, decisions TO app_reader, scorer;
GRANT SELECT ON ALL TABLES IN SCHEMA serving, online_features, decisions TO app_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA serving GRANT SELECT ON TABLES TO app_reader, scorer;
GRANT SELECT, INSERT, UPDATE ON online_features.customer_state, online_features.tx_window_features TO scorer;
GRANT SELECT, INSERT ON decisions.fraud_decision_log TO scorer;
GRANT USAGE ON SEQUENCE decisions.fraud_decision_log_decision_id_seq TO scorer;
RESET ROLE;
