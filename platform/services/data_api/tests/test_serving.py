"""Publication log and table counts. The database is a fake connection."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from data_api.app import create_app
from data_api.db import SERVING_SCHEMAS, DataApiError
from data_api.serving import (
    PUBLICATIONS_SQL,
    TABLES_SQL,
    list_publications,
    list_tables,
    map_publication,
)
from data_api.store import PostgresStore


class Cursor:
    def __init__(self, records: list[tuple], names: list[str]) -> None:
        self._records = records
        self.description = [SimpleNamespace(name=name) for name in names]

    def fetchall(self) -> list[tuple]:
        return self._records

    def fetchone(self) -> tuple | None:
        return self._records[0] if self._records else None


class ScriptedConn:
    def __init__(self, script: list[tuple[str, Cursor]]) -> None:
        self.script = list(script)
        self.statements: list[tuple] = []
        self.closed = False

    def execute(self, query, params=None):
        self.statements.append((query, params))
        text = query if isinstance(query, str) else "COMPOSED"
        for index, (needle, cursor) in enumerate(self.script):
            if needle in text:
                self.script.pop(index)
                return cursor
        return Cursor([], [])

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


def test_serving_sql_selects_metadata_only() -> None:
    for statement in (PUBLICATIONS_SQL, TABLES_SQL):
        lowered = statement.lower()
        assert re.search(r"select\s+\*", lowered) is None
        for banned in ("customer_id", "embedding", "feature_snapshot", "content"):
            assert re.search(rf"\b{banned}\b", lowered) is None
    assert "%s" in TABLES_SQL


def test_map_publication_keeps_only_registry_fields() -> None:
    published = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
    mapped = map_publication(
        {
            "table_name": "customer_360",
            "row_count": 12,
            "content_digest": "digest",
            "lineage_run_id": "run-1",
            "published_at": published,
            "customer_id": "hidden",
        }
    )
    assert mapped == {
        "table": "customer_360",
        "rows": 12,
        "digest": "digest",
        "run_id": "run-1",
        "published_at": published.isoformat(),
    }


def test_list_publications_reads_the_log() -> None:
    cursor = Cursor(
        [("account_inquiry", 4, "abc", "manual", None)],
        ["table_name", "row_count", "content_digest", "lineage_run_id", "published_at"],
    )
    found = list_publications(ScriptedConn([("publication_log", cursor)]))
    assert found == [
        {
            "table": "account_inquiry",
            "rows": 4,
            "digest": "abc",
            "run_id": "manual",
            "published_at": None,
        }
    ]


def test_list_tables_counts_catalog_rows_with_bound_schemas() -> None:
    catalog = Cursor(
        [("decisions", "fraud_decision_log"), ("serving", "publication_log")],
        ["table_schema", "table_name"],
    )
    conn = ScriptedConn(
        [
            ("information_schema.tables", catalog),
            ("COMPOSED", Cursor([(3,)], ["rows"])),
            ("COMPOSED", Cursor([(9,)], ["rows"])),
        ]
    )
    assert list_tables(conn) == [
        {"schema": "decisions", "table": "fraud_decision_log", "rows": 3},
        {"schema": "serving", "table": "publication_log", "rows": 9},
    ]
    _query, params = conn.statements[0]
    assert params == (list(SERVING_SCHEMAS),)


def test_store_opens_bank_serving_read_only() -> None:
    conn = ScriptedConn([])
    seen: list[str] = []

    def connector(db: str) -> ScriptedConn:
        seen.append(db)
        return conn

    store = PostgresStore(connector=connector)
    assert store.publications() == []
    assert store.tables() == []
    assert seen == ["bank_serving", "bank_serving"]
    texts = [item[0] for item in conn.statements]
    assert texts.count("SET TRANSACTION READ ONLY") == 2
    assert conn.closed is True


def test_routes_return_store_rows() -> None:
    class Memory:
        def publications(self) -> list[dict]:
            return [
                {
                    "table": "customer_360",
                    "rows": 1,
                    "digest": "d",
                    "run_id": "r",
                    "published_at": None,
                }
            ]

        def tables(self) -> list[dict]:
            return [{"schema": "serving", "table": "publication_log", "rows": 1}]

    client = TestClient(create_app(store=Memory()))
    assert client.get("/serving/publications").json()["publications"][0]["table"] == "customer_360"
    assert client.get("/serving/tables").json()["tables"][0]["rows"] == 1


def test_database_errors_are_generic_503s() -> None:
    class Down:
        def publications(self) -> list[dict]:
            raise DataApiError("read-only connection to bank_serving failed")

        def tables(self) -> list[dict]:
            raise DataApiError("read failed")

    client = TestClient(create_app(store=Down()))
    response = client.get("/serving/tables")
    assert response.status_code == 503
    assert "postgresql://" not in response.text
    assert "password" not in response.text.lower()
