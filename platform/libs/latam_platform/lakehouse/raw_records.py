"""Byte-exact CSV records: split a file into its records, parse them, and rebuild the file from the parts.

Lossless bronze stores every field as its original text. That is only a guarantee if the file can be
rebuilt, byte for byte, from what is stored, so this module splits on the bytes (not on a parser's
interpretation), keeps each record's exact bytes when re-serialising its fields would not reproduce
them, and rebuilds a file from header + records for the proof:

    sha256(rebuild(read_file(raw))) == sha256(raw)

Records end at a newline outside quotes (RFC 4180): a quoted field may contain LF or CRLF, and an
escaped quote ("") keeps the quote count even. A CR-only line ending is not a record separator.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from dataclasses import dataclass, field

BOM = b"\xef\xbb\xbf"
csv.field_size_limit(1 << 30)  # transcripts: the default 128 KiB per field is too small
STATUSES = ("ok", "ragged", "quote_error", "encoding_error")


def split_records(raw: bytes, start: int = 0) -> list[tuple[int, int]]:
    """(start, end) byte offsets of each record from `start`, terminator included.

    Scans line by line with bytes.find/count (C speed) and ends a record at a newline once the number
    of quotes seen in the record is even. Trailing bytes after the last newline form a final record;
    an open quote at end of file yields the remainder as one (unparsable) record.
    """
    out: list[tuple[int, int]] = []
    n, pos, rec_start, quotes = len(raw), start, start, 0
    while pos < n:
        nl = raw.find(b"\n", pos)
        if nl == -1:
            break
        quotes += raw.count(b'"', pos, nl)
        if quotes % 2 == 0:
            out.append((rec_start, nl + 1))
            rec_start, quotes = nl + 1, 0
        pos = nl + 1
    if rec_start < n:
        out.append((rec_start, n))
    return out


def terminator_of(record: bytes) -> bytes:
    if record.endswith(b"\r\n"):
        return b"\r\n"
    if record.endswith(b"\n"):
        return b"\n"
    return b""


def parse_record(record: bytes, n_fields: int | None) -> tuple[list[str] | None, str]:
    """Fields of one record and its status: ok | ragged | quote_error | encoding_error.

    `n_fields` is the header width (None while parsing the header itself).
    """
    try:
        text = record.decode("utf-8")
    except UnicodeDecodeError:
        return None, "encoding_error"
    body = text[: len(text) - len(terminator_of(record))]
    try:
        rows = list(csv.reader(io.StringIO(body, newline=""), strict=True))
    except csv.Error:
        return None, "quote_error"
    if len(rows) != 1:
        return None, "ragged"  # an empty line, or more than one row in one record
    fields = rows[0]
    if n_fields is not None and len(fields) != n_fields:
        return fields, "ragged"
    return fields, "ok"


def canonical(fields: list[str], terminator: bytes) -> bytes:
    """Minimal-quoting re-serialisation of a record (what most writers, and this source, produce)."""
    buf = io.StringIO(newline="")
    csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator=terminator.decode()).writerow(fields)
    return buf.getvalue().encode("utf-8")


@dataclass
class Record:
    record_no: int  # 1-based, header excluded
    fields: list[str] | None  # NULL data columns when the record is not ok
    status: str
    sha256: str  # of the record's exact bytes
    raw: bytes | None  # exact bytes, kept only when the record is not ok or not canonical


@dataclass
class FileRecords:
    bom: bool
    header_raw: bytes  # header record exactly as written (BOM excluded, terminator included)
    header: list[str]
    terminator: bytes  # the file's dominant record terminator
    records: list[Record] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c = Counter(r.status for r in self.records)
        return {s: c.get(s, 0) for s in STATUSES} | {
            "records": len(self.records),
            "verbatim": sum(r.raw is not None for r in self.records),
        }


def read_file(raw: bytes) -> FileRecords:
    """Split and parse a whole CSV file, keeping whatever the rebuild needs to be byte-exact."""
    bom = raw.startswith(BOM)
    spans = split_records(raw, len(BOM) if bom else 0)
    if not spans:
        return FileRecords(bom, b"", [], b"\r\n")
    h0, h1 = spans[0]
    header_raw = raw[h0:h1]
    header, _ = parse_record(header_raw, None)
    body = [raw[a:b] for a, b in spans[1:]]
    terms = Counter(terminator_of(r) for r in body) or Counter([terminator_of(header_raw)])
    term = terms.most_common(1)[0][0] or terminator_of(header_raw) or b"\r\n"
    fr = FileRecords(bom, header_raw, header or [], term)
    width = len(header) if header else None
    for i, rec in enumerate(body, start=1):
        fields, status = parse_record(rec, width)
        keep = status != "ok" or canonical(fields, term) != rec
        fr.records.append(
            Record(
                record_no=i,
                fields=fields if status == "ok" else None,
                status=status,
                sha256=hashlib.sha256(rec).hexdigest(),
                raw=rec if keep else None,
            )
        )
    return fr


def rebuild(bom: bool, header_raw: bytes, terminator: bytes, records) -> bytes:
    """The file's bytes from its stored parts: BOM + header + each record (verbatim or canonical).

    `records` is an iterable of (fields, raw) in record order.
    """
    parts = [BOM if bom else b"", header_raw]
    for fields, raw in records:
        parts.append(raw if raw is not None else canonical(fields, terminator))
    return b"".join(parts)


def rebuild_file(fr: FileRecords) -> bytes:
    return rebuild(fr.bom, fr.header_raw, fr.terminator, ((r.fields, r.raw) for r in fr.records))


def strict_record_count(raw: bytes) -> int | None:
    """Independent count of data records with Python's csv module (strict); None if it cannot parse.

    It shares no code with split_records, so agreement between the two is evidence, not tautology.
    """
    try:
        text = raw.decode("utf-8-sig")
        return max(sum(1 for _ in csv.reader(io.StringIO(text, newline=""), strict=True)) - 1, 0)
    except (UnicodeDecodeError, csv.Error):
        return None
