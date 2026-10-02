"""DuckDB access to the main and backup Parquet copies of the dataset."""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "data" / "parquet"
BACKUP = ROOT / "data" / "parquet_backup"
DERIVED = ROOT / "data" / "derived"
DERIVED.mkdir(parents=True, exist_ok=True)

FACTS = [
    "transactions",
    "digital_events",
    "call_center_interactions",
    "call_transcripts",
    "campaign_sends",
    "complaints",
    "satisfaction_surveys",
]
DIMS = [
    "customers",
    "products",
    "branches",
    "service_agents",
    "marketing_campaigns",
    "daily_exchange_rates",
]
PK = {
    "customers": "customer_id",
    "products": "product_id",
    "branches": "branch_id",
    "service_agents": "agent_id",
    "marketing_campaigns": "campaign_id",
    "transactions": "transaction_id",
    "digital_events": "event_id",
    "call_center_interactions": "interaction_id",
    "call_transcripts": "transcript_id",
    "campaign_sends": "send_id",
    "complaints": "complaint_id",
    "satisfaction_surveys": "survey_id",
}


def connect() -> duckdb.DuckDBPyConnection:
    """Connection with views `m_<table>` (main) and `b_<table>` (backup)."""
    con = duckdb.connect()
    con.sql("SET threads TO 8")
    for prefix, base in (("m", MAIN), ("b", BACKUP)):
        for f in sorted(base.glob("*.parquet")):
            con.sql(f"CREATE VIEW {prefix}_{f.stem} AS SELECT * FROM '{f}'")
    return con
