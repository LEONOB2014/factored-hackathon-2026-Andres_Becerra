"""End-to-end check of the four-eyes corrections on a scratch lake (docs/platform/09 §D, evidence/phase4).

Nothing in the real lake is modified: the scratch lake symlinks the lossless zones (mutated_lake.py, so one held
partition exists) and has its own correction log and output folders. Steps:

1. build the lakehouse with an empty correction log (baseline);
2. stage and apply real corrections through `latam_platform.dq_corrections` (steward proposes, approver applies):
   the `Mexico` -> `México` variant in transactions and digital events, one rendered `nan` subject, one single cell,
   and the release of a held partition;
3. build again and read what changed (typed values, findings marked corrected, gate rates, holds, consumers);
4. revert every correction and the release, build, and compare with the baseline: it must be restored exactly;
5. build with `corrections_as_of` = the moment before the reverts, and compare with step 3: identical.

    cd platform && uv run python dbt/scripts/verify/corrections_e2e.py --scratch ../data/tmp/verify/e2e \\
        --profiles ../data/tmp/verify/profile --out ../docs/platform/evidence/phase4

Builds are one at a time; each is fingerprinted (compare_lakehouses.py) and deleted after use.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DBT = HERE.parents[1]


def run(cmd: list[str], env: dict, cwd: Path) -> None:
    print("+", " ".join(cmd[:6]), "...", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument(
        "--profiles", type=Path, required=True, help="dbt profiles dir with bounded memory"
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    scratch, out = args.scratch.resolve(), args.out.resolve()
    shutil.rmtree(scratch, ignore_errors=True)
    data = scratch / "data"
    lake = data / "lake"
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "LATAM_DATA_DIR": str(data), "LATAM_LAKE_DIR": str(lake),
           "DBT_PROFILES_DIR": str(args.profiles.resolve())}  # fmt: skip
    py = [sys.executable]
    real = {k: v for k, v in os.environ.items() if k not in ("LATAM_DATA_DIR", "LATAM_LAKE_DIR")}
    run(
        [*py, str(HERE / "mutated_lake.py"), "--out", str(lake)], real, DBT.parent
    )  # reads the real lake
    (lake / "mutations.json").unlink()

    sys.path.insert(0, str(DBT.parent / "libs"))
    os.environ.update({k: env[k] for k in ("LATAM_DATA_DIR",)})
    import duckdb

    from latam_platform import config
    from latam_platform import dq_corrections as dq

    assert lake == config.LAKE, (config.LAKE, lake)
    dq.ensure_log()

    def build(name: str, vars_: dict | None = None) -> Path:
        db = scratch / f"{name}.duckdb"
        cmd = [
            "dbt",
            "build",
            "--target-path",
            str(scratch / f"target_{name}"),
            "--log-path",
            str(scratch / "logs"),
        ]
        if vars_:
            cmd += ["--vars", json.dumps(vars_)]
        run(cmd, {**env, "LATAM_DUCKDB_PATH": str(db)}, DBT)
        run([*py, str(HERE / "compare_lakehouses.py"), "--fingerprint", str(db), "--out", str(scratch / f"{name}.json")],
            env, DBT)  # fmt: skip
        return db

    def drop(db: Path) -> None:
        for p in (db, db.with_suffix(".duckdb.wal")):
            p.unlink(missing_ok=True)
        shutil.rmtree(db.with_suffix(".duckdb.tmp"), ignore_errors=True)

    def compare(a: str, b: str, name: str) -> dict:
        target = out / f"{name}.csv"
        run([*py, str(HERE / "compare_lakehouses.py"), str(scratch / f"{a}.json"), str(scratch / f"{b}.json"),
             "--out", str(target)], env, DBT)  # fmt: skip
        with target.open() as f:
            rows = list(csv.DictReader(f))
        return {"identical": sum(r["status"] == "identical" for r in rows),
                "different": [r["relation"] for r in rows if r["status"] != "identical"]}  # fmt: skip

    def gate(db: Path) -> dict:
        con = duckdb.connect(str(db), read_only=True)
        rules = {
            (r, t): float(v)
            for r, t, v in con.sql("""SELECT rule_id, table_name, rate_pct FROM audit.dq_rule_summary
                                      WHERE rule_id IN ('C04', 'C06', 'C10')""").fetchall()
        }
        out = {
            "findings": con.sql("SELECT count(*) FROM audit.dq_cell_findings").fetchone()[0],
            "findings_marked_corrected": con.sql(
                "SELECT count(*) FROM audit.dq_cell_findings WHERE correction_proposal_id IS NOT NULL"
            ).fetchone()[0],
            "C04_transactions_pct": rules.get(("C04", "transactions")),
            "C04_digital_events_pct": rules.get(("C04", "digital_events")),
            "C06_campaign_sends_pct": rules.get(("C06", "campaign_sends")),
            "held_partitions": con.sql("SELECT count(*) FROM audit.dq_partition_holds").fetchone()[
                0
            ],
            "typed_transactions_mexico_unaccented": con.sql(
                "SELECT count(*) FROM silver.typed_transactions WHERE transaction_country = 'Mexico'"
            ).fetchone()[0],
            "typed_rows_with_corrections": con.sql(
                "SELECT count(*) FROM silver.typed_transactions WHERE len(_corrected_columns) > 0"
            ).fetchone()[0],
        }
        con.close()
        return out

    steps: dict = {}
    # 1. baseline
    base = build("base")
    steps["1_baseline"] = gate(base)
    con = duckdb.connect(str(base), read_only=True)
    nan_subject, nan_cells = con.sql("""SELECT raw_value, count(*) FROM audit.dq_cell_findings
                                        WHERE table_name = 'campaign_sends' AND issue_code = 'P'
                                        GROUP BY 1 ORDER BY 2 DESC LIMIT 1""").fetchone()
    held = con.sql("SELECT table_name, cast(partition_date AS varchar) FROM audit.dq_partition_holds "
                   "ORDER BY 1, 2 LIMIT 1").fetchone()  # fmt: skip
    cell = con.sql("""SELECT 'bronze', _source_file, _record_no, transaction_city FROM silver.typed_transactions
                      WHERE transaction_city = 'Monterrey' ORDER BY _source_file, _record_no LIMIT 1""").fetchone()
    con.close()

    # 2. corrections, proposed by steward and applied by approver
    proposals = {
        "e2e-mexico-tx": {"kind": "pattern", "pattern": {"table": "transactions", "column": "transaction_country",
                                                          "from_value": "Mexico", "to_value": "México"}},
        "e2e-mexico-de": {"kind": "pattern", "pattern": {"table": "digital_events", "column": "ip_country",
                                                          "from_value": "Mexico", "to_value": "México"}},
        "e2e-nan-subject": {"kind": "pattern", "pattern": {"table": "campaign_sends", "column": "subject",
                                                            "from_value": nan_subject, "to_value": ""}},
        "e2e-one-cell": {"kind": "cells", "cells": [{"zone": cell[0], "table": "transactions", "source_file": cell[1],
                                                      "record_no": cell[2], "column": "transaction_city",
                                                      "old_value": cell[3], "new_value": "Guadalajara"}]},
        "e2e-release": {"kind": "release", "release": {"table": held[0], "partition_date": held[1]}},
    }  # fmt: skip
    applied = {}
    lakehouse = duckdb.connect(str(base), read_only=True)
    for pid, body in proposals.items():
        (dq.root() / "proposals" / f"{pid}.json").write_text(
            json.dumps(
                {"proposal_id": pid, "reason": "end-to-end check", **body}, ensure_ascii=False
            )
        )
        summary = dq.stage(pid, "steward", lakehouse)
        res = dq.apply(pid, "steward", "approver", "e2e")
        applied[pid] = {"entries": res["entries"], "read_only": res["read_only"],
                        "findings_resolved": summary.get("findings_resolved")}  # fmt: skip
    lakehouse.close()
    drop(base)
    steps["2_applied"] = applied
    after_apply = datetime.now(UTC).replace(tzinfo=None)

    # 3. corrected build
    corr = build("corrected")
    steps["3_corrected"] = gate(corr)
    drop(corr)

    # 4. revert everything
    (dq.root() / "proposals" / "e2e-revert-all.json").write_text(json.dumps({
        "proposal_id": "e2e-revert-all", "kind": "revert", "reason": "end-to-end check: restore",
        "revert": {"proposal_ids": list(proposals)}}))  # fmt: skip
    dq.stage("e2e-revert-all", "steward")
    dq.apply("e2e-revert-all", "steward", "approver", "restore")
    reverted = build("reverted")
    steps["4_reverted"] = gate(reverted)
    drop(reverted)

    # 5. as of the moment before the reverts
    asof = build("as_of", {"corrections_as_of": after_apply.isoformat(sep=" ")})
    steps["5_as_of"] = gate(asof)
    drop(asof)

    steps["compare_base_vs_reverted"] = compare("base", "reverted", "base_vs_reverted")
    steps["compare_corrected_vs_as_of"] = compare("corrected", "as_of", "corrected_vs_as_of")
    steps["compare_base_vs_corrected"] = compare("base", "corrected", "base_vs_corrected")
    (out / "corrections_e2e.json").write_text(
        json.dumps(steps, indent=1, ensure_ascii=False, default=str) + "\n"
    )
    print(json.dumps(steps, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
