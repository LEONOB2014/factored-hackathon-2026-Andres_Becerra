"""Single source of truth for platform paths, tables and the demo data split.

Every component (Airflow DAGs, dbt vars, stream replayer, ML pipelines) reads these values so the
historical / stream-holdout boundary is defined exactly once.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(os.environ.get("LATAM_REPO_ROOT", Path(__file__).resolve().parents[3]))
DATA = Path(os.environ.get("LATAM_DATA_DIR", REPO_ROOT / "data"))

LANDING = DATA / "raw"  # as received from S3, never modified
LAKE = DATA / "lake"
BRONZE = LAKE / "bronze"  # typed, partitioned, append-only
HOLDOUT = LAKE / "holdout"  # post-cutoff facts, replayed or batch-loaded later
QUARANTINE = LAKE / "quarantine"  # rejected rows and the untrusted backup folder
MANIFESTS = LAKE / "manifests"  # landing + bronze partition manifests
LAKEHOUSE_DB = LAKE / "lakehouse.duckdb"  # dbt dev target (silver/gold/features/graph)

# Demo split (see docs/platform/03_data_split.md). Facts with process_date >= STREAM_CUTOFF are held out.
STREAM_CUTOFF = date.fromisoformat(os.environ.get("LATAM_STREAM_CUTOFF", "2026-05-18"))
DATA_END = date(2026, 6, 17)


@dataclass(frozen=True)
class Table:
    name: str
    pk: tuple[str, ...]
    kind: str  # fact | dimension | reference
    event_ts: str | None = None  # business timestamp column (facts)
    streamed: bool = False  # replayed through Redpanda in the demo


TABLES: dict[str, Table] = {
    t.name: t
    for t in [
        Table("transactions", ("transaction_id",), "fact", "transaction_date", streamed=True),
        Table("digital_events", ("event_id",), "fact", "event_date", streamed=True),
        Table("call_center_interactions", ("interaction_id",), "fact", "interaction_date"),
        Table("call_transcripts", ("transcript_id",), "fact"),
        Table("satisfaction_surveys", ("survey_id",), "fact", "survey_date"),
        Table("complaints", ("complaint_id",), "fact", "creation_date"),
        Table("campaign_sends", ("send_id",), "fact", "send_date"),
        Table("customers", ("customer_id",), "dimension"),
        Table("products", ("product_id",), "dimension"),
        Table("branches", ("branch_id",), "dimension"),
        Table("service_agents", ("agent_id",), "dimension"),
        Table("marketing_campaigns", ("campaign_id",), "dimension"),
        Table("daily_exchange_rates", ("date", "source_currency", "target_currency"), "reference"),
    ]
}

SOURCES = {
    "main": LANDING / "data",
    "backup_20260831": LANDING / "data_backup_20260831",  # quarantined: audit reconciliation only
}


def raw_glob(source: str, table: Table) -> str:
    base = SOURCES[source]
    return (
        f"{base}/{table.name}/*/*/*/*.csv" if table.kind == "fact" else f"{base}/{table.name}.csv"
    )
