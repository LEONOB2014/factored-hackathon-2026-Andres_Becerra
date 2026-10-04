"""latam_eda.mutations: each synthetic mutation changes exactly what it claims, keeping the dialect."""

import csv
import io

import pytest

from latam_eda import mutations as mu
from latam_eda import raw_forensics as rf

HEADER = (
    "transaction_id,transaction_date,process_date,amount,currency,transaction_type,response_code"
)
ROWS = [
    "T1,2024-01-01 09:00:00,2024-01-01,10.50,USD,Purchase,05",
    "T2,2024-01-01 10:00:00,2024-01-01,3.25,COP,Transfer,00",
]


@pytest.fixture
def src(tmp_path):
    p = tmp_path / "src" / "t.csv"
    p.parent.mkdir()
    p.write_bytes(b"\xef\xbb\xbf" + ("\r\n".join([HEADER, *ROWS]) + "\r\n").encode())
    return p


def rows_of(path):
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig"), newline="")))


def by_name(name):
    return next(m for m in mu.transactions_catalogue() if m.name == name)


def test_verbatim_copy_is_byte_identical(src, tmp_path):
    mu.rewrite(src, tmp_path / "out.csv", None)
    assert (tmp_path / "out.csv").read_bytes() == src.read_bytes()


@pytest.mark.parametrize(
    ("name", "column", "expected"),
    [
        ("rename_category", "transaction_type", ["Compra", "Transfer"]),
        ("decimal_comma", "amount", ["10,50", "3,25"]),
        ("date_format_dmy", "process_date", ["01/01/2024", "01/01/2024"]),
        (
            "timezone_suffix",
            "transaction_date",
            ["2024-01-01 09:00:00-05:00", "2024-01-01 10:00:00-05:00"],
        ),
        ("unit_x1000", "amount", ["10500.00", "3250.00"]),
        ("swap_columns", "amount", ["USD", "COP"]),
        ("lost_leading_zeros", "response_code", ["5", "0"]),
    ],
)
def test_row_mutations_keep_bom_and_crlf(src, tmp_path, name, column, expected):
    out = tmp_path / "out.csv"
    mu.rewrite(src, out, by_name(name))
    assert [r[column] for r in rows_of(out)] == expected
    s = rf.scan_file(out)
    assert s.bom and s.lf == 0 and s.records == 2 and s.ragged == 0


def test_file_mutations(src, tmp_path):
    for name, check in [
        ("bom_removed", lambda s: not s.bom and s.records == 2),
        ("ragged_rows", lambda s: s.ragged == 1),
        ("unterminated_quote", lambda s: s.grammar_error is not None),
    ]:
        out = tmp_path / f"{name}.csv"
        mu.rewrite(src, out, by_name(name))
        assert check(rf.scan_file(out)), name
