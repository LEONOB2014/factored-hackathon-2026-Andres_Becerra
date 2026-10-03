-- Online fraud features (Flink SQL). Same definitions as dbt macro fraud_features() for the window
-- features, so the stream_demo parity check can compare them row by row with features.feat_fraud_stream_parity.
--   source : Kafka topic tx.raw (enriched authorization events, JSON), event time = transaction_ts_utc
--   sinks  : Kafka topic tx.features (scorer input) + Postgres online_features.tx_window_features (upsert)
-- Flink evaluates one OVER frame per SELECT, so each window is its own view; the three views are joined on
-- transaction_id (bounded state via table.exec.state.ttl). "minus the current row" == EXCLUDE CURRENT ROW.
-- Each window partitions by CONCAT(customer_id, '|<window>'): identical grouping, but structurally distinct, because
-- the planner merged windows sharing PARTITION BY/ORDER BY and silently compiled the 7-day frame as 24 h (caught by
-- the stream/batch parity check; verified with EXPLAIN: 3 distinct RANGE frames after the change).
SET 'pipeline.name' = 'fraud-online-features';
SET 'table.exec.state.ttl' = '8 d';
SET 'execution.checkpointing.interval' = '30 s';

CREATE TABLE tx_raw (
    transaction_id          STRING,
    customer_id             STRING,
    product_id              STRING,
    transaction_ts_utc      TIMESTAMP(3),
    amount_usd              DOUBLE,
    transaction_type        STRING,
    channel                 STRING,
    transaction_category    STRING,
    merchant_name           STRING,
    transaction_country_code STRING,
    customer_country_code   STRING,
    transaction_status      STRING,
    local_hour              INT,
    is_weekend              BOOLEAN,
    product_family          STRING,
    latitude                DOUBLE,
    longitude               DOUBLE,
    is_warmup               BOOLEAN,
    WATERMARK FOR transaction_ts_utc AS transaction_ts_utc - INTERVAL '5' SECOND
) WITH (
    'connector' = 'kafka',
    'topic' = 'tx.raw',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'properties.group.id' = 'flink-fraud-features',
    'scan.startup.mode' = 'earliest-offset',
    'format' = 'json',
    'json.timestamp-format.standard' = 'ISO-8601',
    'json.ignore-parse-errors' = 'false'
);

CREATE TABLE tx_features (
    transaction_id   STRING,
    customer_id      STRING,
    anchor_ts        TIMESTAMP(3),
    amount_usd       DOUBLE,
    transaction_type STRING,
    channel          STRING,
    transaction_category STRING,
    merchant_name    STRING,
    transaction_country_code STRING,
    customer_country_code STRING,
    transaction_status STRING,
    local_hour       INT,
    is_weekend       BOOLEAN,
    product_family   STRING,
    latitude         DOUBLE,
    longitude        DOUBLE,
    is_warmup        BOOLEAN,
    tx_count_1h      BIGINT,
    tx_count_24h     BIGINT,
    tx_count_7d      BIGINT,
    amount_usd_24h   DOUBLE,
    declines_24h     BIGINT,
    PRIMARY KEY (transaction_id) NOT ENFORCED
) WITH (
    'connector' = 'upsert-kafka',
    'topic' = 'tx.features',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'key.format' = 'json',
    'value.format' = 'json',
    'value.json.timestamp-format.standard' = 'ISO-8601'
);

CREATE TABLE tx_window_features_pg (
    transaction_id   STRING,
    customer_id      STRING,
    anchor_ts        TIMESTAMP(3),
    tx_count_1h      BIGINT,
    tx_count_24h     BIGINT,
    tx_count_7d      BIGINT,
    amount_usd_24h   DOUBLE,
    declines_24h     BIGINT,
    PRIMARY KEY (transaction_id) NOT ENFORCED
) WITH (
    'connector' = 'jdbc',
    'url' = 'jdbc:postgresql://pg-core:5432/bank_serving',
    'table-name' = 'online_features.tx_window_features',
    'username' = 'scorer',
    'password' = '${SCORER_DB_PASSWORD}',
    'sink.buffer-flush.max-rows' = '500',
    'sink.buffer-flush.interval' = '1 s'
);

CREATE TEMPORARY VIEW w1h AS
SELECT transaction_id,
       COUNT(*) OVER w - 1 AS tx_count_1h
FROM tx_raw
WINDOW w AS (PARTITION BY CONCAT(customer_id, '|1h') ORDER BY transaction_ts_utc
             RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW);

CREATE TEMPORARY VIEW w24h AS
SELECT transaction_id,
       COUNT(*) OVER w - 1                                                   AS tx_count_24h,
       SUM(amount_usd) OVER w - amount_usd                                   AS amount_usd_24h,
       SUM(CASE WHEN transaction_status = 'Declined' THEN 1 ELSE 0 END) OVER w
         - CASE WHEN transaction_status = 'Declined' THEN 1 ELSE 0 END       AS declines_24h
FROM tx_raw
WINDOW w AS (PARTITION BY CONCAT(customer_id, '|24h') ORDER BY transaction_ts_utc
             RANGE BETWEEN INTERVAL '24' HOUR PRECEDING AND CURRENT ROW);

CREATE TEMPORARY VIEW w7d AS
SELECT transaction_id,
       COUNT(*) OVER w - 1 AS tx_count_7d
FROM tx_raw
WINDOW w AS (PARTITION BY CONCAT(customer_id, '|7d') ORDER BY transaction_ts_utc
             RANGE BETWEEN INTERVAL '7' DAY PRECEDING AND CURRENT ROW);

CREATE TEMPORARY VIEW features AS
SELECT r.transaction_id, r.customer_id, r.transaction_ts_utc AS anchor_ts, r.amount_usd, r.transaction_type,
       r.channel, r.transaction_category, r.merchant_name, r.transaction_country_code, r.customer_country_code,
       r.transaction_status, r.local_hour, r.is_weekend, r.product_family, r.latitude, r.longitude, r.is_warmup,
       a.tx_count_1h, b.tx_count_24h, c.tx_count_7d, b.amount_usd_24h, b.declines_24h
FROM tx_raw r
JOIN w1h a ON a.transaction_id = r.transaction_id
JOIN w24h b ON b.transaction_id = r.transaction_id
JOIN w7d c ON c.transaction_id = r.transaction_id;

EXECUTE STATEMENT SET
BEGIN
  INSERT INTO tx_features SELECT * FROM features;
  INSERT INTO tx_window_features_pg
  SELECT transaction_id, customer_id, anchor_ts, tx_count_1h, tx_count_24h, tx_count_7d, amount_usd_24h, declines_24h
  FROM features WHERE NOT is_warmup;
END;
