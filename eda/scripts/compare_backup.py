#!/usr/bin/python3
"""Row/column-level comparison of data/parquet (main) vs data/parquet_backup.
Run scripts/build_backup_parquet.py first. Prints, per table: schema diff, PK overlap and
per-column differences on shared primary keys."""

import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("LATAM_EDA_DATA", ROOT / "data")).expanduser().resolve()
MAIN = DATA / "parquet"
BACKUP = DATA / "parquet_backup"
PARTITION_COLS = ("day", "month", "year")
PK = {
    "customers": "customer_id",
    "products": "product_id",
    "branches": "branch_id",
    "service_agents": "agent_id",
    "marketing_campaigns": "campaign_id",
    "transactions": "transaction_id",
    "digital_events": "event_id",
    "call_center_interactions": "interaction_id",
    "campaign_sends": "send_id",
    "complaints": "complaint_id",
}


def compare_table(c, main: Path, backup: Path, t: str, k: str) -> dict:
    """Schema diff, key overlap and per-column differences on shared keys for one table."""
    m = f"'{main}/{t}.parquet'"
    b = f"'{backup}/{t}.parquet'"
    cm = [
        r[0] for r in c.sql(f"describe select * from {m}").fetchall() if r[0] not in PARTITION_COLS
    ]
    cb = [
        r[0] for r in c.sql(f"describe select * from {b}").fetchall() if r[0] not in PARTITION_COLS
    ]
    counts = c.sql(f"""select (select count(*) from {m}) rows_main,(select count(*) from {b}) rows_backup,
      (select count(distinct {k}) from {m}) uk_main,(select count(distinct {k}) from {b}) uk_backup,
      (select count(*) from (select {k} from {b} except select {k} from {m})) only_backup,
      (select count(*) from (select {k} from {m} except select {k} from {b})) only_main""").fetchone()
    common = [x for x in cm if x in cb and x != k]
    diffs = (
        c.sql(
            "select "
            + "".join(
                f"count(*) filter (where m.{x} is distinct from b.{x}) as {x}, " for x in common
            )
            + f"count(*) joined from {m} m join {b} b using({k})"
        )
        .df()
        .T
    )
    diffs.columns = ["n"]
    return {
        "table": t,
        "main_cols": cm,
        "backup_cols": cb,
        "main_only_cols": set(cm) - set(cb),
        "backup_only_cols": set(cb) - set(cm),
        "counts": dict(
            zip(
                [
                    "rows_main",
                    "rows_backup",
                    "uniq_main",
                    "uniq_backup",
                    "only_backup",
                    "only_main",
                ],
                counts,
                strict=True,
            )
        ),
        "column_diffs": {col: int(n) for col, n in diffs.n.items() if col != "joined" and n > 0},
        "joined": int(diffs.loc["joined", "n"]),
    }


def compare(main: Path = MAIN, backup: Path = BACKUP, pk: dict[str, str] = PK) -> list[dict]:
    c = duckdb.connect()
    return [compare_table(c, main, backup, t, k) for t, k in pk.items()]


def main() -> None:
    for r in compare(MAIN, BACKUP, PK):
        print(
            f"\n=== {r['table']}: main cols={len(r['main_cols'])} backup cols={len(r['backup_cols'])}"
            f" schema_diff main-only={r['main_only_cols']} backup-only={r['backup_only_cols']}"
        )
        print(
            "rows_main,rows_backup,uniq_main,uniq_backup,only_backup,only_main =",
            tuple(r["counts"].values()),
        )
        if r["column_diffs"]:
            for col, n in r["column_diffs"].items():
                print(f"{col:>30} {n}")
        else:
            print("no column differences on shared keys")
        print("| joined rows:", r["joined"])


if __name__ == "__main__":
    main()
