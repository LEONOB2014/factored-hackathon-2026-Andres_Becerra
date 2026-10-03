"""Bronze build: landing CSV -> typed, partitioned, append-only Parquet with lineage columns.

Rules that make bronze evidence rather than a scratch copy:
* nothing is dropped silently: rows the CSV parser rejects go to quarantine with the error, and
  loaded + rejected must equal the data lines counted in the landing manifest;
* every row carries `_ingest_run_id`, `_source_file`, `_ingested_at` and `_row_md5`;
* partitions are append-only: an existing partition whose logical digest differs from the rebuild
  raises `BronzeIntegrityError` instead of being overwritten;
* facts on/after the stream cutoff go to the holdout zone (replayed or batch-loaded later);
* the untrusted backup folder is written to quarantine, never to bronze.
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from latam_platform import config
from latam_platform.config import Table


class BronzeIntegrityError(RuntimeError):
    """An existing bronze partition would change: bronze is append-only."""


def _connect(file_backed: bool = False) -> duckdb.DuckDBPyConnection:
    import os

    tmp = config.DATA / "tmp" / "duckdb"
    tmp.mkdir(parents=True, exist_ok=True)
    if file_backed:  # staging lives on disk, not in the capped RAM
        db = tmp / f"bronze_stage_{os.getpid()}.duckdb"
        db.unlink(missing_ok=True)
        con = duckdb.connect(str(db))
    else:
        con = duckdb.connect()
    con.sql("SET preserve_insertion_order = true")
    con.sql(f"SET memory_limit = '{os.environ.get('LATAM_DUCKDB_MEMORY', '8GB')}'")
    con.sql(f"SET threads = {os.environ.get('LATAM_DUCKDB_THREADS', '8')}")
    con.sql(f"SET temp_directory = '{tmp}'")
    return con


def _read_csv_sql(src, table: Table) -> str:
    if isinstance(src, list):
        src = "[" + ", ".join(f"'{p}'" for p in src) + "]"
    else:
        src = f"'{src}'"
    # union_by_name cannot be combined with rejects tables; every daily file shares one header
    # (checked by the landing reconciliation: a header drift would surface as rejected rows).
    multi = ", hive_partitioning=false" if table.kind == "fact" else ""
    return (
        f"read_csv({src}, header=true, sample_size=-1, filename=true, store_rejects=true, "
        f"rejects_scan='rej_scan', rejects_table='rej_errors'{multi})"
    )


def _stage(con: duckdb.DuckDBPyConnection, table: Table, src: str, run_id: str) -> None:
    con.sql("DROP TABLE IF EXISTS rej_scan; DROP TABLE IF EXISTS rej_errors")
    con.sql(f"""
        CREATE OR REPLACE TABLE staged AS
        SELECT * EXCLUDE (filename),
               md5(cast(row(*columns(* EXCLUDE (filename))) AS varchar)) AS _row_md5,
               '{run_id}'                                             AS _ingest_run_id,
               regexp_replace(filename, '^.*/raw/', 'raw/')           AS _source_file,
               current_timestamp                                     AS _ingested_at
        FROM {_read_csv_sql(src, table)}
    """)


def _partition_digests(con, rel: str, part_col: str | None) -> dict[str, dict]:
    key = f"cast({part_col} AS varchar)" if part_col else "'all'"
    rows = con.sql(f"""
        SELECT {key} AS part, count(*) AS n, md5(string_agg(_row_md5, '' ORDER BY _row_md5)) AS digest
        FROM {rel} GROUP BY ALL""").fetchall()
    return {p: {"rows": n, "digest": d} for p, n, d in rows}


def _write(
    con, rel: str, out_dir: Path, part_col: str | None, manifest_path: Path, force: bool
) -> dict:
    new = _partition_digests(con, rel, part_col)
    old = json.loads(manifest_path.read_text())["partitions"] if manifest_path.exists() else {}
    changed = [p for p in new if p in old and old[p]["digest"] != new[p]["digest"]]
    if changed and not force:
        raise BronzeIntegrityError(
            f"{out_dir.name}: {len(changed)} existing partitions would change, e.g. {changed[:3]}"
        )
    to_write = [p for p in new if p not in old or force or p in changed]
    if to_write:
        tmp = out_dir.with_name(out_dir.name + ".__tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if part_col:
            con.sql(f"""COPY (SELECT * FROM {rel} WHERE cast({part_col} AS varchar) IN ({",".join(repr(p) for p in to_write)}))
                        TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY ({part_col}),
                                    WRITE_PARTITION_COLUMNS true, FILENAME_PATTERN 'part-{{i}}')""")
            for d in tmp.iterdir():  # move partition dirs into place atomically per partition
                dest = out_dir / d.name
                if dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                d.rename(dest)
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp.mkdir(parents=True)
            con.sql(
                f"COPY (SELECT * FROM {rel}) TO '{tmp}/part-0.parquet' (FORMAT parquet, COMPRESSION zstd)"
            )
            snap = out_dir / f"snapshot_date={config.DATA_END.isoformat()}"
            shutil.rmtree(snap, ignore_errors=True)
            snap.mkdir(parents=True)
            (tmp / "part-0.parquet").rename(snap / "part-0.parquet")
        shutil.rmtree(tmp, ignore_errors=True)
    merged = {**old, **new}
    manifest = {
        "zone_path": str(out_dir.relative_to(config.DATA)),
        "updated_at": datetime.now(UTC).isoformat(),
        "rows": sum(v["rows"] for v in merged.values()),
        "partitions": dict(sorted(merged.items())),
        "written_now": sorted(to_write),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=1))
    return manifest


def _csv_records(files: list[Path]) -> int:
    """CSV-aware record count (quoted fields may contain newlines, so lines != records)."""
    csv.field_size_limit(1 << 30)
    n = 0
    for f in files:
        with f.open(newline="", encoding="utf-8", errors="replace") as fh:
            n += sum(1 for _ in csv.reader(fh)) - 1
    return n


def _fact_chunks(table: Table) -> list[list[str]]:
    """Group a fact table's daily files by month (directory layout <table>/YYYY/MM/DD/*.csv)."""
    files = sorted(Path(config.SOURCES["main"], table.name).glob("*/*/*/*.csv"))
    chunks: dict[str, list[str]] = {}
    for f in files:
        chunks.setdefault(f"{f.parts[-4]}-{f.parts[-3]}", []).append(str(f))
    return [chunks[k] for k in sorted(chunks)]


def build_table(
    table: Table, run_id: str, landing_lines: dict[str, int] | None = None, force: bool = False
) -> dict:
    """Build bronze (+ holdout) for one main-source table and return its reconciliation record.

    Facts are processed one month of files at a time in a file-backed DuckDB that can spill to disk, so memory
    stays bounded regardless of table size (the scheduler container is memory-capped)."""
    con = _connect(file_backed=True)
    sources = _fact_chunks(table) if table.kind == "fact" else [[config.raw_glob("main", table)]]
    loaded = rejected = bronze_rows = holdout_rows = written = 0
    for files in sources:
        src = files[0] if len(files) == 1 else files
        _stage(con, table, src, run_id)
        loaded += con.sql("SELECT count(*) FROM staged").fetchone()[0]
        rej = con.sql("SELECT count(DISTINCT (file_id, line)) FROM rej_errors").fetchone()[0]
        rejected += rej
        if rej:
            qdir = config.QUARANTINE / "rejects"
            qdir.mkdir(parents=True, exist_ok=True)
            con.sql(
                f"COPY (SELECT e.*, s.file_path FROM rej_errors e JOIN rej_scan s USING (scan_id, file_id)) "
                f"TO '{qdir}/{table.name}__{run_id}__{abs(hash(files[0]))}.parquet' (FORMAT parquet)"
            )
        if table.kind == "fact":
            cut = config.STREAM_CUTOFF.isoformat()
            con.sql(
                f"CREATE OR REPLACE TEMP VIEW hist AS SELECT * FROM staged WHERE process_date < DATE '{cut}'"
            )
            con.sql(
                f"CREATE OR REPLACE TEMP VIEW hold AS SELECT * FROM staged WHERE process_date >= DATE '{cut}'"
            )
            m_b = _write(
                con,
                "hist",
                config.BRONZE / table.name,
                "process_date",
                config.MANIFESTS / "bronze" / f"{table.name}.json",
                force,
            )
            m_h = _write(
                con,
                "hold",
                config.HOLDOUT / table.name,
                "process_date",
                config.MANIFESTS / "holdout" / f"{table.name}.json",
                force,
            )
            bronze_rows, holdout_rows = m_b["rows"], m_h["rows"]
            written += len(m_b["written_now"]) + len(m_h["written_now"])
        else:
            m = _write(
                con,
                "staged",
                config.BRONZE / table.name,
                None,
                config.MANIFESTS / "bronze" / f"{table.name}.json",
                force,
            )
            bronze_rows, written = m["rows"], len(m["written_now"])
    result = {
        "table": table.name,
        "run_id": run_id,
        "loaded": loaded,
        "rejected": rejected,
        "bronze_rows": bronze_rows,
        "holdout_rows": holdout_rows,
        "partitions_written": written,
    }

    if landing_lines is not None:  # reconcile against bytes received
        prefix = f"data/{table.name}"
        files = [k for k in landing_lines if k == f"{prefix}.csv" or k.startswith(prefix + "/")]
        data_lines = sum(landing_lines[k] - 1 for k in files)  # minus header per file
        result["landing_data_lines"] = data_lines
        if data_lines != loaded + rejected:  # multi-line quoted fields: recount as CSV records
            data_lines = _csv_records([config.LANDING / k for k in files])
            result["landing_csv_records"] = data_lines
        result["reconciled"] = data_lines == loaded + rejected
    return result


def build_quarantine_backup(run_id: str) -> list[dict]:
    """Write the untrusted backup folder to quarantine (single file per table, never joined to main)."""
    out = []
    qdir = config.QUARANTINE / "backup_20260831"
    qdir.mkdir(parents=True, exist_ok=True)
    for table in config.TABLES.values():
        src = config.raw_glob("backup_20260831", table)
        if not list(Path(config.SOURCES["backup_20260831"]).glob(table.name + "*")):
            out.append({"table": table.name, "status": "absent"})
            continue
        con = _connect(file_backed=True)
        _stage(con, table, src, run_id)
        con.sql(f"COPY staged TO '{qdir}/{table.name}.parquet' (FORMAT parquet, COMPRESSION zstd)")
        out.append(
            {"table": table.name, "rows": con.sql("SELECT count(*) FROM staged").fetchone()[0]}
        )
    return out
