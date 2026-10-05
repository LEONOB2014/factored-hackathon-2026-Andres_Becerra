"""Export the copilot's demo snapshot from the lakehouse's card serving table.

A stratified sample of customers (every next-best-action class, single- and multi-card holders), with all their cards.
Identifiers and card facts only: no names, documents, contact data or transactions. The snapshot is data, so it lives
under the git-ignored data/ folder and is uploaded to the deploy volume, never committed.

    cd copilot && uv run python scripts/export_snapshot.py            # data/copilot/snapshot.duckdb
    LATAM_DUCKDB_PATH=... COPILOT_SNAPSHOT=... uv run python scripts/export_snapshot.py
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
LAKEHOUSE = Path(os.environ.get("LATAM_DUCKDB_PATH", REPO / "data" / "lake" / "lakehouse.duckdb"))
OUT = Path(os.environ.get("COPILOT_SNAPSHOT", REPO / "data" / "copilot" / "snapshot.duckdb"))
PER_STRATUM = 40
CURRENCY = {"MX": "MXN", "CO": "COP", "AR": "ARS"}

# The serving contract carries the card facts and the rule-based next best action. It does not carry the confirmed
# fraud signal, which the copilot's policy needs to refuse a self-service unblock, so it is joined from the mart.
CARDS = """
select s.*, coalesce(m.confirmed_fraud_365d, 0) as confirmed_fraud_365d
from serving.serving_card_support s
left join gold.mart_card_support m using (product_id)
"""

STRATA = {
    # one card with each next best action, plus multi-card holders and quiet single-card holders
    **{
        nba: f"select customer_id from src_cards where next_best_action = '{nba}'"
        for nba in (
            "FRAUD_REVIEW_AND_BLOCK",
            "REISSUE_CARD",
            "PROACTIVE_RENEWAL",
            "EXPLAIN_LIMIT_OR_OFFER_INCREASE_REVIEW",
            "UNBLOCK_AFTER_STRONG_AUTH",
        )
    },
    "blocked_with_fraud": "select customer_id from src_cards where is_blocked and confirmed_fraud_365d > 0",
    "multi_card": "select customer_id from src_cards group by 1 having count(*) >= 2",
    "single_card_quiet": "select customer_id from src_cards group by 1 having count(*) = 1 and bool_and(next_best_action = 'NONE')",
}


def last4(product_id: str) -> str:
    """A stable synthetic display suffix: the dataset has no card numbers, and a suffix is how customers name a card."""
    return f"{int(hashlib.sha256(product_id.encode()).hexdigest(), 16) % 10000:04d}"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    con = duckdb.connect(str(OUT))
    con.sql(f"attach '{LAKEHOUSE}' as lh (read_only)")
    con.sql("use lh")
    con.sql(f"create temp table src_cards as {CARDS}")
    as_of = str(con.sql("select max(as_of_ts) from serving.serving_card_support").fetchone()[0])
    picked: dict[str, str] = {}
    for stratum, sql in STRATA.items():
        rows = con.sql(
            f"select distinct customer_id from ({sql}) order by hash(customer_id) limit {PER_STRATUM}"
        ).fetchall()
        for (cid,) in rows:
            picked.setdefault(cid, stratum)
    con.sql("use snapshot")
    con.sql("create temp table picked(customer_id varchar, stratum varchar)")
    con.executemany("insert into picked values (?, ?)", list(picked.items()))
    pairs = con.sql(
        "select product_id, customer_id from temp.src_cards join picked using (customer_id) order by 2, 1"
    ).fetchall()
    seen: dict[str, set[str]] = {}
    suffix = []
    for pid, cid in pairs:
        s, bump = last4(pid), 0
        while s in seen.setdefault(
            cid, set()
        ):  # unique within the customer, so a suffix names one card
            bump += 1
            s = last4(f"{pid}:{bump}")
        seen[cid].add(s)
        suffix.append((pid, s))
    con.sql("create temp table suffix(product_id varchar, card_last4 varchar)")
    con.executemany("insert into suffix values (?, ?)", suffix)
    currency = " ".join(f"when '{k}' then '{v}'" for k, v in CURRENCY.items())
    con.sql("use snapshot")
    con.sql(f"""create table cards as
        select c.*, s.card_last4, case c.country_code {currency} end as currency, p.stratum
        from temp.src_cards c join temp.picked p using (customer_id) join temp.suffix s using (product_id)
        order by customer_id, product_id""")
    n_cards = con.sql("select count(*) from cards").fetchone()[0]
    con.sql(
        "create table meta as select ? as as_of, ? as exported_at, ? as source, ? as customers, ? as cards",
        params=[
            as_of,
            datetime.now(UTC).isoformat(),
            "serving.serving_card_support",
            len(picked),
            n_cards,
        ],
    )
    print(
        con.sql(
            "select stratum, count(distinct customer_id) customers, count(*) cards from cards group by 1 order by 1"
        )
    )
    con.sql("detach lh")
    con.close()
    print(f"wrote {OUT} ({len(picked)} customers, {n_cards} cards, as of {as_of})")


if __name__ == "__main__":
    main()
