#!/usr/bin/env python3
"""Positive controls for the raw schema forensics: inject known mutations and score the detectors.

    uv run scripts/mutate_partitions.py               # 90 days of transactions, mutation from day 45

For each mutation in latam_eda.mutations.transactions_catalogue(), a scratch copy of `--days` daily
transaction files is written under data/derived/mutation_lab/<mutation>/ (verbatim before the
change day, mutated from it), fingerprinted exactly like the real data and run through
change_detection.detect_table. A clean copy (no mutation) measures false alarms.

Writes reports/tables/forensics_detector_scorecard.csv:
  mutation, expected finding, detected, delay in days, false alarms before the change day.
"""

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from latam_eda import change_detection as cd  # noqa: E402
from latam_eda import mutations as mu  # noqa: E402
from latam_eda import raw_forensics as rf  # noqa: E402
from latam_eda.data import DATA, DERIVED  # noqa: E402

RAW = DATA / "raw" / "data"
LAB = DERIVED / "mutation_lab"
OUT = Path(__file__).resolve().parent.parent / "reports" / "tables"
VOCAB = ["transaction_type", "currency", "channel", "transaction_status"]


def fingerprint(files: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scans = pd.DataFrame([asdict(rf.scan_file(f)) for f in files])
    scans["header"] = scans["header"].map(json.dumps)
    con = duckdb.connect()
    try:
        lex = rf.lexical_profile(con, files)
        voc = rf.vocabulary(con, files, VOCAB)
    except duckdb.Error:
        # a grammar-breaking mutation makes the strict reader fail: only L0/L1 can speak
        lex = pd.DataFrame(columns=["file", "column", "n", "partition_date"])
        voc = pd.DataFrame(columns=["file", "column", "value", "n", "partition_date"])
    return scans, lex, voc


def matches(findings: pd.DataFrame, expect: str) -> pd.DataFrame:
    level, column, signal, kind = expect.split("|")
    f = findings[(findings["level"] == level) & (findings["kind"] == kind)]
    f = f[f["signal"].astype(str).str.startswith(signal)]
    if column:
        f = f[f["column"] == column]
    return f


def run(days: int, change_at: int, start: str) -> pd.DataFrame:
    source = [f for f in rf.table_files(RAW, "transactions") if rf.partition_date(f) >= start][
        :days
    ]
    change_day = pd.Timestamp(rf.partition_date(source[change_at]))
    rows, baseline = [], None
    key = ["level", "column", "signal", "kind"]
    for m in [None, *mu.transactions_catalogue()]:
        name = m.name if m else "clean_copy"
        lab = LAB / name
        shutil.rmtree(lab, ignore_errors=True)
        files = []
        for i, f in enumerate(source):
            dst = lab / f.relative_to(RAW)
            mu.rewrite(f, dst, m if (m and i >= change_at) else None)
            files.append(dst)
        scans, lex, voc = fingerprint(files)
        for df in (scans, lex, voc):
            if len(df):
                df["partition_date"] = pd.to_datetime(df["partition_date"])
        findings = cd.detect_table(scans, lex, voc if len(voc) else None)
        shutil.rmtree(lab, ignore_errors=True)
        if m is None:
            # genuine variation of the real data in this window: not attributable to any mutation
            baseline = findings
            rows.append(
                {
                    "mutation": name,
                    "expected": "",
                    "detected": None,
                    "delay_days": None,
                    "new_findings": 0,
                    "false_alarms_before_change": 0,
                    "baseline_findings": len(findings),
                }
            )
            print(rows[-1], flush=True)
            continue
        new = findings.merge(baseline[key].drop_duplicates(), on=key, how="left", indicator=True)
        new = new[new["_merge"] == "left_only"].drop(columns="_merge")
        hit = matches(new, m.expect)
        delay = None
        if len(hit) and hit["change_date"].notna().any():
            delay = int((hit["change_date"].min() - change_day).days)
        rows.append(
            {
                "mutation": name,
                "expected": m.expect,
                "detected": bool(len(hit)),
                "delay_days": delay,
                "new_findings": len(new),
                "false_alarms_before_change": int((new["change_date"] < change_day).sum()),
                "baseline_findings": len(baseline),
            }
        )
        print(rows[-1], flush=True)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--change-at", type=int, default=45)
    ap.add_argument("--start", default="2024-01-01")
    a = ap.parse_args()
    score = run(a.days, a.change_at, a.start)
    OUT.mkdir(parents=True, exist_ok=True)
    score.to_csv(OUT / "forensics_detector_scorecard.csv", index=False)


if __name__ == "__main__":
    main()
