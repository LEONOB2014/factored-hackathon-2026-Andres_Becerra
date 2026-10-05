"""Connection rules: app_reader, read-only transactions, no DSN in errors."""

from __future__ import annotations

import os

import pytest
from psycopg import sql

from data_api.db import DataApiError, count_query, load_stack_env, open_reader, session


class FakeConn:
    def __init__(self) -> None:
        self.statements: list[tuple] = []
        self.closed = False
        self.description = None
        self.rows: list[tuple] = []

    def execute(self, query, params=None):
        self.statements.append((query, params))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self) -> None:
        self.closed = True


def test_load_stack_env_fills_missing_and_does_not_override(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("DATA_API_EXAMPLE", raising=False)
    monkeypatch.setenv("DATA_API_KEEP", "from-env")
    env_file = tmp_path / "stack.env"
    env_file.write_text(
        'DATA_API_EXAMPLE="from-file"\nDATA_API_KEEP=from-file\n# comment\n\nnot a pair\n'
    )
    load_stack_env(env_file)
    assert os.environ["DATA_API_EXAMPLE"] == "from-file"
    assert os.environ["DATA_API_KEEP"] == "from-env"


def test_open_reader_uses_app_reader(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_pg(db: str, role: str = "publisher"):
        seen["db"] = db
        seen["role"] = role
        return FakeConn()

    import latam_platform.ops as ops

    monkeypatch.setattr(ops, "pg", fake_pg)
    conn = open_reader("bank_serving")
    assert seen == {"db": "bank_serving", "role": "app_reader"}
    assert isinstance(conn, FakeConn)


def test_open_reader_hides_the_dsn(monkeypatch) -> None:
    def fake_pg(db: str, role: str = "publisher"):
        raise RuntimeError("dsn-redaction-marker")

    import latam_platform.ops as ops

    monkeypatch.setattr(ops, "pg", fake_pg)
    with pytest.raises(DataApiError) as caught:
        open_reader("knowledge")
    message = str(caught.value)
    assert "dsn-redaction-marker" not in message
    assert "knowledge" in message


def test_session_forces_read_only_and_closes() -> None:
    conn = FakeConn()
    with session("bank_serving", connector=lambda _db: conn):
        pass
    texts = [item[0] for item in conn.statements]
    assert "SET default_transaction_read_only = on" in texts
    assert "SET TRANSACTION READ ONLY" in texts
    assert conn.closed is True


def test_count_query_quotes_identifiers() -> None:
    query = count_query("serving", "publication_log")
    assert isinstance(query, sql.Composed)
    assert any(isinstance(part, sql.Identifier) for part in query)


@pytest.mark.parametrize(
    ("schema", "table"),
    [
        ("serving", "publication_log; drop table serving.publication_log"),
        ("public", "publication_log"),
        ("serving", "Customer_360"),
        ("serving", ""),
    ],
)
def test_count_query_rejects_unexpected_names(schema: str, table: str) -> None:
    with pytest.raises(DataApiError):
        count_query(schema, table)
