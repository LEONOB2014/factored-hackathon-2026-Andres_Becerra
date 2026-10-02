#!/usr/bin/env python3
"""Convert data/raw/data_backup_20260831 CSVs to Parquet in data/parquet_backup/."""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "data_backup_20260831"
OUT = ROOT / "data" / "parquet_backup"
OUT.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
for p in sorted(RAW.iterdir()):
    if p.is_dir():
        src, name, extra = f"{p}/*/*/*/*.csv", p.name, ", union_by_name=true"
    else:
        src, name, extra = str(p), p.stem, ""
    con.sql(f"""COPY (SELECT * FROM read_csv('{src}', header=true, sample_size=-1, ignore_errors=true{extra}))
                TO '{OUT / (name + ".parquet")}' (FORMAT parquet, COMPRESSION zstd)""")
    print("✓", name, flush=True)
