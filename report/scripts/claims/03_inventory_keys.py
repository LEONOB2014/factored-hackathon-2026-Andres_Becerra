"""Chapter 3 · Inventory, keys and set difference: census facts from the hash-pinned parquet, and the stored
overlap tables of notebook 02.

    uv run python scripts/claims/03_inventory_keys.py
"""

from __future__ import annotations

import re

import pandas as pd

from report_lib import db
from report_lib.build import Chapter
from report_lib.eda import data
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

ERD = REPO / "docs" / "dataset" / "erd.md"
MAIN, BACKUP = REPO / "data" / "parquet", REPO / "data" / "parquet_backup"
OUT = BUILD / "sources"


def erd_tables() -> dict[str, int]:
    text = ERD.read_text()
    rows = re.findall(r"^\| `(\w+)` \| \w+ \| ([\d,]+) \|", text, re.M)
    return {t: int(n.replace(",", "")) for t, n in rows}


def erd_foreign_keys() -> list[tuple[str, str, str, str, bool]]:
    text = ERD.read_text()
    block = text[text.index("## Foreign keys") :]
    out = []
    for child, parent, nullable in re.findall(
        r"^\| `(\w+\.\w+)` \| `(\w+\.\w+)` \| (\w+) \|", block, re.M
    ):
        ct, cc = child.split(".")
        pt, pc = parent.split(".")
        out.append((ct, cc, pt, pc, nullable == "yes"))
    return out


def main() -> None:
    con = db.connect()
    ch = Chapter(3, "ch03")
    tables = data.FACTS + data.DIMS
    documented = erd_tables()
    present_b = {t: (BACKUP / f"{t}.parquet").exists() for t in tables}

    # --- inventory: rows in each copy against the documentation
    inv = []
    for t in tables:
        n_m = con.sql(f"select count(*) from m_{t}").fetchone()[0]
        n_b = con.sql(f"select count(*) from b_{t}").fetchone()[0] if present_b[t] else 0
        inv.append({"table": t, "documented": documented[t], "main": n_m, "backup": n_b,
                    "main_vs_documented_pct": 100 * (n_m - documented[t]) / documented[t]})  # fmt: skip
    inv = pd.DataFrame(inv)
    OUT.mkdir(parents=True, exist_ok=True)
    inv_path = OUT / "ch03_inventory.csv"
    inv.to_csv(inv_path, index=False)
    ch.count("tables-main", len(tables), MAIN / "transactions.parquet")
    ch.count("tables-backup", sum(present_b.values()), BACKUP / "transactions.parquet")
    for t in ("transactions", "digital_events", "customers"):
        r = inv[inv.table == t].iloc[0]
        ch.count(f"rows-main-{t.replace('_', '-')}", r.main, MAIN / f"{t}.parquet")
        ch.count(f"documented-{t.replace('_', '-')}", r.documented, ERD, source_type="table")
        ch.census(f"vs-documented-{t.replace('_', '-')}", r.main_vs_documented_pct, MAIN / f"{t}.parquet",
                  unit="percent", digits=3)  # fmt: skip
    r = inv[inv.table == "transactions"].iloc[0]
    ch.count("rows-backup-transactions", r.backup, BACKUP / "transactions.parquet")
    ch.census("backup-transactions-share", 100 * r.backup / r.main, BACKUP / "transactions.parquet", unit="percent",
              digits=3)  # fmt: skip
    fx = inv[inv.table == "daily_exchange_rates"].iloc[0]
    ch.count("rows-main-fx", fx.main, MAIN / "daily_exchange_rates.parquet")
    ch.count("documented-fx", fx.documented, ERD, source_type="table")
    pairs = con.sql(
        "select count(distinct (source_currency, target_currency)) from m_daily_exchange_rates"
    ).fetchone()[0]
    days = con.sql("select count(distinct date) from m_daily_exchange_rates").fetchone()[0]
    ch.count("fx-pairs", pairs, MAIN / "daily_exchange_rates.parquet")
    ch.count("fx-days", days, MAIN / "daily_exchange_rates.parquet")

    # --- primary keys: uniqueness and completeness, every keyed table, both copies
    dup = nul = 0
    for t, k in data.PK.items():
        for p in ("m", "b") if present_b[t] else ("m",):
            n, d, z = con.sql(
                f"select count(*), count(distinct {k}), count(*) - count({k}) from {p}_{t}"
            ).fetchone()
            dup, nul = dup + (n - d), nul + z
    ch.count("keyed-tables", len(data.PK), MAIN / "customers.parquet")
    ch.count("pk-duplicates", dup, MAIN / "customers.parquet")
    ch.count("pk-nulls", nul, MAIN / "customers.parquet")

    # --- referential integrity: every documented foreign key, main copy
    fk_rows = []
    for ct, cc, pt, pc, nullable in erd_foreign_keys():
        n, nn, orphan = con.sql(
            f"""select count(*), count(c.{cc}), count(c.{cc}) filter (where p.{pc} is null)
                from m_{ct} c left join (select distinct {pc} from m_{pt}) p on c.{cc} = p.{pc}"""
        ).fetchone()
        fk_rows.append({"foreign_key": f"{ct}.{cc}", "parent": f"{pt}.{pc}", "nullable": nullable,
                        "null_pct": 100 * (n - nn) / n, "orphan_pct_of_non_null": 100 * orphan / nn if nn else 0.0})  # fmt: skip
    fk = pd.DataFrame(fk_rows)
    fk_path = OUT / "ch03_foreign_keys.csv"
    fk.to_csv(fk_path, index=False)
    ch.count("fk-documented", len(fk), ERD, source_type="table")
    ch.count(
        "fk-resolving", int((fk.orphan_pct_of_non_null == 0).sum()), MAIN / "customers.parquet"
    )
    get = lambda name, col: float(fk.loc[fk.foreign_key == name, col].iloc[0])  # noqa: E731
    ch.census("fk-customer-branch-orphan", get("customers.registration_branch_id", "orphan_pct_of_non_null"),
              MAIN / "customers.parquet", unit="percent", digits=3)  # fmt: skip
    ch.census("fk-agent-branch-orphan", get("service_agents.assigned_branch_id", "orphan_pct_of_non_null"),
              MAIN / "service_agents.parquet", unit="percent", digits=3)  # fmt: skip
    ch.census("fk-complaint-interaction-null", get("complaints.origin_interaction_id", "null_pct"),
              MAIN / "complaints.parquet", unit="percent", digits=3)  # fmt: skip
    ch.census("fk-event-customer-null", get("digital_events.customer_id", "null_pct"),
              MAIN / "digital_events.parquet", unit="percent", digits=2)  # fmt: skip

    # --- coverage of the backup by month (figure source)
    months = []
    for t in data.FACTS:
        m = con.sql(
            f"select strftime(process_date, '%Y-%m') ym, count(*) n from m_{t} group by 1 order by 1"
        ).df()
        b = (con.sql(f"select strftime(process_date, '%Y-%m') ym, count(*) n from b_{t} group by 1 order by 1").df()
             if present_b[t] else pd.DataFrame(columns=["ym", "n"]))  # fmt: skip
        j = m.merge(b, on="ym", how="left", suffixes=("_main", "_backup")).fillna({"n_backup": 0})
        months.append(j.assign(table=t))
    cov = pd.concat(months).sort_values(["table", "ym"], kind="stable").reset_index(drop=True)
    cov_path = OUT / "ch03_monthly_coverage.csv"
    cov.to_csv(cov_path, index=False)
    tx = cov[(cov.table == "transactions") & (cov.n_backup > 0)]
    ch.count("backup-tx-months", len(tx), BACKUP / "transactions.parquet")
    ch.count(
        "main-tx-months", int((cov.table == "transactions").sum()), MAIN / "transactions.parquet"
    )

    # --- stored overlap tables of notebook 02 (exploratory, census over the two copies)
    pk = pd.read_csv(TABLES / "pk_overlap.csv").set_index("table")
    nat = pd.read_csv(TABLES / "natural_key_overlap.csv")
    fp = pd.read_csv(TABLES / "fingerprint_overlap.csv").set_index("table")
    for t in ("customers", "transactions", "complaints", "products", "service_agents"):
        ch.census(f"pk-shared-{t.replace('_', '-')}", pk.loc[t, "pct_main_shared"], TABLES / "pk_overlap.csv",
                  source_type="table", unit="percent", digits=3)  # fmt: skip
    ch.census("pk-shared-backup-transactions", pk.loc["transactions", "pct_backup_shared"],
              TABLES / "pk_overlap.csv", source_type="table", unit="percent", digits=2)  # fmt: skip
    key = lambda k: nat[(nat.table == "customers") & (nat.natural_key == k)].iloc[0]  # noqa: E731
    for k, topic in (("document_number", "doc"), ("(first_name,last_name,date_of_birth)", "name-dob"),
                     ("mobile_phone", "phone"), ("email", "email")):  # fmt: skip
        ch.census(f"nk-shared-{topic}", key(k).pct_main_shared, TABLES / "natural_key_overlap.csv",
                  source_type="table", unit="percent", digits=2)  # fmt: skip
    ch.count(
        "nk-shared-doc-n",
        key("document_number").shared,
        TABLES / "natural_key_overlap.csv",
        source_type="table",
    )
    ch.count(
        "email-distinct",
        key("email").main_distinct,
        TABLES / "natural_key_overlap.csv",
        source_type="table",
    )
    for t in ("transactions", "digital_events", "campaign_sends"):
        s = t.replace("_", "-")
        ch.census(f"fp-matched-{s}", fp.loc[t, "pct_main_rows"], TABLES / "fingerprint_overlap.csv",
                  source_type="table", unit="percent", digits=2)  # fmt: skip
        ch.census(f"fp-uniqueness-{s}", fp.loc[t, "fp_uniqueness"], TABLES / "fingerprint_overlap.csv",
                  source_type="table", digits=2)  # fmt: skip

    # --- rendered tables
    render_table(inv_path, "ch03-inventory", "Rows per table in each copy against the documented volume.",
                 count_cols=())  # fmt: skip
    render_table(fk_path, "ch03-foreign-keys", "Every documented foreign key of the main copy: share of null "
                 "child keys and share of non-null child keys absent from the parent.", digits=3)  # fmt: skip
    render_table(TABLES / "pk_overlap.csv", "ch03-pk-overlap", "Surrogate-key overlap between the copies "
                 "(notebook 02).", columns=["table", "main_keys", "backup_keys", "shared", "pct_main_shared"])  # fmt: skip
    render_table(TABLES / "natural_key_overlap.csv", "ch03-natural-keys", "Natural-key overlap between the copies "
                 "(notebook 02).", digits=3)  # fmt: skip
    render_table(TABLES / "fingerprint_overlap.csv", "ch03-fingerprints", "Content-fingerprint overlap and "
                 "fingerprint uniqueness (notebook 02).", columns=["table", "main_rows", "main_distinct_fp",
                 "shared_fp", "matched_rows", "pct_main_rows", "fp_uniqueness"])  # fmt: skip
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
