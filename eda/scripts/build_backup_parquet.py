#!/usr/bin/env python3
"""Convert <repo>/data/raw/data_backup_20260831 CSVs to Parquet in <repo>/data/parquet_backup/."""

import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from latam_eda.csvio import csv_to_parquet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("LATAM_EDA_DATA", ROOT.parent / "data")).expanduser().resolve()
RAW = DATA / "raw" / "data_backup_20260831"
OUT = DATA / "parquet_backup"


def convert(raw: Path = RAW, out: Path = OUT) -> list[str]:
    """One Parquet per table: partitioned folders (year/month/day/*.csv) or flat CSV files."""
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    written = []
    for p in sorted(raw.iterdir()):
        if p.is_dir():  # partitioned fact: headers may differ between days in this untrusted copy
            files, name, union = sorted(p.glob("*/*/*/*.csv")), p.name, True
        elif p.suffix == ".csv":
            files, name, union = [p], p.stem, False
        else:
            continue  # .DS_Store and other non-data files
        n = csv_to_parquet(con, files, out / f"{name}.parquet", union_by_name=union)
        print("✓", name, f"{n:,} rows", flush=True)
        written.append(name)
    return written


if __name__ == "__main__":
    convert()
