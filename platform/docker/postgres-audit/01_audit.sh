#!/usr/bin/env bash
# pg-audit: a separate Postgres instance on an isolated network. Roles:
#   audit_owner  (NOLOGIN) owns every object
#   audit_writer (LOGIN)   INSERT + SELECT only; cannot UPDATE / DELETE / TRUNCATE / ALTER
#   audit_reader (LOGIN)   SELECT only (auditors, verification jobs)
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-SQL
  CREATE ROLE audit_owner NOLOGIN;
  CREATE ROLE audit_writer LOGIN PASSWORD '${AUDIT_WRITER_PASSWORD}';
  CREATE ROLE audit_reader LOGIN PASSWORD '${AUDIT_READER_PASSWORD}';
  CREATE DATABASE audit OWNER audit_owner;
  REVOKE ALL ON DATABASE audit FROM PUBLIC;
  GRANT CONNECT ON DATABASE audit TO audit_writer, audit_reader;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname audit -f /docker-entrypoint-initdb.d/sql/02_audit_schema.sql
