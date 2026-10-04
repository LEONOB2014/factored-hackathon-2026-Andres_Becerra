"""Raw-CSV schema forensics: fingerprints of every (file, column) computed from the original text.

The raw files carry no metadata, and typed copies (Parquet, bronze) already coerced what would reveal
a schema change: formats, separators, leading zeros, empty-vs-null, values that did not fit. So every
fingerprint here is computed from the raw text, read with a pinned dialect, all columns as VARCHAR and
a sentinel `nullstr` so that empty strings stay empty.

Levels (see docs/platform/09_data_and_model_risk_methodology.md, section A):
  L0  file bytes: size, sha256, BOM, line terminators, UTF-8 validity, records by CSV grammar, ragged rows
  L1  header: names, order, BOM attached to the first name
  L2  lexical: share of each value class (integer, decimal dot/comma, ISO date, timestamp variants, ...),
      lengths, charset, decimals, magnitude
  L3  semantic: vocabularies per file, numeric scale (log10 median), key formats
Contracts summarise the whole history of a table into an inferred, versioned schema.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# A string that never occurs in the data: with it as `nullstr`, DuckDB keeps '' as ''.
SENTINEL = "\u0001"
READ_OPTS = (
    "header=true, delim=',', quote='\"', escape='\"', all_varchar=true, "
    f"nullstr='{SENTINEL}', strict_mode=true, sample_size=-1, filename=true, "
    "hive_partitioning=false"
)
NULL_TOKENS = ("null", "none", "nan", "n/a", "na", "-", "?", "undefined")

# Ordered value classes: the first full match wins. Order matters (int before decimal, date before
# timestamp). Each class is a format, not a type: several classes can map to one type.
CLASSES: list[tuple[str, str]] = [
    ("bool", r"(?i)(true|false)"),
    ("ipv4", r"([0-9]{1,3}\.){3}[0-9]{1,3}"),
    ("url", r"(?i)https?://\S+"),
    ("int_leading_zero", r"[+-]?0[0-9]+"),
    ("int", r"[+-]?[0-9]+"),
    ("dec_dot", r"[+-]?[0-9]*\.[0-9]+"),
    ("dec_comma", r"[+-]?[0-9]+,[0-9]+"),
    ("dec_thousands", r"[+-]?[0-9]{1,3}([.,][0-9]{3})+([.,][0-9]+)?"),
    ("sci", r"[+-]?[0-9]*\.?[0-9]+[eE][+-]?[0-9]+"),
    ("date_iso", r"[0-9]{4}-[0-9]{2}-[0-9]{2}"),
    ("date_dmy", r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}"),
    ("ts_space", r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?"),
    ("ts_t", r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?"),
    (
        "ts_tz",
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?(Z|[+-][0-9]{2}:?[0-9]{2})",
    ),
    ("time", r"[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?"),
    # after time: "09:15:00" has two colons too
    ("ipv6", r"[0-9a-fA-F]{0,4}(:[0-9a-fA-F]{0,4}){2,7}"),
    ("json", r"\s*[\{\[].*[\}\]]\s*"),
]
CLASS_NAMES = ["empty", "null_token", *[c for c, _ in CLASSES], "text"]

# Lattice: a type and the value classes it can represent without loss. Inference picks the first
# type (in this order) covering >= coverage of the non-empty values. Leading-zero integers are codes:
# a numeric type would destroy them, so they only fit `string`.
LATTICE: list[tuple[str, set[str]]] = [
    ("boolean", {"bool"}),
    ("integer", {"int"}),
    ("decimal", {"int", "dec_dot", "sci"}),
    ("date", {"date_iso"}),
    ("timestamp", {"ts_space", "ts_t", "ts_tz", "date_iso"}),
    ("time", {"time"}),
    ("json", {"json"}),
    ("ip", {"ipv4", "ipv6"}),
]


def q(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def partition_date(path: Path) -> str | None:
    """yyyy-mm-dd from a Hive path (year=YYYY/month=MM/day=DD), else None (dimension file)."""
    m = re.search(r"year=(\d{4})/month=(\d{2})/day=(\d{2})", str(path))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def table_files(root: Path, table: str) -> list[Path]:
    """Every CSV of a table under a raw root: Hive-partitioned folder or a single file."""
    folder = root / table
    if folder.is_dir():
        return sorted(folder.glob("year=*/month=*/day=*/*.csv"))
    single = root / f"{table}.csv"
    return [single] if single.exists() else []


# ----------------------------------------------------------------------------------------- L0 + L1
@dataclass
class FileScan:
    path: str
    partition_date: str | None
    size: int
    sha256: str
    bom: bool
    lf: int
    crlf: int
    cr_only: int
    utf8_errors: int
    nul_bytes: int
    header: list[str]
    header_bom_in_name: bool
    records: int
    ragged: int
    multiline_records: int
    grammar_error: str | None


def scan_file(path: Path) -> FileScan:
    """L0/L1 from the bytes: nothing DuckDB normalises away is lost here."""
    raw = Path(path).read_bytes()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    cr_only = raw.count(b"\r") - crlf
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8")
        utf8_errors = 0
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        utf8_errors = text.count("�")
    body = text[1:] if text.startswith("﻿") else text
    header, records, ragged, multiline, err = [], 0, 0, 0, None
    try:
        reader = csv.reader(body.splitlines(keepends=True), strict=True)
        header = next(reader, [])
        start = reader.line_num
        for row in reader:
            records += 1
            ragged += len(row) != len(header)
            multiline += reader.line_num - start > 1
            start = reader.line_num
    except csv.Error as e:
        err = str(e)
    return FileScan(
        path=str(path),
        partition_date=partition_date(path),
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        bom=bom,
        lf=lf,
        crlf=crlf,
        cr_only=cr_only,
        utf8_errors=utf8_errors,
        nul_bytes=raw.count(b"\x00"),
        header=header,
        # a reader that does not strip the BOM renames the first column: '﻿id' instead of 'id'
        header_bom_in_name=bool(header) and header[0].startswith("﻿"),
        records=records,
        ragged=ragged,
        multiline_records=multiline,
        grammar_error=err,
    )


# ------------------------------------------------------------------------------------- L2 lexical
def class_case(col: str) -> str:
    """SQL CASE assigning each raw value of `col` to its first matching class."""
    v = q(col)
    tokens = ", ".join(f"'{t}'" for t in NULL_TOKENS)
    arms = [f"WHEN {v} = '' THEN 'empty'", f"WHEN lower(trim({v})) IN ({tokens}) THEN 'null_token'"]
    arms += [f"WHEN regexp_full_match({v}, '{rx}') THEN '{name}'" for name, rx in CLASSES]
    return "CASE " + " ".join(arms) + " ELSE 'text' END"


def _load_chunk(con, files: list[Path]) -> list[str]:
    """Read files once into the temp table `_chunk` (raw text) and return the data columns."""
    listing = "[" + ", ".join(f"'{f}'" for f in files) + "]"
    con.sql(
        f"create or replace temp table _chunk as select * from read_csv({listing}, {READ_OPTS})"
    )
    return [r[0] for r in con.sql("describe _chunk").fetchall() if r[0] != "filename"]


def _profile_column(con, col: str) -> pd.DataFrame:
    counts = ", ".join(f"count(*) filter (where cls = '{c}') as {q('n_' + c)}" for c in CLASS_NAMES)
    return con.sql(
        f"""
        with t as (select filename, {q(col)} as v, {class_case(col)} as cls from _chunk)
        select filename as file, '{col}' as column, count(*) as n, {counts},
               min(length(v)) as len_min, max(length(v)) as len_max, avg(length(v)) as len_avg,
               count(*) filter (where regexp_matches(v, '[^\\x00-\\x7F]')) as n_non_ascii,
               count(*) filter (where v <> trim(v)) as n_untrimmed,
               max(length(regexp_extract(v, '\\.([0-9]+)$', 1)))
                   filter (where cls in ('dec_dot', 'ts_space', 'ts_t', 'ts_tz')) as max_fraction_digits,
               -- CASE guard: DuckDB evaluates log10 before the filter, and log10(0) raises
               median(log10(case when abs(try_cast(v as double)) > 0
                                 then abs(try_cast(v as double)) end))
                   filter (where cls in ('int', 'dec_dot', 'sci')) as log10_median
        from t group by filename
        """
    ).df()


def lexical_profile(
    con, files: list[Path], columns: list[str] | None = None, chunk: int = 31
) -> pd.DataFrame:
    """One row per (file, column): counts per value class plus length, charset, decimals and scale.

    Files are read once per chunk (about a month of daily partitions) as raw text, `''` kept empty;
    every column is then profiled from memory. Columns default to the whole header.
    """
    frames = []
    for i in range(0, len(files), chunk):
        cols = _load_chunk(con, files[i : i + chunk])
        frames += [_profile_column(con, c) for c in (columns or cols)]
    con.sql("drop table if exists _chunk")
    out = pd.concat(frames, ignore_index=True)
    out["partition_date"] = out["file"].map(lambda f: partition_date(Path(f)))
    return out


def vocabulary(con, files: list[Path], columns: list[str], chunk: int = 31) -> pd.DataFrame:
    """(file, column, value, n) for low-cardinality text columns: births, deaths and variants."""
    frames = []
    for i in range(0, len(files), chunk):
        _load_chunk(con, files[i : i + chunk])
        parts = [
            f"select filename as file, '{c}' as column, {q(c)} as value, count(*) as n "
            f"from _chunk group by 1, 3"
            for c in columns
        ]
        frames.append(con.sql(" union all ".join(parts)).df())
    con.sql("drop table if exists _chunk")
    out = pd.concat(frames, ignore_index=True)
    out["partition_date"] = out["file"].map(lambda f: partition_date(Path(f)))
    return out


def fold(value: str) -> str:
    """Case- and accent-insensitive key: 'México' and 'MEXICO' fold to 'mexico'."""
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold().strip()


def variant_groups(values: list[str]) -> dict[str, list[str]]:
    """Values that differ only by case or accents: {folded key: [spellings]} for keys with >1 spelling."""
    groups: dict[str, set[str]] = {}
    for v in values:
        if v:
            groups.setdefault(fold(v), set()).add(v)
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def key_shape(value: str) -> str:
    """Shape of an identifier: letters -> A, digits -> 9, other characters kept ('TRX-A9B' -> 'AAA-A9A')."""
    return re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "A", value))


# -------------------------------------------------------------------------------- inferred contract
def infer_type(class_counts: dict[str, int], coverage: float = 0.999) -> tuple[str, float]:
    """(lattice type, share of non-empty values it covers). Empty and null tokens are not evidence."""
    total = sum(n for c, n in class_counts.items() if c not in ("empty", "null_token"))
    if total == 0:
        return "empty", 1.0
    for type_name, classes in LATTICE:
        share = sum(class_counts.get(c, 0) for c in classes) / total
        if share >= coverage:
            return type_name, share
    return "string", 1.0


def column_contract(profile: pd.DataFrame, column: str, coverage: float = 0.999) -> dict:
    """Contract entry for one column from its per-file lexical profile (all files of a table)."""
    p = profile[profile["column"] == column]
    counts = {c: int(p[f"n_{c}"].sum()) for c in CLASS_NAMES}
    n = int(p["n"].sum())
    type_name, share = infer_type(counts, coverage)
    present = {c: k for c, k in counts.items() if k and c not in ("empty", "null_token")}
    nonempty = sum(present.values()) or 1
    return {
        "type": type_name,
        "coverage": round(share, 6),
        "formats": {
            c: round(k / nonempty, 6) for c, k in sorted(present.items(), key=lambda x: -x[1])
        },
        "empty_share": round(counts["empty"] / max(n, 1), 6),
        "null_token_share": round(counts["null_token"] / max(n, 1), 6),
        "length": [int(p["len_min"].min()), int(p["len_max"].max())],
        "non_ascii_share": round(float(p["n_non_ascii"].sum()) / max(n, 1), 6),
        "max_fraction_digits": None
        if p["max_fraction_digits"].isna().all()
        else int(p["max_fraction_digits"].max()),
        "files": int(p["file"].nunique()),
        "rows": n,
    }


def table_contract(
    table: str, profile: pd.DataFrame, header: list[str], vocab: dict | None = None
) -> dict:
    """Inferred, versioned contract for a table. The version is a hash of its content."""
    body = {
        "table": table,
        "header": header,
        "columns": {c: column_contract(profile, c) for c in header},
    }
    if vocab:
        for c, values in vocab.items():
            body["columns"][c]["vocabulary"] = values
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    return {"contract_version": digest, **body}


def minority_formats(profile: pd.DataFrame, contract: dict) -> pd.DataFrame:
    """Per (file, column): values in classes the contract type does not cover (the anomalies)."""
    rows = []
    for col, spec in contract["columns"].items():
        covered = next((cl for t, cl in LATTICE if t == spec["type"]), None)
        if covered is None:  # string or empty: everything is covered
            continue
        p = profile[profile["column"] == col]
        others = [c for c in CLASS_NAMES if c not in covered and c not in ("empty", "null_token")]
        for _, r in p.iterrows():
            for c in others:
                if r[f"n_{c}"]:
                    rows.append(
                        {
                            "file": r["file"],
                            "partition_date": r["partition_date"],
                            "column": col,
                            "expected_type": spec["type"],
                            "found_class": c,
                            "n": int(r[f"n_{c}"]),
                        }
                    )
    return pd.DataFrame(
        rows, columns=["file", "partition_date", "column", "expected_type", "found_class", "n"]
    )


def class_share_matrix(profile: pd.DataFrame, column: str) -> pd.DataFrame:
    """Daily share of each value class for one column (rows = partition dates): the input to drift tests."""
    p = (
        profile[profile["column"] == column]
        .groupby("partition_date")[[f"n_{c}" for c in CLASS_NAMES]]
        .sum()
    )
    p.columns = CLASS_NAMES
    return p.div(p.sum(axis=1).where(lambda s: s > 0), axis=0).fillna(0.0).sort_index()


def header_census(scans: list[FileScan]) -> Counter:
    """Distinct headers (as tuples) and how many files carry each."""
    return Counter(tuple(s.header) for s in scans)
