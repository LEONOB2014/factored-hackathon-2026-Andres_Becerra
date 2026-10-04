"""Build a scratch lake for the circuit-breaker positive control (docs/platform/09 §C.4).

The scratch lake is the real lossless lake by symlink, except a few real partitions rewritten the way a producer
change would arrive, and one proof-manifest header given a column the contract does not know. Nothing in the real
lake is modified. Build dbt against it with LATAM_LAKE_DIR pointing at the scratch lake, then read the outcome
with breaker_outcome.py.

    cd platform && uv run python dbt/scripts/verify/mutated_lake.py --out ../data/tmp/lake_mutated
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "libs"))
from latam_platform import config  # noqa: E402

# (table, partition) -> (SELECT list rewriting the partition, what it emulates, expected outcome)
MUTATIONS = {
    ("transactions", "2025-03-13"): (
        "* REPLACE (replace(amount, '.', ',') AS amount)",
        "amount written with a decimal comma",
        "held: format",
    ),
    ("transactions", "2025-04-04"): (
        "* REPLACE (cast(round(try_cast(amount AS double) * 1000, 2) AS varchar) AS amount)",
        "amount restated x1000 (unit change)",
        "held: scale",
    ),
    ("transactions", "2024-12-30"): (
        """* REPLACE (CASE transaction_type WHEN 'Adjustment' THEN 'Ajuste' WHEN 'Deposit' THEN 'Depósito'
             WHEN 'Payment' THEN 'Pago' WHEN 'Purchase' THEN 'Compra' WHEN 'Transfer' THEN 'Transferencia'
             WHEN 'Withdrawal' THEN 'Retiro' END AS transaction_type)""",
        "transaction_type translated to Spanish",
        "held: vocabulary",
    ),
    ("transactions", "2025-05-01"): (
        "* REPLACE (CASE WHEN _record_no <= 5 THEN 'Kiosk' ELSE channel END AS channel)",
        "5 records with a new channel 'Kiosk'",
        "reported (B), not held",
    ),
    ("digital_events", "2025-06-01"): (
        "* EXCLUDE (browser)",
        "column browser dropped from the file",
        "held: absent",
    ),
}
HEADER_MUTATION = (
    "transactions",
    "2025-06-10",
    "channel_v2",
)  # an unknown column in a landed header


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="scratch lake directory (recreated)")
    args = ap.parse_args()
    real, lake = config.LAKE.resolve(), args.out.resolve()
    if lake == real or real in lake.parents and lake.parent == real:
        sys.exit("the scratch lake must not be a zone of the real lake")
    shutil.rmtree(lake, ignore_errors=True)
    lake.mkdir(parents=True)
    for zone in ("holdout_raw", "quarantine"):
        (lake / zone).symlink_to(real / zone)
    for out_dir in (
        "graph",
        "knowledge",
        "features",
        "privacy",
        "stream",
    ):  # dbt external models write here
        (lake / out_dir).mkdir()
    (lake / "bronze_raw").mkdir()
    mutated_tables = {t for t, _ in MUTATIONS}
    for t in (real / "bronze_raw").iterdir():
        if t.name not in mutated_tables:
            (lake / "bronze_raw" / t.name).symlink_to(t)
    con = duckdb.connect()
    for table in sorted(mutated_tables):
        (lake / "bronze_raw" / table).mkdir()
        for part in (real / "bronze_raw" / table).iterdir():
            day = part.name.split("=", 1)[1]
            if (table, day) in MUTATIONS:
                (lake / "bronze_raw" / table / part.name).mkdir()
                con.sql(
                    f"COPY (SELECT {MUTATIONS[(table, day)][0]} FROM read_parquet('{part}/part-0.parquet')) "
                    f"TO '{lake}/bronze_raw/{table}/{part.name}/part-0.parquet' (FORMAT parquet)"
                )
            else:
                (lake / "bronze_raw" / table / part.name).symlink_to(part)
    (lake / "manifests").mkdir()
    for d in (real / "manifests").iterdir():
        if d.name != "bronze_raw_proof":
            (lake / "manifests" / d.name).symlink_to(d)
    proofs = lake / "manifests" / "bronze_raw_proof"
    shutil.copytree(real / "manifests" / "bronze_raw_proof", proofs)
    table, day, column = HEADER_MUTATION
    manifest = json.loads((proofs / f"{table}.json").read_text())
    y, m, d = day.split("-")
    key = next(k for k in manifest["files"] if f"year={y}/month={m}/day={d}/" in k)
    manifest["files"][key]["header"].append(column)
    (proofs / f"{table}.json").write_text(json.dumps(manifest))
    plan = [
        {"table_name": t, "partition_date": d, "mutation": what, "expected": expected}
        for (t, d), (_, what, expected) in sorted(MUTATIONS.items())
    ]
    plan.append({"table_name": table, "partition_date": day, "mutation": f"header gains column {column}",
                 "expected": "held: header_extra"})  # fmt: skip
    (lake / "mutations.json").write_text(json.dumps(plan, indent=1))
    print(json.dumps(plan, indent=1))


if __name__ == "__main__":
    main()
