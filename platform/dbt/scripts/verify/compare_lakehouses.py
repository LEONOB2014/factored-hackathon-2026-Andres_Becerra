"""Compare two lakehouse builds relation by relation (docs/platform/09 §C.4, evidence/reproducibility).

Each build is reduced to a **fingerprint**: per relation, its columns and types, the row count, an
order-independent hash of every row and one per column. Two fingerprints are then compared: row counts, column
sets and types, row hashes and, when they differ, the columns whose hashes differ. Volatile run timestamps and
snapshot system time are ignored.

    cd platform/dbt
    uv run python scripts/verify/compare_lakehouses.py A.duckdb B.duckdb --out diff.csv
    uv run python scripts/verify/compare_lakehouses.py --fingerprint A.duckdb --out A.json   # then delete A.duckdb
    uv run python scripts/verify/compare_lakehouses.py A.json B.duckdb --out diff.csv          # mix freely

A fingerprint is a few hundred KB, so builds can be compared one at a time on a small disk. With --noise (the
output of the same comparison between two builds of one commit), each difference is marked `explained_by_noise`
when the relation and all its differing columns also differ between those two builds.

Run it from platform/dbt: views store paths relative to it (builds must come from a checkout in this environment).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb

# Run timestamps, and system time recorded by the snapshots (dbt_valid_* and recorded_from = when a build observed a
# version): they differ between builds by definition, everything else must not.
VOLATILE = {
    "computed_at",
    "checked_at",
    "held_at",
    "as_of_ts",
    "_loaded_at",
    "loaded_at",
    "generated_at",
    "recorded_from",
}
# Hashes are combined with sum(), not bit_xor(): XOR cancels equal values in pairs, so a column holding one value
# in every row would hash to 0 in both builds whatever that value is.


def fingerprint(db: Path) -> dict:
    con = duckdb.connect()
    con.sql("SET enable_progress_bar = false")
    cat = db.stem  # views name other relations by catalog = database file stem
    con.sql(f"ATTACH '{db}' AS \"{cat}\" (READ_ONLY)")
    out: dict = {"database": db.name, "relations": {}}
    rels = con.sql(f"""SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = '{cat}'
                       AND table_schema NOT IN ('main', 'information_schema') ORDER BY 1, 2""").fetchall()
    for s, t in rels:
        cols = dict(
            con.sql(f"""SELECT column_name, data_type FROM information_schema.columns WHERE table_catalog = '{cat}'
                        AND table_schema = '{s}' AND table_name = '{t}' ORDER BY ordinal_position""").fetchall()
        )
        hashed = [c for c in cols if c not in VOLATILE and not c.startswith("dbt_")]
        sel = ", ".join(f'"{c}"' for c in hashed)
        per_col = ", ".join(f'sum(hash("{c}"))::hugeint' for c in hashed)
        try:
            row = con.sql(
                f'SELECT count(*), sum(hash(row({sel})))::hugeint, {per_col} FROM "{cat}"."{s}"."{t}"'
            ).fetchone()
        except duckdb.Error as e:
            out["relations"][f"{s}.{t}"] = {"columns": cols, "error": str(e).splitlines()[0][:200]}
            continue
        out["relations"][f"{s}.{t}"] = {
            "columns": cols,
            "rows": row[0],
            "row_hash": str(row[1]),
            "column_hashes": {c: str(h) for c, h in zip(hashed, row[2:], strict=True)},
        }
    return out


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.suffix == ".json" else fingerprint(path)


def compare(fa: dict, fb: dict, noise: dict[str, set[str]]) -> list[dict]:
    ra, rb = fa["relations"], fb["relations"]
    rows = [{"relation": r, "status": "only_in_a"} for r in sorted(set(ra) - set(rb))]
    rows += [{"relation": r, "status": "only_in_b"} for r in sorted(set(rb) - set(ra))]
    for r in sorted(set(ra) & set(rb)):
        a, b = ra[r], rb[r]
        if "error" in a or "error" in b:
            rows.append(
                {"relation": r, "status": "error", "detail": a.get("error") or b.get("error")}
            )
            continue
        ca, cb = a["columns"], b["columns"]
        common = [c for c in a["column_hashes"] if c in b["column_hashes"]]
        diff_cols = [c for c in common if a["column_hashes"][c] != b["column_hashes"][c]]
        types = [f"{c}:{ca[c]}->{cb[c]}" for c in ca if c in cb and ca[c] != cb[c]]
        same = (
            a["rows"] == b["rows"]
            and a["row_hash"] == b["row_hash"]
            and not types
            and set(ca) == set(cb)
        )
        row = {
            "relation": r,
            "status": "identical" if same else "different",
            "rows_a": a["rows"],
            "rows_b": b["rows"],
            "columns_only_a": ";".join(sorted(set(ca) - set(cb))),
            "columns_only_b": ";".join(sorted(set(cb) - set(ca))),
            "type_differences": ";".join(types),
            "differing_columns": ";".join(diff_cols),
        }
        if noise and not same:
            row["explained_by_noise"] = (
                r in noise and set(diff_cols) <= noise[r] and a["rows"] == b["rows"] and not types
            )
        rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "inputs", nargs="*", type=Path, help="two builds (.duckdb) or fingerprints (.json)"
    )
    ap.add_argument(
        "--fingerprint", type=Path, help="write the fingerprint of this build to --out and stop"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--noise", type=Path, help="comparison of two builds of one commit")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.fingerprint:
        fp = fingerprint(args.fingerprint)
        args.out.write_text(json.dumps(fp, indent=0, sort_keys=True))
        print(f"{len(fp['relations'])} relations fingerprinted")
        return
    if len(args.inputs) != 2:
        ap.error("give two builds or fingerprints to compare")
    noise: dict[str, set[str]] = {}
    if args.noise:
        with args.noise.open() as f:
            noise = {r["relation"]: set(filter(None, r["differing_columns"].split(";")))
                     for r in csv.DictReader(f) if r["status"] == "different"}  # fmt: skip
    rows = compare(load(args.inputs[0]), load(args.inputs[1]), noise)
    fields = ["relation", "status", "rows_a", "rows_b", "columns_only_a", "columns_only_b", "type_differences",
              "differing_columns", "explained_by_noise", "detail"]  # fmt: skip
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(counts)


if __name__ == "__main__":
    main()
