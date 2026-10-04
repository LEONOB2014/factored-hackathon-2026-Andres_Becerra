#!/usr/bin/env python3
"""
Initial EDA of the LATAM Bank dataset (<repo>/data/raw/data).

1. Converts the CSVs (12k daily files) to typed Parquet in <repo>/data/parquet/ (cached;
   use --rebuild to redo). Later analyses should read the Parquet files.
2. Profiles every table with DuckDB: rows, date range, nulls, duplicates,
   orphan foreign keys, category distributions.
3. Writes reports/eda_overview.md and figures to reports/figures/.

Usage:
    uv run scripts/eda_overview.py [--rebuild]
"""

import argparse
import os
import sys
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from latam_eda.csvio import csv_to_parquet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("LATAM_EDA_DATA", ROOT.parent / "data")).expanduser().resolve()
RAW = DATA / "raw" / "data"
PQ = DATA / "parquet"
REPORTS = ROOT / "reports"
FIGS = REPORTS / "figures"

console = Console()

FACTS = {  # table -> (primary key, documented rows)
    "transactions": ("transaction_id", 5_000_000),
    "digital_events": ("event_id", 10_000_000),
    "call_center_interactions": ("interaction_id", 800_000),
    "call_transcripts": ("transcript_id", 200_000),
    "campaign_sends": ("send_id", 2_000_000),
    "complaints": ("complaint_id", 80_000),
    "satisfaction_surveys": ("survey_id", 250_000),
}
DIMS = {
    "customers": ("customer_id", 150_000),
    "products": ("product_id", 400_000),
    "branches": ("branch_id", 350),
    "service_agents": ("agent_id", 1_200),
    "marketing_campaigns": ("campaign_id", 200),
    "daily_exchange_rates": (None, 3_000),
}
# (child table, column, parent table, parent key)
FKS = [
    ("transactions", "customer_id", "customers", "customer_id"),
    ("transactions", "product_id", "products", "product_id"),
    ("transactions", "branch_id", "branches", "branch_id"),
    ("products", "customer_id", "customers", "customer_id"),
    ("digital_events", "customer_id", "customers", "customer_id"),
    ("call_center_interactions", "customer_id", "customers", "customer_id"),
    ("call_center_interactions", "agent_id", "service_agents", "agent_id"),
    ("call_transcripts", "interaction_id", "call_center_interactions", "interaction_id"),
    ("satisfaction_surveys", "interaction_id", "call_center_interactions", "interaction_id"),
    ("complaints", "customer_id", "customers", "customer_id"),
    ("campaign_sends", "campaign_id", "marketing_campaigns", "campaign_id"),
    ("campaign_sends", "customer_id", "customers", "customer_id"),
]


def build_parquet(con, rebuild: bool):
    PQ.mkdir(parents=True, exist_ok=True)
    for table in [*FACTS, *DIMS]:
        out = PQ / f"{table}.parquet"
        if out.exists() and not rebuild:
            continue
        files = (
            sorted((RAW / table).glob("*/*/*/*.csv")) if table in FACTS else [RAW / f"{table}.csv"]
        )
        # One shared header per table (verified), so no union_by_name: a header change fails loudly.
        with console.status(f"Converting {table} to Parquet..."):
            csv_to_parquet(con, files, out)
        console.print(f"[green]✓[/] {table}")


def view_all(con):
    for table in [*FACTS, *DIMS]:
        con.sql(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM '{PQ / table}.parquet'")


def md_table(df) -> str:
    return df.to_markdown(index=False) if len(df) else "_empty_"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect()
    build_parquet(con, args.rebuild)
    view_all(con)
    FIGS.mkdir(parents=True, exist_ok=True)
    out = ["# LATAM Bank – initial EDA\n"]

    def section(title, df, note=""):
        out.append(f"\n## {title}\n")
        if note:
            out.append(note + "\n")
        out.append(md_table(df) + "\n")
        console.rule(title)
        console.print(df.to_string(index=False))

    # 1. Row counts vs documentation, date range, duplicate keys --------------
    rows = []
    for table, (pk, documented) in {**FACTS, **DIMS}.items():
        n = con.sql(f"SELECT count(*) FROM {table}").fetchone()[0]
        dup = (
            con.sql(f"SELECT count(*) - count(DISTINCT {pk}) FROM {table}").fetchone()[0]
            if pk
            else None
        )
        dcol = {"daily_exchange_rates": "date"}.get(
            table, "process_date" if table in FACTS else None
        )
        rng = (
            con.sql(
                f"SELECT min({dcol})::VARCHAR || ' → ' || max({dcol})::VARCHAR FROM {table}"
            ).fetchone()[0]
            if dcol
            else ""
        )
        rows.append(
            {
                "table": table,
                "rows": n,
                "documented": documented,
                "diff_%": round(100 * (n - documented) / documented, 1),
                "dup_pk": dup,
                "dup_%": round(100 * dup / n, 2) if dup is not None else None,
                "process_date_range": rng,
            }
        )
    import pandas as pd

    section(
        "Row counts, duplicate primary keys, date range",
        pd.DataFrame(rows),
        "`documented` comes from the dataset summary PDF; `dup_pk` = rows − distinct primary keys.",
    )

    # 2. Null rates ------------------------------------------------------------
    for table in [*FACTS, *DIMS]:
        if table == "call_transcripts":
            continue  # long free text, profiled separately if needed
        cols = [r[0] for r in con.sql(f"DESCRIBE {table}").fetchall()]
        sel = ", ".join(f'round(100*avg(({c} IS NULL)::INT),1) AS "{c}"' for c in cols)
        df = con.sql(f"SELECT {sel} FROM {table}").df().T.reset_index()
        df.columns = ["column", "null_%"]
        df = df[df["null_%"] > 0].sort_values("null_%", ascending=False)
        section(f"Nulls – {table}", df, "Only columns with nulls.")

    # 3. Referential integrity --------------------------------------------------
    fk_rows = []
    for child, col, parent, pkey in FKS:
        orphans, total = con.sql(f"""
            SELECT count(*) FILTER (WHERE p.{pkey} IS NULL), count(*)
            FROM {child} c LEFT JOIN (SELECT DISTINCT {pkey} FROM {parent}) p ON c.{col} = p.{pkey}
            WHERE c.{col} IS NOT NULL""").fetchone()
        fk_rows.append(
            {
                "child": f"{child}.{col}",
                "parent": f"{parent}.{pkey}",
                "orphans": orphans,
                "orphan_%": round(100 * orphans / total, 3),
            }
        )
    section("Referential integrity", pd.DataFrame(fk_rows))

    # 4. Categorical distributions ---------------------------------------------
    cats = [
        ("customers", "country"),
        ("customers", "segment"),
        ("customers", "customer_status"),
        ("customers", "detected_accent"),
        ("customers", "document_type"),
        ("products", "product_type"),
        ("products", "currency"),
        ("products", "product_status"),
        ("transactions", "transaction_type"),
        ("transactions", "channel"),
        ("transactions", "currency"),
        ("transactions", "transaction_country"),
        ("transactions", "transaction_status"),
        ("transactions", "response_code"),
        ("transactions", "merchant_category"),
        ("digital_events", "event_type"),
        ("digital_events", "channel"),
        ("call_center_interactions", "interaction_type"),
        ("call_center_interactions", "reason_category"),
        ("call_center_interactions", "detected_sentiment"),
        ("campaign_sends", "send_channel"),
        ("campaign_sends", "send_status"),
        ("complaints", "category"),
        ("complaints", "status"),
        ("complaints", "priority"),
        ("satisfaction_surveys", "survey_type"),
        ("satisfaction_surveys", "nps_category"),
        ("call_transcripts", "detected_accent"),
        ("call_transcripts", "detected_language"),
    ]
    for table, col in cats:
        df = con.sql(f"""SELECT {col} AS value, count(*) AS n,
                         round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
                         FROM {table} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 15""").df()
        section(f"Distribution – {table}.{col}", df)

    # 5. Numeric summaries ------------------------------------------------------
    nums = [
        ("transactions", "amount_usd"),
        ("transactions", "fraud_score"),
        ("customers", "credit_score"),
        ("customers", "estimated_monthly_income"),
        ("products", "current_balance"),
        ("call_center_interactions", "duration_seconds"),
        ("call_center_interactions", "wait_time_seconds"),
        ("satisfaction_surveys", "main_score"),
        ("complaints", "resolution_days"),
    ]
    rows = []
    for table, col in nums:
        r = con.sql(f"""SELECT min({col}), quantile_cont({col},0.01), quantile_cont({col},0.5),
                        avg({col}), quantile_cont({col},0.99), max({col}) FROM {table}""").fetchone()
        rows.append(
            dict(
                zip(
                    ["min", "p01", "median", "mean", "p99", "max"],
                    [round(x, 2) if x is not None else None for x in r],
                ),
                column=f"{table}.{col}",
            )
        )
    section(
        "Numeric summaries",
        pd.DataFrame(rows)[["column", "min", "p01", "median", "mean", "p99", "max"]],
    )

    # 6. Fraud -----------------------------------------------------------------
    section(
        "Fraud by transaction type / channel",
        con.sql("""
        SELECT transaction_type, channel, count(*) n, sum(is_fraud::INT) fraud,
               round(100.0*avg(is_fraud::INT),3) fraud_pct, round(avg(fraud_score),1) avg_score
        FROM transactions GROUP BY 1,2 ORDER BY fraud DESC, n DESC, 1, 2 LIMIT 15""").df(),
    )

    # 7. Marketing funnel ------------------------------------------------------
    section(
        "Campaign funnel by channel",
        con.sql("""
        SELECT send_channel, count(*) sends,
               round(100*avg(was_delivered::INT),1) delivered_pct,
               round(100*avg(was_opened::INT),1) opened_pct,
               round(100*avg(was_clicked::INT),1) clicked_pct,
               round(100*avg(had_conversion::INT),2) conv_pct,
               round(sum(send_cost),0) AS total_cost
        FROM campaign_sends GROUP BY 1 ORDER BY 2 DESC, 1""").df(),
    )

    # 8. Contact center -------------------------------------------------------
    section(
        "Resolution & sentiment by reason",
        con.sql("""
        SELECT reason_category, count(*) n, round(100*avg(was_resolved::INT),1) resolved_pct,
               round(avg(sentiment_score),2) avg_sentiment, round(avg(duration_seconds)) avg_dur_s
        FROM call_center_interactions GROUP BY 1 ORDER BY 2 DESC, 1""").df(),
    )

    # 9. Figures ---------------------------------------------------------------
    ts = {
        t: con.sql(
            f"SELECT date_trunc('month', process_date) m, count(*) n FROM {t} GROUP BY 1 ORDER BY 1"
        ).df()
        for t in FACTS
        if t != "call_transcripts"
    }
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), sharex=True)
    for ax, (t, df) in zip(axes.flat, ts.items()):
        ax.plot(df["m"], df["n"])
        ax.set_title(t)
        ax.set_ylim(bottom=0)
    fig.suptitle("Monthly record counts by process_date")
    fig.tight_layout()
    fig.savefig(FIGS / "monthly_volumes.png", dpi=120)
    plt.close(fig)

    amt = con.sql(
        "SELECT amount_usd FROM transactions ORDER BY hash(transaction_id, 0) LIMIT 500000"
    ).df()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(amt["amount_usd"], bins=80)
    ax.set_yscale("log")
    ax.set_title("transactions.amount_usd (500k sample, log y)")
    ax.set_xlabel("USD")
    fig.tight_layout()
    fig.savefig(FIGS / "amount_usd_hist.png", dpi=120)
    plt.close(fig)

    cs = con.sql("SELECT credit_score, segment FROM customers WHERE credit_score IS NOT NULL").df()
    fig, ax = plt.subplots(figsize=(7, 4))
    for seg, g in cs.groupby("segment"):
        ax.hist(g["credit_score"], bins=40, alpha=0.5, label=seg)
    ax.legend()
    ax.set_title("customers.credit_score by segment")
    fig.tight_layout()
    fig.savefig(FIGS / "credit_score_by_segment.png", dpi=120)
    plt.close(fig)

    out.append(
        "\n## Figures\n\n![monthly volumes](figures/monthly_volumes.png)\n\n"
        "![amount_usd](figures/amount_usd_hist.png)\n\n"
        "![credit score](figures/credit_score_by_segment.png)\n"
    )
    (REPORTS / "eda_overview.md").write_text("\n".join(out))
    console.print(f"\n[bold green]Report written to {REPORTS / 'eda_overview.md'}[/]")


if __name__ == "__main__":
    main()
