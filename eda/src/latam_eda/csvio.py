"""CSV -> Parquet conversion that never drops, reshapes or silently re-types rows.

DuckDB's CSV auto-detection is lenient in ways that propagate damage without an error:
* `ignore_errors=true` drops rows that do not fit the inferred schema;
* with `union_by_name=true` each file is sniffed on its own, and a file with a ragged row can be
  read with a different dialect, losing rows (the strict all-varchar parse agrees with the loss);
* one unparsable value in any file demotes the whole column to VARCHAR.

So the dialect is pinned, the record count is reconciled against an independent parser (Python's
csv module, strict), ragged rows are refused, and near-total castability of a VARCHAR column is
treated as a demotion. Any of these raises `CsvIntegrityError` and removes the partial output.
"""

import csv
from pathlib import Path

DIALECT = "header=true, delim=',', quote='\"', escape='\"', sample_size=-1"


class CsvIntegrityError(RuntimeError):
    """The CSV -> Parquet conversion would lose, reshape or re-type data."""


def count_records(path: Path) -> tuple[int, int]:
    """(data records, records whose field count differs from the header), by CSV grammar.

    Counts records, not lines: quoted fields may contain newlines. `utf-8-sig` strips a BOM.
    """
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh, strict=True)
        header = next(reader, None)
        if header is None:
            return 0, 0
        n = ragged = 0
        for row in reader:
            n += 1
            ragged += len(row) != len(header)
    return n, ragged


def type_demotions(con, parquet: Path, share: float = 0.99) -> list[tuple[str, str, float]]:
    """VARCHAR columns whose non-null values are almost all numeric, timestamp or boolean.

    Returns (column, castable kind, castable share) for shares in [share, 1): a few bad values
    turned a typed column into text.
    """
    found = []
    for name, dtype, *_ in con.sql(f"describe select * from '{parquet}'").fetchall():
        if dtype != "VARCHAR":
            continue
        q = '"' + name.replace('"', '""') + '"'
        nn, num, ts, bo = con.sql(
            f"""select count({q}), count(try_cast({q} as double)),
                       count(try_cast({q} as timestamp)), count(try_cast({q} as boolean))
                from '{parquet}'"""
        ).fetchone()
        for kind, k in (("numeric", num), ("timestamp", ts), ("boolean", bo)):
            if nn and share <= k / nn < 1:
                found.append((name, kind, k / nn))
    return found


def csv_to_parquet(con, files: list[Path], out: Path, union_by_name: bool = False) -> int:
    """Convert CSV files to one Parquet file; return the row count or raise `CsvIntegrityError`.

    `union_by_name` is only for sources whose headers may differ (a partition gaining a column);
    with one shared header, leave it off so a schema mismatch fails loudly.
    """
    if not files:
        raise CsvIntegrityError(f"no CSV files for {out.name}")
    expected = ragged = 0
    for f in files:
        try:
            n, r = count_records(f)
        except (csv.Error, UnicodeDecodeError) as e:
            raise CsvIntegrityError(f"{out.name}: {Path(f).name} does not parse as CSV: {e}") from e
        expected += n
        ragged += r
    if ragged:
        raise CsvIntegrityError(f"{out.name}: {ragged:,} records with a wrong field count")
    listing = ", ".join(f"'{f}'" for f in files)
    extra = ", union_by_name=true" if union_by_name else ""
    con.sql(
        f"""COPY (SELECT * FROM read_csv([{listing}], {DIALECT}, hive_partitioning=false{extra}))
            TO '{out}' (FORMAT parquet, COMPRESSION zstd)"""
    )
    written = con.sql(f"select count(*) from '{out}'").fetchone()[0]
    problems = []
    if written != expected:
        problems.append(f"{written:,} rows written but {expected:,} records in the CSVs")
    problems += [
        f"column {c} demoted to VARCHAR ({share:.3%} of values are {kind})"
        for c, kind, share in type_demotions(con, out)
    ]
    if problems:
        out.unlink(missing_ok=True)
        raise CsvIntegrityError(f"{out.name}: " + "; ".join(problems))
    return written
