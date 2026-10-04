"""Four-eyes correction and restore of flagged cells (docs/platform/09 §D).

Bronze is never touched. A steward writes a **proposal** (JSON, usually from the correction workbench), the
`dq_correction_review` DAG validates and stages it, an approver who is not the proposer decides in Airflow, and an
approved proposal becomes one **write-once, read-only** file in the correction log. Silver overlays the log on
lossless bronze (dbt `dq_corrections_active`), so a revert, itself a proposal, restores the original value, and
silver can be rebuilt as of any point of the log.

Proposal kinds (every proposal has `proposal_id`, `kind`, `reason`):
* `pattern`: {table, column, from_value, to_value, zones?, partitions?}: every cell holding `from_value`;
* `cells`:   [{zone, table, source_file, record_no, column, old_value, new_value}];
* `revert`:  {proposal_ids: [...]}: undo applied corrections or releases (a released partition is held again);
* `release`: {table, partition_date}: release a partition held by the schema-drift circuit breaker.

Layout under data/lake/corrections: `proposals/<id>.json` (input), `staged/<id>.parquet` (validated, awaiting a
decision), `applied/<id>.parquet` (the log; `_genesis.parquet` keeps it non-empty for readers). Expansion and
staging run in DuckDB: a pattern can touch a million cells.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import stat
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import duckdb

from latam_platform import config

PROPOSAL_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
KINDS = ("pattern", "cells", "revert", "release")
CELL_KINDS = ("pattern", "cells")
# The correction log: one schema for every kind (unused columns are NULL).
LOG_COLUMNS = {
    "proposal_id": "VARCHAR",
    "kind": "VARCHAR",
    "seq": "BIGINT",
    "zone": "VARCHAR",
    "table_name": "VARCHAR",
    "source_file": "VARCHAR",
    "record_no": "BIGINT",
    "column_name": "VARCHAR",
    "old_value": "VARCHAR",
    "new_value": "VARCHAR",
    "partition_date": "DATE",
    "reverts_proposal_id": "VARCHAR",
    "reason": "VARCHAR",
    "proposal_sha256": "VARCHAR",
    "proposed_by": "VARCHAR",
    "approved_by": "VARCHAR",
    "approval_comment": "VARCHAR",
    "applied_at": "TIMESTAMP",
}
ENTRY_COLUMNS = ["zone", "table_name", "source_file", "record_no", "column_name", "old_value", "new_value",
                 "partition_date", "reverts_proposal_id"]  # fmt: skip
ZONE_DIR = {"bronze": "BRONZE_RAW", "holdout": "HOLDOUT_RAW"}
NO_WRITE = ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


class CorrectionError(ValueError):
    """A proposal that must not be applied (invalid, stale, already applied, or four-eyes violated)."""


# ---------------------------------------------------------------------------------------------- paths and log
def root() -> Path:
    return config.LAKE / "corrections"


def ensure_log() -> Path:
    """Create the correction folders and the empty, typed genesis file that readers need."""
    for d in ("proposals", "staged", "applied"):
        (root() / d).mkdir(parents=True, exist_ok=True)
    genesis = root() / "applied" / "_genesis.parquet"
    if not genesis.exists():
        cols = ", ".join(f"CAST(NULL AS {t}) AS {c}" for c, t in LOG_COLUMNS.items())
        duckdb.connect().execute(f"COPY (SELECT {cols} LIMIT 0) TO '{genesis}' (FORMAT parquet)")
    return genesis


def log_sql() -> str:
    ensure_log()
    return f"read_parquet('{root()}/applied/*.parquet', union_by_name = true)"


# ------------------------------------------------------------------------------------------------- contracts
@cache
def _generator():
    path = config.REPO_ROOT / "platform" / "dbt" / "scripts" / "generate_silver_from_contracts.py"
    spec = importlib.util.spec_from_file_location("generate_silver_from_contracts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def contract(table: str) -> dict:
    contracts = _generator().load_contracts()
    if table not in contracts:
        raise CorrectionError(f"unknown table {table!r}")
    return contracts[table]


def column_spec(table: str, column: str) -> dict:
    spec = contract(table)["columns"].get(column)
    if spec is None:
        raise CorrectionError(f"{table}.{column} is not in the source contract")
    return spec


def zones_for(table: str) -> list[str]:
    gen = _generator()
    return [gen.ZONE_NAME[z] for z in gen.ZONES if table in gen.tables(z, gen.load_contracts())]


def value_breaches(table: str, column: str, values: list[str]) -> dict[str, list[str]]:
    """{value: [issue codes]} for values that would break the column's source contract, with the very predicates
    the typed models use (generator `checks`), so a correction can never introduce a new breach."""
    checks = _generator().checks(column, column_spec(table, column), _generator().value_classes())
    if not checks or not values:
        return {}
    con = duckdb.connect()
    con.execute(f"CREATE TABLE r ({_q(column)} VARCHAR)")
    con.executemany("INSERT INTO r VALUES (?)", [[v] for v in values])
    arms = ", ".join(f"CASE WHEN {cond} THEN '{code}' END" for code, cond in checks)
    rows = con.sql(
        f"SELECT {_q(column)}, list_filter([{arms}], x -> x IS NOT NULL) FROM r"
    ).fetchall()
    return {v: codes for v, codes in rows if codes}


# ----------------------------------------------------------------------------------------------- proposals
def _q(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def _zone_dir(zone: str, table: str) -> Path:
    return getattr(config, ZONE_DIR[zone]) / table


def _bronze(zone: str, table: str) -> str:
    return f"read_parquet('{_zone_dir(zone, table)}/*/*.parquet', union_by_name = true, hive_partitioning = false)"


def load_proposal(proposal_id: str) -> tuple[dict, str]:
    if not PROPOSAL_ID.match(proposal_id or ""):
        raise CorrectionError(
            f"invalid proposal id {proposal_id!r} (lowercase letters, digits and '-')"
        )
    path = root() / "proposals" / f"{proposal_id}.json"
    if not path.exists():
        raise CorrectionError(f"proposal file not found: {path.relative_to(config.DATA)}")
    raw = path.read_bytes()
    proposal = json.loads(raw)
    if proposal.get("proposal_id") != proposal_id:
        raise CorrectionError("proposal_id in the file does not match its name")
    if proposal.get("kind") not in KINDS:
        raise CorrectionError(f"kind must be one of {KINDS}")
    if not str(proposal.get("reason", "")).strip():
        raise CorrectionError("a proposal needs a reason")
    return proposal, hashlib.sha256(raw).hexdigest()


def _entries_table(con) -> None:
    types = {c: LOG_COLUMNS[c] for c in ENTRY_COLUMNS}
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE entries ({', '.join(f'{c} {t}' for c, t in types.items())})"
    )


def _expand_pattern(con, p: dict) -> None:
    table, column = p["table"], p["column"]
    if column_spec(table, column).get("pii"):
        raise CorrectionError(
            f"{table}.{column} is personal data: correct it cell by cell, not by pattern"
        )
    if p["from_value"] == p["to_value"]:
        raise CorrectionError("from_value and to_value are equal")
    zones = p.get("zones") or zones_for(table)
    if bad := set(zones) - set(zones_for(table)):
        raise CorrectionError(f"zones {sorted(bad)} are not typed into silver for {table}")
    parts = [str(d) for d in p.get("partitions") or []]
    for zone in zones:
        if not any(_zone_dir(zone, table).glob("*/*.parquet")):
            continue  # nothing landed in this zone yet
        where = f"{_q(column)} = $from"
        if parts:
            where += (
                f" AND cast(_partition_date AS date) IN ({', '.join(f'DATE {d!r}' for d in parts)})"
            )
        con.execute(
            f"""INSERT INTO entries (zone, table_name, source_file, record_no, column_name, old_value, new_value,
                                     partition_date)
                SELECT '{zone}', '{table}', _source_file, _record_no, '{column}', {_q(column)}, $to,
                       cast(_partition_date AS date)
                FROM {_bronze(zone, table)} WHERE {where}""",
            {"from": p["from_value"], "to": p["to_value"]},
        )


def _expand_cells(con, cells: list[dict]) -> None:
    if not cells:
        raise CorrectionError("a cells proposal needs at least one cell")
    stale = []
    for c in cells:
        column_spec(c["table"], c["column"])
        if c["zone"] not in zones_for(c["table"]):
            raise CorrectionError(f"zone {c['zone']!r} is not typed into silver for {c['table']}")
        if not any(_zone_dir(c["zone"], c["table"]).glob("*/*.parquet")):
            raise CorrectionError(f"no lossless bronze for {c['table']} in zone {c['zone']!r}")
        row = con.execute(
            f"SELECT {_q(c['column'])}, cast(_partition_date AS date) FROM {_bronze(c['zone'], c['table'])} "
            "WHERE _source_file = ? AND _record_no = ?",
            [c["source_file"], int(c["record_no"])],
        ).fetchone()
        if row is None:
            raise CorrectionError(
                f"no bronze record {c['source_file']}#{c['record_no']} in {c['table']}"
            )
        if row[0] != c["old_value"]:
            stale.append(f"{c['source_file']}#{c['record_no']}.{c['column']}")
            continue
        con.execute(
            "INSERT INTO entries (zone, table_name, source_file, record_no, column_name, old_value, new_value, "
            "partition_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                c["zone"],
                c["table"],
                c["source_file"],
                int(c["record_no"]),
                c["column"],
                row[0],
                c["new_value"],
                row[1],
            ],
        )
    if stale:
        raise CorrectionError(
            f"old_value does not match lossless bronze for {stale[:5]} (stale proposal?)"
        )


def applied_state(con) -> dict[str, dict]:
    """{proposal_id: {kind, reverted}} of the correction log."""
    rows = con.sql(f"""
        SELECT proposal_id, any_value(kind),
               bool_or(proposal_id IN (SELECT reverts_proposal_id FROM {log_sql()}
                                       WHERE reverts_proposal_id IS NOT NULL))
        FROM {log_sql()} WHERE proposal_id IS NOT NULL GROUP BY 1""").fetchall()
    return {pid: {"kind": kind, "reverted": reverted} for pid, kind, reverted in rows}


def validate(proposal: dict, lakehouse=None) -> duckdb.DuckDBPyConnection:
    """Check a proposal and expand it into the TEMP table `entries` of the returned connection.

    Raises CorrectionError for anything that must not reach an approver."""
    con = duckdb.connect()
    _entries_table(con)
    kind = proposal["kind"]
    applied = applied_state(con)
    if proposal["proposal_id"] in applied:
        raise CorrectionError("this proposal was already applied: proposals are write-once")
    if kind == "pattern":
        _expand_pattern(con, proposal["pattern"])
    elif kind == "cells":
        _expand_cells(con, proposal["cells"])
    elif kind == "revert":
        ids = proposal["revert"]["proposal_ids"]
        if not ids:
            raise CorrectionError("a revert needs proposal_ids")
        for pid in ids:
            info = applied.get(pid)
            if info is None or info["kind"] == "revert":
                raise CorrectionError(f"{pid} is not an applied correction or release")
            if info["reverted"]:
                raise CorrectionError(f"{pid} is already reverted")
            con.execute("INSERT INTO entries (reverts_proposal_id) VALUES (?)", [pid])
    else:
        table, day = proposal["release"]["table"], str(proposal["release"]["partition_date"])
        contract(table)
        if (
            lakehouse is not None
            and not lakehouse.execute(
                "SELECT count(*) FROM audit.dq_partition_holds WHERE table_name = ? AND partition_date = ?::DATE",
                [table, day],
            ).fetchone()[0]
        ):
            raise CorrectionError(f"{table} {day} is not held")
        con.execute(
            "INSERT INTO entries (table_name, partition_date) VALUES (?, ?::DATE)", [table, day]
        )
    n = con.sql("SELECT count(*) FROM entries").fetchone()[0]
    if n == 0:
        raise CorrectionError("the pattern matches no cell in lossless bronze")
    if kind in CELL_KINDS:
        dup = con.sql("""SELECT count(*) FROM (SELECT 1 FROM entries
                         GROUP BY zone, table_name, source_file, record_no, column_name HAVING count(*) > 1)""").fetchone()[
            0
        ]
        if dup:
            raise CorrectionError(f"{dup} cell(s) appear more than once in the proposal")
        for table, column, values in con.sql(
            "SELECT table_name, column_name, list(DISTINCT new_value ORDER BY new_value) FROM entries GROUP BY ALL"
        ).fetchall():
            if breaches := value_breaches(table, column, values):
                raise CorrectionError(f"new values break the {table}.{column} contract: {breaches}")
    return con


def impact(con, kind: str, staged: Path | None = None, lakehouse=None) -> dict:
    out: dict = {"kind": kind, "entries": con.sql("SELECT count(*) FROM entries").fetchone()[0]}
    if kind not in CELL_KINDS:
        return out
    cells, records, partitions = con.sql(
        "SELECT count(*), count(DISTINCT (zone, source_file, record_no)), count(DISTINCT (zone, partition_date)) "
        "FROM entries"
    ).fetchone()
    out |= {
        "cells": cells,
        "records": records,
        "partitions": partitions,
        "columns": [
            r[0]
            for r in con.sql(
                "SELECT DISTINCT table_name || '.' || column_name FROM entries ORDER BY 1"
            ).fetchall()
        ],
        "zones": [r[0] for r in con.sql("SELECT DISTINCT zone FROM entries ORDER BY 1").fetchall()],
        "examples": [
            {"from": o, "to": n, "cells": k}
            for o, n, k in con.sql(
                "SELECT old_value, new_value, count(*) FROM entries GROUP BY ALL ORDER BY 3 DESC, 1 LIMIT 5"
            ).fetchall()
        ],
    }
    if lakehouse is not None and staged is not None:  # the findings these cells carry today
        out["findings_resolved"] = dict(
            lakehouse.execute(
                f"""SELECT f.issue_code, count(*) FROM audit.dq_cell_findings f
                    JOIN read_parquet('{staged}') s USING (zone, table_name, source_file, record_no, column_name)
                    GROUP BY 1 ORDER BY 1"""
            ).fetchall()
        )
    out["downstream_models"] = downstream(
        [r[0] for r in con.sql("SELECT DISTINCT table_name FROM entries ORDER BY 1").fetchall()]
    )
    return out


def downstream(tables: list[str]) -> list[str]:
    """Gold, feature, graph, serving and privacy models fed by the typed models of these tables (dbt manifest)."""
    for name in ("target-airflow", "target"):
        path = config.REPO_ROOT / "platform" / "dbt" / name / "manifest.json"
        if path.exists():
            break
    else:
        return []
    children = json.loads(path.read_text()).get("child_map", {})
    todo = [f"model.latam_lakehouse.typed_{t}{s}" for t in tables for s in ("", "_holdout")]
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


# --------------------------------------------------------------------------------------------- stage, apply
def stage(proposal_id: str, proposed_by: str, lakehouse=None) -> dict:
    """Validate a proposal and stage its entries for review. Returns the summary shown to the approver."""
    ensure_log()
    proposal, sha = load_proposal(proposal_id)
    con = validate(proposal, lakehouse)
    staged = root() / "staged" / f"{proposal_id}.parquet"
    tmp = staged.with_suffix(".tmp")
    fixed = {"proposal_id": proposal_id, "kind": proposal["kind"], "reason": proposal["reason"],
             "proposal_sha256": sha, "proposed_by": proposed_by}  # fmt: skip
    cols, params = [], []
    for c, t in LOG_COLUMNS.items():
        if c in ENTRY_COLUMNS:
            cols.append(c)
        elif c == "seq":
            cols.append("row_number() OVER (ORDER BY zone, table_name, source_file, record_no, column_name, "
                        "partition_date, reverts_proposal_id) AS seq")  # fmt: skip
        else:  # proposal-level values; the approval columns stay NULL until apply()
            cols.append(f"CAST(? AS {t}) AS {c}")
            params.append(fixed.get(c))
    con.execute(
        f"COPY (SELECT {', '.join(cols)} FROM entries ORDER BY seq) TO '{tmp}' (FORMAT parquet)",
        params,
    )
    tmp.rename(staged)
    return {"proposal_id": proposal_id, "proposal_sha256": sha, "proposed_by": proposed_by,
            "reason": proposal["reason"], **impact(con, proposal["kind"], staged, lakehouse)}  # fmt: skip


def four_eyes(proposed_by: str, approved_by: str) -> None:
    if not approved_by or approved_by.strip().lower() == (proposed_by or "").strip().lower():
        raise CorrectionError(
            f"four-eyes violated: {approved_by!r} cannot approve a proposal by {proposed_by!r}"
        )


def apply(proposal_id: str, proposed_by: str, approved_by: str, comment: str) -> dict:
    """Append an approved, staged proposal to the correction log (write-once, read-only)."""
    four_eyes(proposed_by, approved_by)
    staged = root() / "staged" / f"{proposal_id}.parquet"
    target = root() / "applied" / f"{proposal_id}.parquet"
    if target.exists():
        raise CorrectionError(f"{proposal_id} is already in the correction log")
    if not staged.exists():
        raise CorrectionError(f"{proposal_id} was not staged")
    proposal, sha = load_proposal(proposal_id)
    con = duckdb.connect()
    staged_sha, staged_by = con.execute(
        f"SELECT any_value(proposal_sha256), any_value(proposed_by) FROM read_parquet('{staged}')"
    ).fetchone()
    if staged_sha != sha:
        raise CorrectionError("the proposal file changed after it was validated: propose again")
    if staged_by != proposed_by:
        raise CorrectionError("the staged proposal was proposed by someone else")
    now = datetime.now(UTC).replace(tzinfo=None)
    tmp = target.with_suffix(".tmp")
    con.execute(
        f"""COPY (SELECT * REPLACE (CAST(? AS VARCHAR) AS approved_by, CAST(? AS VARCHAR) AS approval_comment,
                                   CAST(? AS TIMESTAMP) AS applied_at)
                  FROM read_parquet('{staged}') ORDER BY seq)
            TO '{tmp}' (FORMAT parquet)""",
        [approved_by, comment, now],
    )
    tmp.rename(target)
    target.chmod(target.stat().st_mode & NO_WRITE)
    staged.unlink()
    entries = con.execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()[0]
    return {
        "proposal_id": proposal_id,
        "kind": proposal["kind"],
        "file": str(target.relative_to(config.DATA)),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "entries": entries,
        "applied_at": now.isoformat(),
        "read_only": not target.stat().st_mode & ~NO_WRITE,
    }


def discard(proposal_id: str) -> None:
    """Drop the staged entries of a rejected proposal (the proposal file and the ledger keep the record)."""
    (root() / "staged" / f"{proposal_id}.parquet").unlink(missing_ok=True)
