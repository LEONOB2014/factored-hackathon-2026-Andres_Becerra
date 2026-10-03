"""Compare two lakehouse builds relation by relation (docs/platform/09 §C.4).

For every relation in both DuckDB files: row counts, column sets and types, an order-independent hash of all
values and, when the hashes differ, the columns whose hashes differ. Volatile run timestamps are ignored.

    cd platform/dbt && uv run python scripts/verify/compare_lakehouses.py A.duckdb B.duckdb --out diff.csv

With --noise (the output of the same comparison between two builds of one commit), each difference is marked
`explained_by_noise` when the relation and all its differing columns also differ between those two builds.

Run it from platform/dbt: views store paths relative to it (both builds must have been made from a checkout
in this same environment, or their views will not resolve).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import duckdb

VOLATILE = {
    "computed_at",
    "checked_at",
    "held_at",
    "as_of_ts",
    "_loaded_at",
    "loaded_at",
    "generated_at",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--noise", type=Path, help="comparison of two builds of one commit")
    args = ap.parse_args()
    noise: dict[str, set[str]] = {}
    if args.noise:
        with args.noise.open() as f:
            noise = {r["relation"]: set(filter(None, r["differing_columns"].split(";")))
                     for r in csv.DictReader(f) if r["status"] == "different"}  # fmt: skip
    con = duckdb.connect()
    con.sql("SET enable_progress_bar = false")
    # views name other relations by catalog = database file stem: attach each build under its own stem
    a, b = args.a.stem, args.b.stem
    if a == b:
        raise SystemExit("the two builds need different file names")
    con.sql(f"ATTACH '{args.a}' AS \"{a}\" (READ_ONLY)")
    con.sql(f"ATTACH '{args.b}' AS \"{b}\" (READ_ONLY)")

    def relations(db: str) -> set[tuple[str, str]]:
        return set(
            con.sql(f"""SELECT table_schema, table_name FROM information_schema.tables
                        WHERE table_catalog = '{db}' AND table_schema NOT IN ('main', 'information_schema')""").fetchall()
        )

    def columns(db: str, schema: str, table: str) -> dict[str, str]:
        return dict(
            con.sql(f"""SELECT column_name, data_type FROM information_schema.columns WHERE table_catalog = '{db}'
                        AND table_schema = '{schema}' AND table_name = '{table}'""").fetchall()
        )

    ra, rb = relations(a), relations(b)
    rows = [{"relation": f"{s}.{t}", "status": "only_in_a"} for s, t in sorted(ra - rb)]
    rows += [{"relation": f"{s}.{t}", "status": "only_in_b"} for s, t in sorted(rb - ra)]
    for s, t in sorted(ra & rb):
        ca, cb = columns(a, s, t), columns(b, s, t)
        common = [c for c in ca if c in cb and c not in VOLATILE and not c.startswith("dbt_")]
        sel = ", ".join(f'"{c}"' for c in common)
        row = {"relation": f"{s}.{t}"}
        try:
            na, ha = con.sql(
                f'SELECT count(*), bit_xor(hash(row({sel}))) FROM "{a}"."{s}"."{t}"'
            ).fetchone()
            nb, hb = con.sql(
                f'SELECT count(*), bit_xor(hash(row({sel}))) FROM "{b}"."{s}"."{t}"'
            ).fetchone()
        except duckdb.Error as e:
            rows.append({**row, "status": "error", "detail": str(e).splitlines()[0][:200]})
            continue
        diff_cols = []
        if ha != hb:
            for c in common:
                xa = con.sql(f'SELECT bit_xor(hash("{c}")) FROM "{a}"."{s}"."{t}"').fetchone()[0]
                xb = con.sql(f'SELECT bit_xor(hash("{c}")) FROM "{b}"."{s}"."{t}"').fetchone()[0]
                if xa != xb:
                    diff_cols.append(c)
        types = [f"{c}:{ca[c]}->{cb[c]}" for c in common if ca[c] != cb[c]]
        same = na == nb and ha == hb and not types and set(ca) == set(cb)
        rows.append(
            {
                **row,
                "status": "identical" if same else "different",
                "rows_a": na,
                "rows_b": nb,
                "columns_only_a": ";".join(sorted(set(ca) - set(cb))),
                "columns_only_b": ";".join(sorted(set(cb) - set(ca))),
                "type_differences": ";".join(types),
                "differing_columns": ";".join(diff_cols),
            }
        )
        if args.noise and not same:
            rows[-1]["explained_by_noise"] = (
                f"{s}.{t}" in noise
                and set(diff_cols) <= noise[f"{s}.{t}"]
                and na == nb
                and not types
            )
    fields = ["relation", "status", "rows_a", "rows_b", "columns_only_a", "columns_only_b", "type_differences",
              "differing_columns", "explained_by_noise", "detail"]  # fmt: skip
    args.out.parent.mkdir(parents=True, exist_ok=True)
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
