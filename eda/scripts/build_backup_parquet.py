#!/usr/bin/env python3
"""Convert data/raw/data_backup_20260831 CSVs to Parquet in data/parquet_backup/."""

import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("LATAM_EDA_DATA", ROOT / "data")).expanduser().resolve()
RAW = DATA / "raw" / "data_backup_20260831"
OUT = DATA / "parquet_backup"


def convert(raw: Path = RAW, out: Path = OUT) -> list[str]:
    """One Parquet per table: partitioned folders (year/month/day/*.csv) or flat CSV files."""
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    written = []
    for p in sorted(raw.iterdir()):
        if p.is_dir():
            src, name, extra = f"{p}/*/*/*/*.csv", p.name, ", union_by_name=true"
        else:
            src, name, extra = str(p), p.stem, ""
        con.sql(f"""COPY (SELECT * FROM read_csv('{src}', header=true, sample_size=-1, ignore_errors=true{extra}))
                    TO '{out / (name + ".parquet")}' (FORMAT parquet, COMPRESSION zstd)""")
        print("✓", name, flush=True)
        written.append(name)
    return written


if __name__ == "__main__":
    convert()
