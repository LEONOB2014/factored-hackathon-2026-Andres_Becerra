#!/usr/bin/env python3
"""Fingerprint every raw CSV file (main and backup) and cache the result for the forensics notebook.

    uv run scripts/raw_schema_scan.py                 # both copies, resumes where it stopped
    uv run scripts/raw_schema_scan.py --copy main --table transactions --rebuild

For each copy and table it writes, under data/derived/raw_fingerprints/<copy>/:
  <table>__files.parquet       L0/L1 per file: bytes, sha256, BOM, line endings, UTF-8, records, header
  <table>__lexical.parquet     L2 per (file, column): value-class counts, lengths, charset, scale
  <table>__vocabulary.parquet  L3 per (file, column, value) for columns with <= --max-levels values
Everything is read from the raw text (see latam_eda.raw_forensics); the typed Parquet is never used.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from latam_eda import raw_forensics as rf  # noqa: E402
from latam_eda.data import DATA, DERIVED  # noqa: E402

COPIES = {"main": DATA / "raw" / "data", "backup": DATA / "raw" / "data_backup_20260831"}
OUT = DERIVED / "raw_fingerprints"


def tables(root: Path) -> list[str]:
    return sorted(
        p.stem if p.suffix == ".csv" else p.name
        for p in root.iterdir()
        if p.is_dir() or p.suffix == ".csv"
    )


def low_cardinality(con, files: list[Path], max_levels: int) -> list[str]:
    listing = "[" + ", ".join(f"'{f}'" for f in files) + "]"
    src = f"read_csv({listing}, {rf.READ_OPTS})"
    cols = [r[0] for r in con.sql(f"describe select * exclude (filename) from {src}").fetchall()]
    expr = ", ".join(f"approx_count_distinct({rf.q(c)}) as {rf.q(c)}" for c in cols)
    counts = con.sql(f"select {expr} from {src}").df().iloc[0]
    return [c for c in cols if counts[c] <= max_levels]


def scan_table(
    copy: str, root: Path, table: str, out: Path, rebuild: bool, max_levels: int, workers: int
):
    files = rf.table_files(root, table)
    targets = {k: out / f"{table}__{k}.parquet" for k in ("files", "lexical", "vocabulary")}
    if not rebuild and all(p.exists() for p in targets.values()):
        print(f"  {copy}/{table}: cached", flush=True)
        return
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        scans = list(pool.map(rf.scan_file, files, chunksize=8))
    fdf = pd.DataFrame([asdict(s) for s in scans])
    fdf["header"] = fdf["header"].map(json.dumps)
    fdf.to_parquet(targets["files"], index=False)

    con = duckdb.connect()
    rf.lexical_profile(con, files).to_parquet(targets["lexical"], index=False)
    vocab_cols = low_cardinality(con, files, max_levels)
    vocab = rf.vocabulary(con, files, vocab_cols) if vocab_cols else pd.DataFrame()
    vocab.to_parquet(targets["vocabulary"], index=False)
    print(
        f"  {copy}/{table}: {len(files):,} files, {int(fdf['records'].sum()):,} records, "
        f"{len(vocab_cols)} vocabulary columns, {time.time() - t0:,.0f}s",
        flush=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", choices=[*COPIES, "all"], default="all")
    ap.add_argument("--table", default=None)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--max-levels", type=int, default=300)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    for copy, root in COPIES.items():
        if a.copy not in ("all", copy) or not root.exists():
            continue
        out = OUT / copy
        out.mkdir(parents=True, exist_ok=True)
        print(f"{copy}: {root}", flush=True)
        for table in tables(root):
            if a.table in (None, table):
                scan_table(copy, root, table, out, a.rebuild, a.max_levels, a.workers)


if __name__ == "__main__":
    main()
