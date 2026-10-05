"""Read-only Postgres sessions as ``app_reader``.

Passwords are read from the environment or from ``platform/docker/.env``.
They are never logged, and connection failures are re-raised without the DSN.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from psycopg import sql

SERVING_DB = "bank_serving"
KNOWLEDGE_DB = "knowledge"
SERVING_SCHEMAS = ("decisions", "online_features", "serving")

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class DataApiError(Exception):
    """Failure safe to show a client. The message never contains a DSN."""


def load_stack_env(path: Path | None = None) -> None:
    """Fill missing environment keys from the stack env file. Existing keys win."""
    env_path = path if path is not None else _env_file()
    if env_path is None or not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def open_reader(db: str) -> Any:
    """Connect to ``db`` as ``app_reader``. The caller must close the connection."""
    load_stack_env()
    ops = _load_ops()
    try:
        return ops.pg(db, role="app_reader")
    except Exception:
        raise DataApiError(f"read-only connection to {db} failed") from None


@contextmanager
def session(db: str, *, connector: Any = open_reader) -> Iterator[Any]:
    """One read-only transaction. Writes fail even if a grant would allow them."""
    conn = connector(db)
    try:
        conn.execute("SET default_transaction_read_only = on")
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            yield conn
    finally:
        close = getattr(conn, "close", None)
        if close is not None:
            close()


def execute(conn: Any, query: Any, params: tuple | list = ()) -> Any:
    try:
        if params:
            return conn.execute(query, params)
        return conn.execute(query)
    except DataApiError:
        raise
    except Exception:
        raise DataApiError("read failed") from None


def rows(conn: Any, query: Any, params: tuple | list = ()) -> list[dict]:
    cur = execute(conn, query, params)
    if cur.description is None:
        return []
    names = [col.name for col in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def scalar(conn: Any, query: Any, params: tuple | list = ()) -> int:
    cur = execute(conn, query, params)
    row = cur.fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def count_query(schema: str, table: str) -> sql.Composed:
    """Count one catalog table. Names that fail the allow-list are refused."""
    if schema not in SERVING_SCHEMAS or _IDENT.fullmatch(table) is None:
        raise DataApiError("refusing to query an unexpected table")
    return sql.SQL("SELECT count(*) AS rows FROM {}.{}").format(
        sql.Identifier(schema),
        sql.Identifier(table),
    )


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        roots.append(start)
        roots.extend(start.parents)
    return roots


def _find_file(*parts: str) -> Path | None:
    for root in _candidate_roots():
        candidate = root.joinpath(*parts)
        if candidate.is_file():
            return candidate
    return None


def _env_file() -> Path | None:
    override = os.environ.get("DATA_API_STACK_ENV")
    if override:
        return Path(override)
    return _find_file("platform", "docker", ".env") or _find_file("docker", ".env")


def _libs_dir() -> Path:
    override = os.environ.get("LATAM_PLATFORM_LIBS")
    if override:
        return Path(override)
    ops_py = _find_file("platform", "libs", "latam_platform", "ops.py")
    if ops_py is None:
        ops_py = _find_file("libs", "latam_platform", "ops.py")
    if ops_py is None:
        raise DataApiError("latam_platform is not importable")
    return ops_py.parents[1]


def _load_ops() -> Any:
    libs = str(_libs_dir())
    if libs not in sys.path:
        sys.path.insert(0, libs)
    from latam_platform import ops

    return ops
