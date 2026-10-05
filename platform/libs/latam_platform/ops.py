"""Connections used by pipeline tasks. Every store is reached with a workload-specific role:
publisher (serving/knowledge writes), audit_writer (ledger inserts), platform S3 user (WORM writes)."""

from __future__ import annotations

import json
import os

from latam_platform import config


def pg(db: str, role: str = "publisher"):
    import psycopg

    pw = {
        "publisher": "PUBLISHER_DB_PASSWORD",
        "app_reader": "APP_READER_DB_PASSWORD",
        "scorer": "SCORER_DB_PASSWORD",
        "monitoring": "MONITORING_DB_PASSWORD",
    }[role]
    host = os.environ.get("LATAM_PG_CORE_HOST", "127.0.0.1")
    port = os.environ.get("LATAM_PG_CORE_PORT", "5432" if host != "127.0.0.1" else "5433")
    return psycopg.connect(
        f"postgresql://{role}:{os.environ[pw]}@{host}:{port}/{db}", autocommit=True
    )


def audit():
    import psycopg

    from latam_platform import audit_ledger

    return psycopg.connect(audit_ledger.dsn(), autocommit=True)


def ledger(
    event_type: str,
    subject_ref: str | None,
    payload: dict,
    run_id: str | None = None,
    actor: str = "svc-airflow",
) -> str:
    from latam_platform import audit_ledger

    with audit() as c:
        return audit_ledger.append_event(
            c, actor, event_type, subject_ref, payload, lineage_run_id=run_id
        )


def s3():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("LATAM_S3_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.environ["MINIO_PLATFORM_USER"],
        aws_secret_access_key=os.environ["MINIO_PLATFORM_PASSWORD"],
        region_name="us-east-1",
    )


def worm_put_json(bucket: str, key: str, doc: dict) -> str:
    """Write a JSON document to an object-locked bucket (bucket default retention = COMPLIANCE)."""
    s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(doc, indent=1, default=str).encode(),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"


def lakehouse(read_only: bool = True, path: str | os.PathLike | None = None):
    """The dbt lakehouse: the bank's (default) or a country scope's file (ADR-020)."""
    import duckdb

    os.chdir(config.REPO_ROOT / "platform" / "dbt")  # staging views resolve ../../data/lake
    con = duckdb.connect(str(path or config.LAKEHOUSE_DB), read_only=read_only)
    con.sql(f"SET memory_limit = '{os.environ.get('LATAM_DUCKDB_MEMORY', '2GB')}'")
    return con


def neo4j_driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(
        os.environ.get("LATAM_NEO4J_URI", "bolt://neo4j:7687"),
        auth=("neo4j", os.environ["NEO4J_PASSWORD"]),
    )
