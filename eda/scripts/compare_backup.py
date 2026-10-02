#!/usr/bin/python3
"""Row/column-level comparison of data/parquet (main) vs data/parquet_backup.
Run scripts/build_backup_parquet.py first. Prints, per table: schema diff, PK overlap and
per-column differences on shared primary keys."""

import duckdb

c = duckdb.connect()
M, B = "data/parquet", "data/parquet_backup"
pk = {
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
for t, k in pk.items():
    m = f"'{M}/{t}.parquet'"
    b = f"'{B}/{t}.parquet'"
    cm = [
        r[0]
        for r in c.sql(f"describe select * from {m}").fetchall()
        if r[0] not in ("day", "month", "year")
    ]
    cb = [
        r[0]
        for r in c.sql(f"describe select * from {b}").fetchall()
        if r[0] not in ("day", "month", "year")
    ]
    print(
        f"\n=== {t}: main cols={len(cm)} backup cols={len(cb)} schema_diff main-only={set(cm) - set(cb)} backup-only={set(cb) - set(cm)}"
    )
    r = c.sql(f"""select (select count(*) from {m}) rows_main,(select count(*) from {b}) rows_backup,
      (select count(distinct {k}) from {m}) uk_main,(select count(distinct {k}) from {b}) uk_backup,
      (select count(*) from (select {k} from {b} except select {k} from {m})) only_backup,
      (select count(*) from (select {k} from {m} except select {k} from {b})) only_main""").fetchone()
    print("rows_main,rows_backup,uniq_main,uniq_backup,only_backup,only_main =", r)
    common = [x for x in cm if x in cb and x != k]
    if t == "transactions":  # restrict main to backup's window for fair compare
        pass
    diffs = (
        c.sql(
            "select "
            + ",".join(
                f"count(*) filter (where m.{x} is distinct from b.{x}) as {x}" for x in common
            )
            + f" ,count(*) joined from {m} m join {b} b using({k})"
        )
        .df()
        .T
    )
    diffs.columns = ["n"]
    print(
        diffs[diffs.n > 0].to_string()
        if (diffs.n > 0).any()
        else "no column differences on shared keys",
        "| joined rows:",
        int(diffs.loc["joined", "n"]),
    )
