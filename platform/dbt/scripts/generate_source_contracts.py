"""Seed the reviewed SOURCE contracts (platform/contracts/sources/<table>.yml) from the raw forensics.

Run once, review the YAML, commit it; from then on the YAML is the source of truth and changes go through
review. (Not to be confused with scripts/generate_contracts.py, which writes OUTPUT contracts for serving.)

Inputs:
* eda/reports/contracts/<table>.json: the Phase 1 contract inferred from the raw CSV text (value classes,
  empty shares, vocabularies);
* the typed bronze schema (data/lake/bronze, or its read-only archive): the target types, so silver keeps
  exactly the types it had while it read typed bronze;
* lossless bronze (data/lake/bronze_raw): key shapes, the canonical spelling of variant groups and the
  per-partition scale baseline of numeric columns.

    cd platform/dbt && uv run python scripts/generate_source_contracts.py
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "platform" / "libs"))
from latam_platform import config  # noqa: E402

PHASE1 = ROOT / "eda" / "reports" / "contracts"
OUT = ROOT / "platform" / "contracts" / "sources"
PII_SEED = ROOT / "platform" / "dbt" / "seeds" / "restricted_pii_columns.csv"
TYPED_CANDIDATES = [config.BRONZE, config.LAKE / "archive" / "bronze_typed_v1" / "bronze"]

# Free-text columns scanned for leaked placeholders (eda latam_eda.profiling.TEXT plus restricted free text).
TEXT = {"full_text", "customer_text", "agent_text", "description", "open_comments", "resolution",
        "subject", "page_url", "page_title"}  # fmt: skip
# Known generator artefacts already owned by a row-level rule: not re-flagged cell by cell.
KNOWN = {
    ("call_transcripts", "full_text"): {"slot": "unrendered template slots: rule R27"},
    ("call_transcripts", "agent_text"): {"slot": "unrendered template slots: rule R27"},
}
# Value classes a type accepts (names of latam_eda.raw_forensics.CLASSES). Numbers accept every lossless
# numeric spelling; temporal and other typed columns accept only the formats observed in the source.
NUMERIC = {"DOUBLE": ["int", "dec_dot", "sci"], "BIGINT": ["int"]}
OBSERVED = {
    "DATE": {"date_iso"},
    "TIMESTAMP": {"ts_space", "ts_t", "ts_tz", "date_iso"},
    "TIME": {"time"},
    "BOOLEAN": {"bool"},
}
STRING_FORMATS = {"json": {"json"}, "ip": {"ipv4", "ipv6"}}
MIN_SCALE_N = 30  # partitions with fewer non-zero values do not enter the scale baseline
SCALE_STEP = 0.5  # the drift check holds a partition whose log10 median moves this far (x3.16)
UNFIT_SHARE = 0.05  # ...so a column whose own history does that this often gets no scale check


def fold(value: str) -> str:
    """Same folding as latam_eda.raw_forensics.fold: case- and accent-insensitive."""
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold().strip()


def q(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def typed_schema(con, table: str) -> dict[str, str]:
    for base in TYPED_CANDIDATES:
        if list((base / table).glob("*/*.parquet")):
            rows = con.sql(
                f"DESCRIBE SELECT * FROM read_parquet('{base}/{table}/*/*.parquet', "
                "union_by_name=true, hive_partitioning=false)"
            ).fetchall()
            return {r[0]: r[1] for r in rows if not r[0].startswith("_")}
    raise SystemExit(f"typed bronze schema not found for {table} in {TYPED_CANDIDATES}")


def raw_rel(table: str) -> str:
    return (
        f"read_parquet('{config.BRONZE_RAW}/{table}/*/*.parquet', "
        "union_by_name=true, hive_partitioning=false)"
    )


def key_pattern(con, table: str, col: str) -> str | None:
    """^PREFIX-[0-9A-Z]{n}$ when every non-empty value has one prefix and one suffix length."""
    rows = con.sql(f"""
        SELECT split_part({q(col)}, '-', 1) AS prefix, length(split_part({q(col)}, '-', 2)) AS n,
               bool_and(regexp_full_match({q(col)}, '[A-Z]+-[0-9A-Z]+')) AS shaped
        FROM {raw_rel(table)} WHERE {q(col)} <> '' GROUP BY ALL""").fetchall()
    if len(rows) == 1 and rows[0][2]:
        prefix, n, _ = rows[0]
        return f"^{prefix}-[0-9A-Z]{{{n}}}$"
    return None


def vocabulary(con, table: str, col: str, values: list[str]) -> tuple[list[str], dict[str, str]]:
    """Canonical vocabulary plus a variant map (other spellings -> the most frequent spelling)."""
    values = [v for v in values if v != ""]
    groups: dict[str, list[str]] = {}
    for v in values:
        groups.setdefault(fold(v), []).append(v)
    variants: dict[str, str] = {}
    multi = [g for g in groups.values() if len(g) > 1]
    if multi:
        spellings = [v for g in multi for v in g]
        lits = ", ".join("'" + v.replace("'", "''") + "'" for v in spellings)
        counts = dict(
            con.sql(
                f"SELECT {q(col)}, count(*) FROM {raw_rel(table)} WHERE {q(col)} IN ({lits}) GROUP BY 1"
            ).fetchall()
        )
        for g in multi:
            canonical = max(g, key=lambda v: (counts.get(v, 0), v))
            variants.update({v: canonical for v in sorted(g) if v != canonical})
    return sorted(v for v in values if v not in variants), dict(sorted(variants.items()))


def scale(con, table: str, col: str, typ: str) -> dict | None:
    """Baseline of log10(median |x|) per partition: median and MAD across partitions."""
    row = con.sql(f"""
        WITH p AS (
            SELECT _partition_date, log10(median(abs(x))) AS m
            FROM (SELECT _partition_date, try_cast(nullif({q(col)}, '') AS {typ}) AS x FROM {raw_rel(table)})
            WHERE x <> 0 GROUP BY 1 HAVING count(*) >= {MIN_SCALE_N}
        )
        SELECT median(m), median(abs(m - (SELECT median(m) FROM p))), count(*),
               avg((abs(m - (SELECT median(m) FROM p)) >= {SCALE_STEP})::int) FROM p""").fetchone()
    if not row or row[2] == 0:
        return None
    if row[3] > UNFIT_SHARE:  # the statistic already jumps by a step in its own history: multimodal
        return {"unfit": f"{row[3]:.0%} of baseline partitions move by >= {SCALE_STEP} in log10"}
    return {"log10_median": round(row[0], 4), "mad": round(row[1], 4), "partitions": row[2]}


def contract(con, table: str, pii: dict[str, str]) -> dict:
    p1 = json.loads((PHASE1 / f"{table}.json").read_text())
    types = typed_schema(con, table)
    meta = config.TABLES[table]
    columns: dict[str, dict] = {}
    for col in p1["header"]:
        spec = p1["columns"][col]
        typ = types.get(col, "VARCHAR")
        c: dict = {
            "type": typ,
            "required": spec["empty_share"] == 0,
            "empty_share": spec["empty_share"],  # baseline for the empty-share drift check
        }
        observed = set(spec["formats"])
        if typ in NUMERIC:
            c["formats"] = list(NUMERIC[typ])
        elif typ in OBSERVED:
            c["formats"] = sorted(observed & OBSERVED[typ])
        elif spec["type"] in STRING_FORMATS:
            c["formats"] = sorted(observed & STRING_FORMATS[spec["type"]])
        if typ == "VARCHAR" and col.endswith("_id") and spec["type"] != "empty":
            kp = key_pattern(con, table, col)
            if kp:
                c["key_pattern"] = kp
        listed = any("," in v for v in spec.get("vocabulary", []))  # multi-valued: no closed set
        enumerated = spec.get("vocabulary") and spec["type"] == "string" and not listed
        if typ == "VARCHAR" and enumerated and col not in pii and col not in TEXT:
            vocab, variants = vocabulary(con, table, col, spec["vocabulary"])
            c["vocabulary"] = vocab
            if variants:
                c["variants"] = variants
        if col in pii:
            c["pii"] = pii[col]
        if col in TEXT:
            known = KNOWN.get((table, col), {})
            c["scan"] = [s for s in ("null_word", "slot") if s not in known]
            if known:
                c["scan_exempt"] = known
        if typ in NUMERIC:
            s = scale(con, table, col, typ)
            if s and "unfit" in s:
                c["note"] = "no scale check: unstable daily median (" + s["unfit"] + ")"
            elif s:
                c["scale"] = s
        if spec["type"] == "empty":
            c["note"] = "always empty in the source so far"
        columns[col] = c
    return {
        "table": table,
        "kind": meta.kind,
        "entity_key": list(meta.pk),
        "timestamps": "naive: the source carries no offset (process_date is a batch window)",
        "inferred_from": {
            "phase1_contract": p1["contract_version"],
            "rows": p1["columns"][p1["header"][0]]["rows"],
            "files": p1["columns"][p1["header"][0]]["files"],
        },
        "columns": columns,
    }


HEADER = """\
# Source contract: {table}. Lossless bronze (every field as text) is typed into silver against it.
# Seeded by platform/dbt/scripts/generate_source_contracts.py from the raw forensics contract
# (eda/reports/contracts/{table}.json) and the retired typed bronze schema, then reviewed.
# This file is the source of truth: change it by pull request, then regenerate the dbt artefacts with
#   cd platform/dbt && uv run python scripts/generate_silver_from_contracts.py
# A cell that breaks it is flagged in audit.dq_cell_findings, never dropped.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--table", action="append", help="only these tables (default: all)")
    args = ap.parse_args()
    import csv

    with PII_SEED.open() as f:
        pii = {r["column_name"]: r["pii_type"] for r in csv.DictReader(f)}
    con = duckdb.connect()
    con.sql("SET enable_progress_bar = false")
    OUT.mkdir(parents=True, exist_ok=True)
    for table in args.table or sorted(config.TABLES):
        body = yaml.safe_dump(
            contract(con, table, pii), sort_keys=False, allow_unicode=True, width=110
        )
        (OUT / f"{table}.yml").write_text(HEADER.format(table=table) + body)
        print(f"wrote {OUT.relative_to(ROOT)}/{table}.yml")


if __name__ == "__main__":
    main()
