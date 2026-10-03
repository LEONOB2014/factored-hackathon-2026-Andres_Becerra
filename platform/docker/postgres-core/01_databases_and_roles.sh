#!/usr/bin/env bash
# pg-core: one Postgres instance, one database per compartment, one login role per workload.
# Least privilege: each workload owns only its database; readers get SELECT only.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-SQL
  CREATE ROLE airflow      LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
  CREATE ROLE mlflow       LOGIN PASSWORD '${MLFLOW_DB_PASSWORD}';
  CREATE ROLE publisher    LOGIN PASSWORD '${PUBLISHER_DB_PASSWORD}';   -- Airflow publish_serving / kb_sync
  CREATE ROLE app_reader   LOGIN PASSWORD '${APP_READER_DB_PASSWORD}';  -- scorer API, future agent tools (read only)
  CREATE ROLE scorer       LOGIN PASSWORD '${SCORER_DB_PASSWORD}';      -- stream scorer: append decisions, upsert online features
  CREATE ROLE monitoring   LOGIN PASSWORD '${MONITORING_DB_PASSWORD}';
  CREATE ROLE marquez      LOGIN PASSWORD '${MARQUEZ_DB_PASSWORD}';     -- OpenLineage backend

  CREATE DATABASE airflow      OWNER airflow;
  CREATE DATABASE mlflow       OWNER mlflow;
  CREATE DATABASE bank_serving OWNER publisher;
  CREATE DATABASE knowledge    OWNER publisher;
  CREATE DATABASE monitoring   OWNER monitoring;
  CREATE DATABASE marquez      OWNER marquez;

  REVOKE ALL ON DATABASE bank_serving, knowledge, monitoring, mlflow, airflow, marquez FROM PUBLIC;
  GRANT CONNECT ON DATABASE bank_serving TO app_reader, scorer;
  GRANT CONNECT ON DATABASE knowledge    TO app_reader;
  GRANT CONNECT ON DATABASE monitoring   TO app_reader;
SQL
