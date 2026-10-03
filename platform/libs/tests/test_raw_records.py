"""Byte-exact record splitting and file reconstruction (no dataset, no services)."""

from __future__ import annotations

import hashlib

import pytest

from latam_platform.lakehouse import raw_records as rr

BOM = rr.BOM

CASES = {
    "crlf_with_bom": BOM + b"id,amount\r\nT1,10.5\r\nT2,\r\n",
    "lf_without_bom": b"id,amount\nT1,10.5\nT2,3\n",
    "quoted_lf_inside_field": BOM + b'id,note\r\nT1,"two\nlines"\r\nT2,x\r\n',
    "quoted_crlf_inside_field": b'id,note\r\nT1,"two\r\nlines"\r\nT2,x\r\n',
    "escaped_quotes": b'id,json\r\nT1,"{""a"": 1, ""b"": ""x,y""}"\r\n',
    "empty_fields": b"a,b,c\r\n,,\r\nx,,\r\n",
    "no_final_terminator": b"id,amount\r\nT1,1\r\nT2,2",
    "header_only": BOM + b"id,amount\r\n",
    "empty_file": b"",
    "ragged_rows": b"id,amount\r\nT1,1\r\nT2,2,extra\r\nT3\r\n",
    "invalid_utf8": b"id,name\r\nT1,ok\r\nT2,\xff\xfe\r\n",
    "unterminated_quote_at_eof": b'id,note\r\nT1,ok\r\nT2,"never closed\r\n',
    "unnecessary_quotes": b'id,name\r\n"T1","Ana"\r\n',
    "blank_line": b"id,amount\r\nT1,1\r\n\r\nT2,2\r\n",
    "mixed_terminators": b"id,amount\r\nT1,1\nT2,2\r\n",
    "accents_and_bom": BOM + "id,país\r\nT1,México\r\n".encode(),
}


@pytest.mark.parametrize("name", CASES)
def test_every_file_rebuilds_byte_for_byte(name):
    raw = CASES[name]
    fr = rr.read_file(raw)
    assert hashlib.sha256(rr.rebuild_file(fr)).digest() == hashlib.sha256(raw).digest()


def test_quoted_newlines_stay_inside_one_record():
    fr = rr.read_file(CASES["quoted_lf_inside_field"])
    assert [r.fields for r in fr.records] == [["T1", "two\nlines"], ["T2", "x"]]
    assert all(
        r.status == "ok" and r.raw is None for r in fr.records
    )  # canonical: no verbatim copy


def test_bom_and_terminator_are_recorded():
    fr = rr.read_file(CASES["crlf_with_bom"])
    assert fr.bom and fr.terminator == b"\r\n" and fr.header == ["id", "amount"]
    assert fr.records[1].fields == ["T2", ""]  # the empty field stays an empty string


@pytest.mark.parametrize(
    ("name", "statuses"),
    [
        ("ragged_rows", ["ok", "ragged", "ragged"]),
        ("invalid_utf8", ["ok", "encoding_error"]),
        ("unterminated_quote_at_eof", ["ok", "quote_error"]),
        ("blank_line", ["ok", "ragged", "ok"]),
    ],
)
def test_damaged_records_are_classified_and_kept_verbatim(name, statuses):
    fr = rr.read_file(CASES[name])
    assert [r.status for r in fr.records] == statuses
    for r in fr.records:
        if r.status != "ok":
            assert r.raw is not None and r.fields is None


def test_non_canonical_records_are_kept_verbatim():
    fr = rr.read_file(CASES["unnecessary_quotes"])
    (rec,) = fr.records
    assert rec.status == "ok" and rec.fields == ["T1", "Ana"]
    assert rec.raw == b'"T1","Ana"\r\n'  # minimal quoting would drop the quotes


def test_counts_and_record_hashes():
    raw = CASES["ragged_rows"]
    fr = rr.read_file(raw)
    assert fr.counts() == {
        "ok": 1,
        "ragged": 2,
        "quote_error": 0,
        "encoding_error": 0,
        "records": 3,
        "verbatim": 2,
    }
    first = raw.split(b"\r\n")[1] + b"\r\n"
    assert fr.records[0].sha256 == hashlib.sha256(first).hexdigest()


@pytest.mark.parametrize(
    "name",
    ["crlf_with_bom", "quoted_lf_inside_field", "escaped_quotes", "header_only", "blank_line"],
)
def test_independent_count_agrees_with_the_splitter(name):
    raw = CASES[name]
    assert rr.strict_record_count(raw) == len(rr.read_file(raw).records)


def test_independent_count_refuses_unparsable_files():
    assert rr.strict_record_count(CASES["invalid_utf8"]) is None
    assert rr.strict_record_count(CASES["unterminated_quote_at_eof"]) is None


def test_a_tampered_record_breaks_the_rebuild():
    raw = CASES["crlf_with_bom"]
    fr = rr.read_file(raw)
    fr.records[0].fields = ["T1", "10.6"]
    assert rr.rebuild_file(fr) != raw


def test_long_fields_parse():
    big = "x" * 300_000
    raw = f'id,text\r\nT1,"{big}"\r\n'.encode()
    fr = rr.read_file(raw)
    assert fr.records[0].fields == ["T1", big] and rr.rebuild_file(fr) == raw
