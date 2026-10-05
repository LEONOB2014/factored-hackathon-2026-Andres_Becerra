"""Request-scoped reads. Each call is one read-only ``app_reader`` transaction."""

from __future__ import annotations

from typing import Any

from data_api.db import KNOWLEDGE_DB, SERVING_DB, open_reader, session
from data_api.knowledge import list_documents, read_active_set
from data_api.serving import list_publications, list_tables


class PostgresStore:
    def __init__(self, connector: Any = None) -> None:
        self._connector = connector or open_reader

    def publications(self) -> list[dict]:
        with session(SERVING_DB, connector=self._connector) as conn:
            return list_publications(conn)

    def tables(self) -> list[dict]:
        with session(SERVING_DB, connector=self._connector) as conn:
            return list_tables(conn)

    def documents(self) -> list[dict]:
        with session(KNOWLEDGE_DB, connector=self._connector) as conn:
            return list_documents(conn)

    def active_set(self) -> dict:
        with session(KNOWLEDGE_DB, connector=self._connector) as conn:
            return read_active_set(conn)
