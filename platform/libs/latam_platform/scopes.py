"""Country scopes: lossless subsets of bronze, cut before silver (ADR-016).

A scope is the whole bank (``ALL``, no cut) or one market. A market's lake keeps the same layout as the bank's lake
(``bronze_raw``, ``holdout_raw``, the quarantined backup, corrections and manifests), so the same compiled dbt project
runs on it unchanged through ``LATAM_LAKE_DIR`` and ``LATAM_DUCKDB_PATH`` (ADR-020).

Cut rules (ported from ``eda/src/latam_eda/country.py``, where the country series proved them):
  * customers: by the customer's country;
  * customer-owned tables: by ``customer_id``, so every join stays complete inside the scope;
  * digital events: by customer, and anonymous events by IP country;
  * shared reference tables: linked, not cut;
  * corrections and proof manifests: linked.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import duckdb

from latam_platform import config


@dataclass(frozen=True)
class Scope:
    code: str
    customer_raw: str  # spelling in customers.country
    raw_names: tuple[str, ...]  # spellings of the country in ip_country


MARKETS: dict[str, Scope] = {
    "MX": Scope("MX", "México", ("México", "Mexico")),
    "CO": Scope("CO", "Colombia", ("Colombia",)),
    "AR": Scope("AR", "Argentina", ("Argentina",)),
}
SCOPES = ("ALL", *MARKETS)
SHARED_TABLES = ("branches", "service_agents", "marketing_campaigns", "daily_exchange_rates")
BACKUP_DIR = "quarantine/backup_20260831_raw"
LINKED_DIRS = ("corrections", "manifests")
MANIFEST = "_country_lake.json"

SCOPES_DIR = Path(os.environ.get("LATAM_SCOPES_DIR", config.DATA / "scopes"))


def lake_dir(code: str, root: Path = SCOPES_DIR) -> Path:
    """The lake of a scope; ``ALL`` is the bank's own lake."""
    return config.LAKE if code == "ALL" else root / code.lower() / "lake"


def lakehouse_path(code: str, root: Path = SCOPES_DIR) -> Path:
    """The DuckDB file dbt builds for a scope: one per scope, so scopes never share the single writer."""
    return config.LAKEHOUSE_DB if code == "ALL" else root / code.lower() / "lakehouse.duckdb"


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _rel(glob: str) -> str:
    return f"read_parquet('{glob}', union_by_name = true, hive_partitioning = false)"


def _empty_like(con: duckdb.DuckDBPyConnection, src_glob: str, dest_file: Path) -> None:
    """A zero-row Parquet file with the schema of the source, so a table with no rows in the scope still reads."""
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY (SELECT * FROM {_rel(src_glob)} LIMIT 0) TO '{dest_file}' (FORMAT parquet)")


def _copy(con: duckdb.DuckDBPyConnection, src_glob: str, where: str, dest: Path) -> int:
    """Copy the rows of one bronze table that satisfy ``where`` into dest/<partition>/, lineage columns kept."""
    dest.mkdir(parents=True, exist_ok=True)
    n = con.sql(f"SELECT count(*) FROM {_rel(src_glob)} WHERE {where}").fetchone()[0]
    if n:
        con.sql(f"""COPY (SELECT * FROM {_rel(src_glob)} WHERE {where}) TO '{dest}'
                    (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (_partition_date), WRITE_PARTITION_COLUMNS true,
                     OVERWRITE_OR_IGNORE true, FILENAME_PATTERN 'part-{{i}}')""")
    else:
        _empty_like(con, src_glob, dest / "_empty" / "part-0.parquet")
    return n


def _link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        return
    dst.symlink_to(src, target_is_directory=src.is_dir())


def _count(con: duckdb.DuckDBPyConnection, glob: str) -> int:
    return con.sql(f"SELECT count(*) FROM {_rel(glob)}").fetchone()[0]


def cut(
    code: str, lake: Path | None = None, out: Path | None = None, force: bool = False
) -> list[dict]:
    """Write the scope's lossless subset of ``lake`` to ``out`` and return the rows kept per zone and table.

    Idempotent: a finished cut leaves ``_country_lake.json`` and is not redone unless ``force``.
    """
    if code not in MARKETS:
        raise ValueError(f"unknown market scope {code!r}; ALL is the bank's lake and is not cut")
    m = MARKETS[code]
    lake = lake or config.LAKE
    out = out or lake_dir(code)
    done = out / MANIFEST
    if done.exists() and not force:
        return json.loads(done.read_text())
    con = duckdb.connect()
    con.sql("SET enable_progress_bar = false")
    con.sql("SET preserve_insertion_order = false")
    names = ", ".join(_q(n) for n in m.raw_names)
    digital_where = (
        "customer_id IN (SELECT customer_id FROM ids) OR "
        f"(coalesce(customer_id, '') = '' AND ip_country IN ({names}))"
    )
    rows: list[dict] = []
    for zone, src_root, dst_root in (
        ("bronze_raw", lake / "bronze_raw", out / "bronze_raw"),
        ("backup", lake / BACKUP_DIR, out / BACKUP_DIR),
    ):
        if not src_root.exists():
            continue
        con.sql(f"""CREATE OR REPLACE TEMP TABLE ids AS SELECT DISTINCT customer_id
                    FROM {_rel(f"{src_root}/customers/*/*.parquet")} WHERE country = {_q(m.customer_raw)}""")
        for table in sorted(p.name for p in src_root.iterdir() if p.is_dir()):
            glob = f"{src_root / table}/*/*.parquet"
            total = _count(con, glob)
            if table in SHARED_TABLES:
                _link(src_root / table, dst_root / table)
                kept, rule = total, "shared (not cut)"
            elif table == "customers":
                kept = _copy(con, glob, f"country = {_q(m.customer_raw)}", dst_root / table)
                rule = "customer country"
            elif table == "digital_events":
                kept = _copy(con, glob, digital_where, dst_root / table)
                rule = "customer, or IP country when anonymous"
            else:
                kept = _copy(
                    con, glob, "customer_id IN (SELECT customer_id FROM ids)", dst_root / table
                )
                rule = "customer of the country"
            rows.append(
                {"zone": zone, "table": table, "rows_total": total, "rows_kept": kept, "rule": rule}
            )
        if zone == "bronze_raw" and (lake / "holdout_raw").exists():
            for table in sorted(p.name for p in (lake / "holdout_raw").iterdir() if p.is_dir()):
                glob = f"{lake / 'holdout_raw' / table}/*/*.parquet"
                where = (
                    digital_where
                    if table == "digital_events"
                    else "customer_id IN (SELECT customer_id FROM ids)"
                )
                kept = _copy(con, glob, where, out / "holdout_raw" / table)
                rows.append(
                    {
                        "zone": "holdout_raw",
                        "table": table,
                        "rows_total": _count(con, glob),
                        "rows_kept": kept,
                        "rule": "as in bronze",
                    }
                )
    for d in LINKED_DIRS:
        if (lake / d).exists():
            _link(lake / d, out / d)
    con.close()
    done.write_text(json.dumps(rows, indent=1))
    return rows
