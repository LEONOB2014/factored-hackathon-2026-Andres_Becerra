"""Read what the circuit breaker did in a lakehouse build (docs/platform/09 §C.4).

Writes, per partition with a drift check: the checks that fired, whether it is held, and how many of its rows reach
the typed models, staging and gold. With --mutations (from mutated_lake.py) every mutated partition is listed with
its expected outcome and an `as_expected` verdict; partitions nobody mutated but which drifted are listed too (they
would be false alarms in a positive control, real findings in a production build). Also writes the per-rule cell
findings of the build.

    cd platform/dbt && uv run python scripts/verify/breaker_outcome.py LAKEHOUSE.duckdb \
        --mutations ../../data/tmp/lake_mutated/mutations.json --out breaker.csv --findings findings.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb

ROWS = {  # table -> (typed model, staging model, gold fact or None, partition column in staging/gold)
    "transactions": (
        "silver.typed_transactions",
        "silver.stg_transactions",
        "gold.fct_transaction",
    ),
    "digital_events": ("silver.typed_digital_events", "silver.stg_digital_events", None),
}


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lakehouse", type=Path)
    ap.add_argument("--mutations", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--findings", type=Path)
    args = ap.parse_args()
    con = duckdb.connect(str(args.lakehouse), read_only=True)
    con.sql("SET enable_progress_bar = false")
    drift = con.sql("""
        SELECT table_name, cast(partition_date AS varchar) AS day,
               string_agg(DISTINCT severity || ':' || check_name || ':' || column_name, ';'
                          ORDER BY severity || ':' || check_name || ':' || column_name) AS checks
        FROM audit.dq_schema_drift GROUP BY ALL""").fetchall()
    held = {
        (t, str(d))
        for t, d in con.sql(
            "SELECT table_name, partition_date FROM audit.dq_partition_holds"
        ).fetchall()
    }
    plan = json.loads(args.mutations.read_text()) if args.mutations else []
    expected = {(p["table_name"], p["partition_date"]): p for p in plan}
    keys = sorted({(t, d) for t, d, _ in drift} | set(expected))
    checks = {(t, d): c for t, d, c in drift}
    rows = []
    for t, d in keys:
        p = expected.get((t, d), {})
        counts = {"rows_typed": "", "rows_staging": "", "rows_gold": ""}
        if t in ROWS:
            typed, stg, gold = ROWS[t]
            counts["rows_typed"] = con.sql(
                f"SELECT count(*) FROM {typed} WHERE _partition_date = DATE '{d}'"
            ).fetchone()[0]
            counts["rows_staging"] = con.sql(
                f"SELECT count(*) FROM {stg} WHERE process_date = DATE '{d}'"
            ).fetchone()[0]
            if gold:
                counts["rows_gold"] = con.sql(
                    f"SELECT count(*) FROM {gold} WHERE process_date = DATE '{d}'"
                ).fetchone()[0]
        is_held = (t, d) in held
        verdict = ""
        if p:
            want_held = p["expected"].startswith("held")
            want_check = p["expected"].split(": ", 1)[1] if want_held else "vocabulary"
            verdict = is_held == want_held and f":{want_check}:" in checks.get((t, d), "")
        elif args.mutations:
            verdict = not is_held  # not mutated: a hold here would be a false alarm
        rows.append({"table_name": t, "partition_date": d, "mutation": p.get("mutation", ""),
                     "expected": p.get("expected", ""), "checks": checks.get((t, d), ""), "held": is_held,
                     **counts, "as_expected": verdict})  # fmt: skip
        print(rows[-1], flush=True)
    write(args.out, rows)
    if args.findings:
        f = con.sql("""SELECT rule_id, severity, table_name, rule_description, violations, table_rows, rate_pct,
                              baseline_rate_pct, max_rate_pct, slo_breached
                       FROM audit.dq_rule_summary WHERE rule_id LIKE 'C%' AND violations > 0 ORDER BY 1, 3""")
        write(args.findings, [dict(zip(f.columns, r, strict=True)) for r in f.fetchall()])
    print(
        f"{len(rows)} partitions, held {len(held)}, as expected: {all(r['as_expected'] for r in rows if r['as_expected'] != '')}"
    )


if __name__ == "__main__":
    main()
