"""Integration fixtures: a throwaway copy of the audit schema on the local pg-core container.

Requires `docker compose --profile core up -d pg-core` (port 127.0.0.1:5433). Tests are skipped otherwise.
"""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[3]
AUDIT_SQL = ROOT / "platform" / "docker" / "postgres-audit" / "sql" / "02_audit_schema.sql"


def _env() -> dict:
    env = {}
    p = ROOT / "platform" / "docker" / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
    return env


@pytest.fixture(scope="session")
def audit_db():
    env = _env()
    su_base = f"postgresql://postgres:{env.get('PG_CORE_SUPERUSER_PASSWORD', '')}@127.0.0.1:5433"
    su = f"{su_base}/postgres"
    try:
        admin = psycopg.connect(su, autocommit=True, connect_timeout=3)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"pg-core not reachable: {e}")
    db = f"audit_test_{uuid.uuid4().hex[:8]}"
    for role, login in (
        ("audit_owner", "NOLOGIN"),
        ("audit_writer", "LOGIN"),
        ("audit_reader", "LOGIN"),
    ):
        admin.execute(
            f"DO $$ BEGIN CREATE ROLE {role} {login}; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
    # fresh passwords per run, never stored in the repository
    writer_pw, reader_pw = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    admin.execute(f"ALTER ROLE audit_writer PASSWORD '{writer_pw}'")
    admin.execute(f"ALTER ROLE audit_reader PASSWORD '{reader_pw}'")
    admin.execute(f"CREATE DATABASE {db} OWNER audit_owner")
    with psycopg.connect(f"{su_base}/{db}", autocommit=True) as c:
        c.execute(AUDIT_SQL.read_text())
        c.execute(f"GRANT CONNECT ON DATABASE {db} TO audit_writer, audit_reader")
    writer = f"postgresql://audit_writer:{writer_pw}@127.0.0.1:5433/{db}"
    yield {"writer": writer, "superuser": f"{su_base}/{db}"}
    admin.execute(f"DROP DATABASE {db} WITH (FORCE)")
    admin.close()


@pytest.fixture
def writer_conn(audit_db):
    with psycopg.connect(audit_db["writer"], autocommit=True) as c:
        yield c
