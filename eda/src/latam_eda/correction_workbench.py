"""Correction workbench helpers (notebook model_risk/02): explore flagged cells and write correction proposals.

The workbench only **proposes**. A proposal is a JSON file in data/lake/corrections/proposals/; the
`dq_correction_review` DAG validates it against the source contracts and lossless bronze, an approver who is not
the proposer decides in Airflow, and only then does silver change (docs/platform/09 §D). Nothing here writes to the
lakehouse.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

PROPOSAL_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


def connect(lakehouse: Path) -> duckdb.DuckDBPyConnection:
    """Read-only: the workbench never writes to the lakehouse (and must not block an Airflow dbt run for long)."""
    return duckdb.connect(str(lakehouse), read_only=True)


def pattern_groups(con, min_cells: int = 1) -> pd.DataFrame:
    """Findings grouped by (table, column, code, value): the candidates for a pattern correction.

    `pii` marks values shown only as a shape: those columns can be corrected cell by cell, not by pattern."""
    return con.sql(f"""
        SELECT table_name, column_name, issue_code, raw_value,
               count(*)                                              AS cells,
               count(DISTINCT zone || source_file || record_no)      AS records,
               count(DISTINCT partition_date)                        AS partitions,
               min(partition_date)                                   AS first_partition,
               max(partition_date)                                   AS last_partition,
               count(correction_proposal_id)                         AS already_corrected,
               starts_with(coalesce(raw_value, ''), 'shape:')        AS pii
        FROM audit.dq_cell_findings
        GROUP BY ALL
        HAVING count(*) >= {int(min_cells)}
        ORDER BY cells DESC, table_name, column_name, raw_value""").df()


def records(con, table: str, column: str, value: str, limit: int = 20) -> pd.DataFrame:
    """Lineage of the flagged cells holding `value`: where each one is in lossless bronze."""
    return con.execute(
        """SELECT zone, partition_date, source_file, record_no, entity_id, issue_code, correction_proposal_id
           FROM audit.dq_cell_findings WHERE table_name = ? AND column_name = ? AND raw_value = ?
           ORDER BY partition_date, source_file, record_no LIMIT ?""",
        [table, column, value, limit],
    ).df()


def holds(con) -> pd.DataFrame:
    return con.sql(
        "SELECT * FROM audit.dq_partition_holds ORDER BY table_name, partition_date"
    ).df()


def downstream(manifest: Path, table: str) -> list[str]:
    """Consumer models (gold, features, graph, serving, privacy) fed by the typed model of `table`."""
    if not manifest.exists():
        return []
    children = json.loads(manifest.read_text()).get("child_map", {})
    todo = [f"model.latam_lakehouse.typed_{table}", f"model.latam_lakehouse.typed_{table}_holdout"]
    seen: set[str] = set()
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in seen:
                seen.add(child)
                todo.append(child)
    keep = ("dim_", "fct_", "mart_", "serving_", "feat_", "graph_", "privacy_")
    return sorted(
        n.split(".")[-1]
        for n in seen
        if n.startswith("model.") and n.split(".")[-1].startswith(keep)
    )


# --------------------------------------------------------------------------------------------- proposals
def _base(proposal_id: str, kind: str, reason: str) -> dict:
    if not PROPOSAL_ID.match(proposal_id):
        raise ValueError("proposal_id: lowercase letters, digits and '-', 3 to 80 characters")
    if not reason.strip():
        raise ValueError("a proposal needs a reason: it is what the approver reads first")
    return {"proposal_id": proposal_id, "kind": kind, "reason": reason.strip()}


def pattern_proposal(proposal_id: str, table: str, column: str, from_value: str, to_value: str, reason: str,
                     zones: list[str] | None = None, partitions: list[str] | None = None) -> dict:  # fmt: skip
    if from_value == to_value:
        raise ValueError("from_value and to_value are equal")
    if from_value.startswith("shape:"):
        raise ValueError(
            "personal data is shown only as a shape: correct it cell by cell, not by pattern"
        )
    pattern = {"table": table, "column": column, "from_value": from_value, "to_value": to_value}
    if zones:
        pattern["zones"] = zones
    if partitions:
        pattern["partitions"] = [str(p) for p in partitions]
    return {**_base(proposal_id, "pattern", reason), "pattern": pattern}


def cells_proposal(proposal_id: str, cells: list[dict], reason: str) -> dict:
    need = {"zone", "table", "source_file", "record_no", "column", "old_value", "new_value"}
    for c in cells:
        if missing := need - set(c):
            raise ValueError(f"cell is missing {sorted(missing)}")
    if not cells:
        raise ValueError("no cells")
    return {**_base(proposal_id, "cells", reason), "cells": cells}


def revert_proposal(proposal_id: str, proposal_ids: list[str], reason: str) -> dict:
    if not proposal_ids:
        raise ValueError("name the applied proposals to revert")
    return {**_base(proposal_id, "revert", reason), "revert": {"proposal_ids": list(proposal_ids)}}


def release_proposal(proposal_id: str, table: str, partition_date: str, reason: str) -> dict:
    return {
        **_base(proposal_id, "release", reason),
        "release": {"table": table, "partition_date": str(partition_date)},
    }


def write_proposal(proposal: dict, proposals_dir: Path) -> Path:
    """Write the proposal file; never overwrites (a reviewed proposal must not change under the approver)."""
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / f"{proposal['proposal_id']}.json"
    if path.exists():
        raise FileExistsError(f"{path.name} exists: choose a new proposal_id")
    path.write_text(json.dumps(proposal, indent=1, ensure_ascii=False) + "\n")
    return path


def next_step(proposal_id: str) -> str:
    return (
        f"Proposal written. Next: in Airflow (http://127.0.0.1:8080), log in as **steward**, open "
        f"`dq_correction_review`, choose *Trigger* and set `proposal_id` = `{proposal_id}`. The run validates it; "
        f"then **approver** (not you) approves or rejects it under *Required actions*."
    )
