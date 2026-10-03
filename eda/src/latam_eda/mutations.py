"""Synthetic schema mutations for positive controls: the detectors must find each of these.

A mutation rewrites a copy of raw CSV partitions from a given day onwards, keeping the original dialect
(BOM, CRLF, minimal quoting) so that only the mutation itself differs. Used by
scripts/mutate_partitions.py to measure recall, detection delay and false alarms per detector.
"""

from __future__ import annotations

import csv
import io
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True)
class Mutation:
    name: str
    column: str | None
    expect: str  # the finding that must appear: "<level>|<column>|<signal prefix>|<kind>"
    row: Callable[[dict, random.Random], dict] | None = None
    file: str | None = None  # file-level mutation: drop_bom | ragged | unterminated_quote


def _rename(col, old, new):
    return lambda r, _: {**r, col: new if r[col] == old else r[col]}


def _decimal_comma(col):
    return lambda r, _: {**r, col: r[col].replace(".", ",")}


def _date_dmy(col):
    def f(r, _):
        v = r[col]
        if len(v) >= 10 and v[4] == "-":  # yyyy-mm-dd... -> dd/mm/yyyy...
            v = f"{v[8:10]}/{v[5:7]}/{v[:4]}{v[10:]}"
        return {**r, col: v}

    return f


def _tz_suffix(col):
    return lambda r, _: {**r, col: r[col] + "-05:00" if r[col] else r[col]}


def _scale(col, factor):
    def f(r, _):
        try:
            return {**r, col: f"{float(r[col]) * factor:.2f}"}
        except ValueError:
            return r

    return f


def _swap(a, b):
    return lambda r, _: {**r, a: r[b], b: r[a]}


def _strip_zeros(col):
    return lambda r, _: {**r, col: r[col].lstrip("0") or "0" if r[col] else r[col]}


def transactions_catalogue() -> list[Mutation]:
    """Mutations for the transactions table, each with the finding the detectors must produce."""
    return [
        Mutation(
            "rename_category",
            "transaction_type",
            "L3|transaction_type|value=Compra|born",
            row=_rename("transaction_type", "Purchase", "Compra"),
        ),
        Mutation(
            "decimal_comma",
            "amount",
            "L2|amount|class:dec_comma|born",
            row=_decimal_comma("amount"),
        ),
        Mutation(
            "date_format_dmy",
            "process_date",
            "L2|process_date|class:date_dmy|born",
            row=_date_dmy("process_date"),
        ),
        Mutation(
            "timezone_suffix",
            "transaction_date",
            "L2|transaction_date|class:ts_tz|born",
            row=_tz_suffix("transaction_date"),
        ),
        Mutation("unit_x1000", "amount", "L3|amount|scale|scale_step", row=_scale("amount", 1000)),
        Mutation(
            "swap_columns", "amount", "L2|amount|class:text|born", row=_swap("amount", "currency")
        ),
        Mutation(
            "lost_leading_zeros",
            "response_code",
            "L2|response_code|class:int_leading_zero|died",
            row=_strip_zeros("response_code"),
        ),
        Mutation("bom_removed", None, "L0||bom|died", file="drop_bom"),
        Mutation("ragged_rows", None, "L0||ragged_rows|born", file="ragged"),
        Mutation("unterminated_quote", None, "L0||grammar_error|born", file="unterminated_quote"),
    ]


def rewrite(src: Path, dst: Path, mutation: Mutation | None, seed: int = 0) -> None:
    """Copy src to dst, applying `mutation` (None = verbatim copy) with the original dialect."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_bytes()
    if mutation is None:
        dst.write_bytes(raw)
        return
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rng = random.Random(seed)  # noqa: S311  (test data, not security)
    buf = io.StringIO(newline="")
    w = csv.DictWriter(
        buf, fieldnames=reader.fieldnames, lineterminator="\r\n", extrasaction="ignore"
    )
    w.writeheader()
    rows = list(reader)
    for i, r in enumerate(rows):
        if mutation.row:
            r = mutation.row(r, rng)
        w.writerow(r)
        if mutation.file == "ragged" and i % 50 == 0:  # 2% of rows gain a field
            buf.write(buf.getvalue().splitlines()[-1] + ",extra\r\n")
    out = buf.getvalue()
    if mutation.file == "unterminated_quote":
        out += 'X-BROKEN,"never closed\r\n'
    keep_bom = bom and mutation.file != "drop_bom"
    dst.write_bytes((b"\xef\xbb\xbf" if keep_bom else b"") + out.encode())
