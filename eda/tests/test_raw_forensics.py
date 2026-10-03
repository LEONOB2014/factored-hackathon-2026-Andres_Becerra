"""latam_eda.raw_forensics on crafted CSVs (no dataset): classes, lattice, L0 scan, contracts."""

import duckdb
import pytest

from latam_eda import raw_forensics as rf


def write(tmp_path, name, text, bom=True, crlf=True):
    body = text.replace("\n", "\r\n") if crlf else text
    p = tmp_path / name
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body.encode())
    return p


@pytest.mark.parametrize(
    ("value", "cls"),
    [
        ("", "empty"),
        ("N/A", "null_token"),
        ("true", "bool"),
        ("007", "int_leading_zero"),
        ("-42", "int"),
        ("10.5", "dec_dot"),
        ("10,5", "dec_comma"),
        ("1.234.567,89", "dec_thousands"),
        ("1.5e3", "sci"),
        ("2024-01-31", "date_iso"),
        ("31/01/2024", "date_dmy"),
        ("2024-01-31 09:15:00.123", "ts_space"),
        ("2024-01-31T09:15:00", "ts_t"),
        ("2024-01-31 09:15:00-05:00", "ts_tz"),
        ("09:15", "time"),
        ("09:15:00", "time"),
        ('{"a": 1}', "json"),
        ("201.123.456.7", "ipv4"),
        ("2001:db8::1", "ipv6"),
        ("https://bank.example/login", "url"),
        ("México", "text"),
    ],
)
def test_value_classes(value, cls):
    con = duckdb.connect()
    got = con.execute(f"select {rf.class_case('v')} from (select ? as v)", [value]).fetchone()[0]
    assert got == cls


def test_scan_counts_records_by_grammar_and_reads_the_bytes(tmp_path):
    p = write(tmp_path, "a.csv", 'id,note\nT1,"two\nlines"\nT2,x\n')
    s = rf.scan_file(p)
    assert (s.records, s.multiline_records, s.ragged) == (2, 1, 0)
    assert s.bom and s.crlf == 4 and s.lf == 0 and s.utf8_errors == 0
    assert s.header == ["id", "note"] and not s.header_bom_in_name


def test_scan_flags_ragged_rows_and_bad_utf8(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_bytes(b"id,amount\nT1,1\nT2,2,3\nT3,\xff\n")
    s = rf.scan_file(p)
    assert s.ragged == 1 and s.utf8_errors == 1 and not s.bom


def test_lexical_profile_keeps_empty_strings_and_counts_classes(tmp_path):
    p = write(tmp_path, "a.csv", 'id,amount,code\nT1,10.5,007\nT2,,012\nT3,"3,5",9\n')
    prof = rf.lexical_profile(duckdb.connect(), [p])
    a = prof[prof.column == "amount"].iloc[0]
    assert (a.n_empty, a.n_dec_dot, a.n_dec_comma) == (1, 1, 1)
    c = prof[prof.column == "code"].iloc[0]
    assert (c.n_int_leading_zero, c.n_int) == (2, 1)


def test_infer_type_follows_the_lattice():
    assert rf.infer_type({"int": 99}) == ("integer", 1.0)
    assert rf.infer_type({"int": 50, "dec_dot": 50, "empty": 400})[0] == "decimal"
    assert rf.infer_type({"date_iso": 10, "ts_space": 990})[0] == "timestamp"
    # leading zeros are codes: no numeric type may hold them
    assert rf.infer_type({"int_leading_zero": 90, "int": 10})[0] == "string"
    # one decimal comma in 10,000 keeps the decimal type (coverage 0.9999) ...
    assert rf.infer_type({"dec_dot": 9999, "dec_comma": 1})[0] == "decimal"
    # ... but 1% does not
    assert rf.infer_type({"dec_dot": 99, "dec_comma": 1})[0] == "string"


def test_contract_and_minority_formats(tmp_path):
    rows = "".join(f"T{i},{i}.25\n" for i in range(2000))
    p1 = write(tmp_path, "d1.csv", "id,amount\n" + rows)
    p2 = write(tmp_path, "d2.csv", "id,amount\n" + rows + 'T9,"7,5"\n')
    con = duckdb.connect()
    prof = rf.lexical_profile(con, [p1, p2])
    contract = rf.table_contract("t", prof, ["id", "amount"])
    assert contract["columns"]["amount"]["type"] == "decimal"
    assert (
        contract["contract_version"]
        == rf.table_contract("t", prof, ["id", "amount"])["contract_version"]
    )
    m = rf.minority_formats(prof, contract)
    assert m[["column", "found_class", "n"]].values.tolist() == [["amount", "dec_comma", 1]]
    assert m["file"].iloc[0].endswith("d2.csv")


def test_variants_and_key_shapes():
    assert rf.variant_groups(["México", "Mexico", "MEXICO", "Chile"]) == {
        "mexico": ["MEXICO", "Mexico", "México"]
    }
    assert rf.key_shape("TRX-A9B0") == "AAA-A9A9"


def test_partition_date_from_hive_path(tmp_path):
    assert rf.partition_date(tmp_path / "t/year=2024/month=03/day=09/x.csv") == "2024-03-09"
    assert rf.partition_date(tmp_path / "customers.csv") is None
