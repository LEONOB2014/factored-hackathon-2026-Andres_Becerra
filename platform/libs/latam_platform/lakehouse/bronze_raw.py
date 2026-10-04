"""Lossless bronze of record: every landed record, every field as its original text, proven byte-exact.

The typed bronze (bronze.py) keeps every record but coerces cells (an empty field becomes NULL, values
take auto-detected types). This zone is the compliance copy:

* every field is stored as the exact text that was written: no trim, `''` kept, no typing;
* every record carries `_source_file`, `_source_sha256`, `_record_no`, `_record_sha256`,
  `_parse_status` and, only when the record is not ok or not canonical, its exact bytes;
* **proof per file before anything is written**: the file's sha256 equals the landing manifest, the
  file rebuilt from its parts hashes to the same value, and an independent strict CSV count equals the
  number of records (raw_records.py). Any failure raises `BronzeIntegrityError`;
* `verify_table_raw` re-reads the *stored* Parquet and rebuilds every file again, so it proves the
  artefact on disk (and detects later tampering), not the build's memory;
* partitions are append-only (shared logic in bronze._write, keyed on `_record_sha256`);
* facts on/after the stream cutoff go to holdout_raw; the untrusted backup copy goes to quarantine.

Until silver reads this zone (phase 3), dbt keeps reading the typed bronze.
"""

from __future__ import annotations

import base64
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from latam_platform import config
from latam_platform.config import Table
from latam_platform.lakehouse import raw_records as rr
from latam_platform.lakehouse.bronze import BronzeIntegrityError, _connect, _write

LINEAGE = [
    "_source_file",
    "_source_sha256",
    "_record_no",
    "_record_sha256",
    "_parse_status",
    "_raw_record",
    "_partition_date",
    "_ingest_run_id",
    "_ingested_at",
]
PROOF_DIR = "bronze_raw_proof"


def table_files(source: str, table: Table) -> list[Path]:
    base = config.SOURCES[source]
    if table.kind == "fact":
        return sorted((base / table.name).glob("year=*/month=*/day=*/*.csv"))
    single = base / f"{table.name}.csv"
    return [single] if single.exists() else []


def partition_date(path: Path) -> str:
    """yyyy-mm-dd from the Hive path; dimensions and reference tables use the snapshot date."""
    parts = {p.split("=")[0]: p.split("=")[1] for p in path.parts if "=" in p}
    if {"year", "month", "day"} <= parts.keys():
        return f"{parts['year']}-{parts['month']}-{parts['day']}"
    return config.DATA_END.isoformat()


def _prove_file(args: tuple[str, str, str | None]) -> dict:
    """Read, split, parse and prove one file (runs in a worker process)."""
    path, rel, landing_sha = args
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    fr = rr.read_file(raw)
    rebuilt = hashlib.sha256(rr.rebuild_file(fr)).hexdigest()
    independent = rr.strict_record_count(raw)
    counts = fr.counts()
    problems = []
    if landing_sha is None:
        problems.append("file is not in the landing manifest")
    elif sha != landing_sha:
        problems.append("file changed since it landed (sha256 differs from the landing manifest)")
    if rebuilt != sha:
        problems.append("file does not rebuild byte-exact from its records")
    clean = counts["ok"] == counts["records"]
    if independent is None and clean:
        problems.append("independent CSV parse failed although every record parsed")
    if independent is not None and independent != counts["records"]:
        problems.append(f"record count {counts['records']} != independent count {independent}")
    return {
        "file": rel,
        "sha256": sha,
        "landing_sha256": landing_sha,
        "rebuilt_sha256": rebuilt,
        "independent_records": independent,
        **counts,
        "bom": fr.bom,
        "terminator": base64.b64encode(fr.terminator).decode(),
        "header_b64": base64.b64encode(fr.header_raw).decode(),
        "header": fr.header,
        "problems": problems,
        "rows": [(r.record_no, r.fields, r.status, r.sha256, r.raw) for r in fr.records],
    }


def _frame(proofs: list[dict], run_id: str) -> pd.DataFrame:
    """All records of a chunk of files: data columns as text (union of headers), then lineage."""
    columns: list[str] = []
    for p in proofs:
        columns += [c for c in p["header"] if c not in columns]
    data: dict[str, list] = {c: [] for c in columns + LINEAGE}
    now = datetime.now(UTC).isoformat()
    for p in proofs:
        width = len(p["header"])
        index = {c: i for i, c in enumerate(p["header"])}
        part = partition_date(Path(p["file"]))
        for record_no, fields, status, sha, raw in p["rows"]:
            for c in columns:
                i = index.get(c)
                data[c].append(
                    fields[i] if fields is not None and i is not None and i < width else None
                )
            data["_source_file"].append(p["file"])
            data["_source_sha256"].append(p["sha256"])
            data["_record_no"].append(record_no)
            data["_record_sha256"].append(sha)
            data["_parse_status"].append(status)
            data["_raw_record"].append(raw)
            data["_partition_date"].append(part)
            data["_ingest_run_id"].append(run_id)
            data["_ingested_at"].append(now)
    return pd.DataFrame(data)


def _landing_shas() -> dict[str, str]:
    from latam_platform.lakehouse import landing

    manifest = landing.latest_manifest() or {"files": []}
    return {f["path"]: f["sha256"] for f in manifest["files"]}


def _proof_path(source: str, table: str) -> Path:
    prefix = "" if source == "main" else f"{source}__"
    return config.MANIFESTS / PROOF_DIR / f"{prefix}{table}.json"


def build_table_raw(
    table: Table,
    run_id: str,
    source: str = "main",
    landing_sha: dict[str, str] | None = None,
    force: bool = False,
    chunk: int = 8,
    workers: int = 4,
) -> dict:
    """Prove and write every file of one table into the lossless zone; return its reconciliation."""
    landing_sha = _landing_shas() if landing_sha is None else landing_sha
    files = table_files(source, table)
    if not files:
        return {"table": table.name, "source": source, "status": "absent"}
    if source == "main":
        zones = {"hist": config.BRONZE_RAW / table.name, "hold": config.HOLDOUT_RAW / table.name}
    else:
        zones = {"hist": config.QUARANTINE_RAW / table.name}
    mdir = config.MANIFESTS / ("bronze_raw" if source == "main" else f"bronze_raw_{source}")
    proof_path = _proof_path(source, table.name)
    proof = json.loads(proof_path.read_text())["files"] if proof_path.exists() else {}
    con = _connect(file_backed=True)
    totals = {
        "files": 0,
        "records": 0,
        "verbatim": 0,
        "ok": 0,
        "ragged": 0,
        "quote_error": 0,
        "encoding_error": 0,
        "partitions_written": 0,
    }
    cut = config.STREAM_CUTOFF.isoformat()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i in range(0, len(files), chunk):
            batch = files[i : i + chunk]
            args = []
            for f in batch:
                rel = str(f.relative_to(config.LANDING))
                args.append((str(f), rel, landing_sha.get(rel)))
            proofs = list(pool.map(_prove_file, args))
            failed = {p["file"]: p["problems"] for p in proofs if p["problems"]}
            if failed:
                raise BronzeIntegrityError(
                    f"{table.name}: {len(failed)} file(s) fail the proof: {failed}"
                )
            con.register("chunk_df", _frame(proofs, run_id))
            con.sql("CREATE OR REPLACE TEMP TABLE chunk AS SELECT * FROM chunk_df")
            con.unregister("chunk_df")
            part_col = "_partition_date" if table.kind == "fact" else None
            if source == "main" and table.kind == "fact":
                con.sql(
                    f"CREATE OR REPLACE TEMP VIEW hist AS SELECT * FROM chunk WHERE _partition_date < '{cut}'"
                )
                con.sql(
                    f"CREATE OR REPLACE TEMP VIEW hold AS SELECT * FROM chunk WHERE _partition_date >= '{cut}'"
                )
                rels = {"hist": "hist", "hold": "hold"}
            else:
                rels = {"hist": "chunk"}
            for zone, rel in rels.items():
                if con.sql(f"SELECT count(*) FROM {rel}").fetchone()[0] == 0:
                    continue
                m = _write(
                    con,
                    rel,
                    zones[zone],
                    part_col,
                    mdir / f"{zone}__{table.name}.json",
                    force,
                    digest_col="_record_sha256",
                )
                totals["partitions_written"] += len(m["written_now"])
            for p in proofs:
                proof[p["file"]] = {k: v for k, v in p.items() if k not in ("rows", "problems")}
                totals["files"] += 1
                for k in ("records", "verbatim", "ok", "ragged", "quote_error", "encoding_error"):
                    totals[k] += p[k]
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(
        json.dumps(
            {
                "table": table.name,
                "source": source,
                "run_id": run_id,
                "updated_at": datetime.now(UTC).isoformat(),
                "files": dict(sorted(proof.items())),
            },
            indent=1,
        )
    )
    return {"table": table.name, "source": source, "run_id": run_id, "proven": True, **totals}


def _close_file(name, digest, count, proof, landing_sha, problems) -> None:
    """Compare one rebuilt file with the landing sha256 and its proven record count."""
    p = proof.get(name)
    if p is None:
        problems.append(f"{name}: stored but not in the proof manifest")
        return
    got = digest.hexdigest()
    if got != landing_sha.get(name):
        problems.append(
            f"{name}: rebuilt sha256 {got[:12]} != landing {str(landing_sha.get(name))[:12]}"
        )
    if count != p["records"]:
        problems.append(f"{name}: {count} stored records != {p['records']} proven")


def verify_table_raw(table: Table, source: str = "main") -> dict:
    """Rebuild every file of a table from the *stored* Parquet and compare with the landing sha256.

    Independent of the build: it uses only what is on disk (records + the proof manifest's header bytes)
    and the landing manifest. Missing files, extra files, a changed value or a missing record all fail.
    """
    landing_sha = _landing_shas()
    proof_path = _proof_path(source, table.name)
    if not proof_path.exists():
        return {
            "table": table.name,
            "source": source,
            "verified": False,
            "problems": ["no proof manifest"],
        }
    proof = json.loads(proof_path.read_text())["files"]
    zones = [config.BRONZE_RAW, config.HOLDOUT_RAW] if source == "main" else [config.QUARANTINE_RAW]
    globs = [str(z / table.name / "**" / "*.parquet") for z in zones if (z / table.name).exists()]
    expected = {str(f.relative_to(config.LANDING)) for f in table_files(source, table)}
    problems: list[str] = []
    if not globs:
        return {
            "table": table.name,
            "source": source,
            "verified": False,
            "problems": ["no stored partitions"],
        }
    # One stored Parquet file at a time: a source file never spans two partitions, so memory stays flat
    # (one global ORDER BY over 15.6M rows needed 5.5 GB, above the scheduler's 4 GB limit).
    con = _connect()
    parts = sorted(f for g in globs for f in Path(g.split("**")[0]).rglob("*.parquet"))
    seen: set[str] = set()
    for part in parts:
        cols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM read_parquet('{part}')").fetchall()]
        data_cols = [c for c in cols if c not in LINEAGE]
        cur = con.execute(
            f"""SELECT _source_file, _record_no, _raw_record, {", ".join(f'"{c}"' for c in data_cols)}
                FROM read_parquet('{part}') ORDER BY _source_file, _record_no"""
        )
        current, digest, count, prev_no, index, term = None, None, 0, 0, [], b"\r\n"
        while batch := cur.fetchmany(50_000):
            for row in batch:
                name, record_no, raw = row[0], row[1], row[2]
                if name != current:
                    if current is not None:
                        _close_file(current, digest, count, proof, landing_sha, problems)
                    if name in seen:
                        problems.append(f"{name}: stored in more than one partition")
                    current, count, prev_no = name, 0, 0
                    seen.add(name)
                    p = proof.get(name, {})
                    digest = hashlib.sha256()
                    digest.update(
                        (rr.BOM if p.get("bom") else b"")
                        + base64.b64decode(p.get("header_b64", ""))
                    )
                    index = [data_cols.index(c) for c in p.get("header", []) if c in data_cols]
                    term = base64.b64decode(p.get("terminator", "DQo="))
                if record_no != prev_no + 1:
                    problems.append(f"{name}: record {prev_no + 1} missing before {record_no}")
                prev_no = record_no
                count += 1
                if raw is not None:
                    digest.update(bytes(raw))
                else:
                    digest.update(rr.canonical([row[3 + i] for i in index], term))
        if current is not None:
            _close_file(current, digest, count, proof, landing_sha, problems)
    for name in sorted(expected - seen):
        problems.append(f"{name}: landed but not stored")
    return {
        "table": table.name,
        "source": source,
        "files": len(seen),
        "verified": not problems,
        "problems": problems[:50],
        "problem_count": len(problems),
    }


def worm_sync(s3, bucket: str, run_id: str) -> dict:
    """Copy lossless partitions the object-locked bucket does not hold yet, plus this run's proofs.

    Idempotent and append-only: an object already in the bucket is never rewritten (object lock would
    keep the old version anyway), and proof manifests go under a run-specific prefix.
    """
    existing: set[str] = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="lake/"):
        existing.update(o["Key"] for o in page.get("Contents", []))
    uploaded = 0
    for zone in (config.BRONZE_RAW, config.HOLDOUT_RAW, config.QUARANTINE_RAW):
        if not zone.exists():
            continue
        for f in sorted(zone.rglob("*.parquet")):
            key = "lake/" + str(f.relative_to(config.LAKE))
            if key not in existing:
                s3.upload_file(str(f), bucket, key)
                uploaded += 1
    proofs = sorted((config.MANIFESTS / PROOF_DIR).glob("*.json"))
    for f in proofs:
        s3.upload_file(str(f), bucket, f"manifests/{PROOF_DIR}/{run_id}/{f.name}")
    return {
        "bucket": bucket,
        "partitions_uploaded": uploaded,
        "already_sealed": len(existing),
        "proof_manifests": len(proofs),
    }
