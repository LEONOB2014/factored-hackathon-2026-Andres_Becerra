"""latam_eda.csvio: CSV -> Parquet never loses, reshapes or silently re-types rows.

Each malformed case below is one DuckDB's lenient reader accepted without an error (probed on
duckdb 1.5): the conversion must refuse it instead.
"""

import duckdb
import pytest

from latam_eda.csvio import CsvIntegrityError, count_records, csv_to_parquet, type_demotions

CLEAN = "id,amount\nT0,1.0\n"


def files(tmp_path, *bodies, sub="."):
    folder = tmp_path / sub
    folder.mkdir(exist_ok=True)
    paths = []
    for i, body in enumerate(bodies):
        p = folder / f"part-{i}.csv"
        p.write_text(body, encoding="utf-8")
        paths.append(p)
    return paths


def test_records_are_counted_by_grammar_not_lines(tmp_path):
    (p,) = files(tmp_path, 'id,note\nT1,"two\nlines"\nT2,plain\n')
    assert count_records(p) == (2, 0)


def test_bom_is_not_part_of_the_first_column(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes("﻿id,amount\nT1,1.5\n".encode())
    out = tmp_path / "bom.parquet"
    assert csv_to_parquet(duckdb.connect(), [p], out) == 1
    cols = [r[0] for r in duckdb.sql(f"describe select * from '{out}'").fetchall()]
    assert cols == ["id", "amount"]


def test_clean_files_convert_with_types(tmp_path):
    out = tmp_path / "ok.parquet"
    assert csv_to_parquet(duckdb.connect(), files(tmp_path, CLEAN, "id,amount\nT1,2.5\n"), out) == 2
    assert duckdb.sql(f"select typeof(amount) from '{out}' limit 1").fetchone()[0] == "DOUBLE"


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("id,amount\nT1,10.5\nT2,3,x\n", id="extra-field"),
        pytest.param("id,amount\nT1,10.5\nT2\n", id="missing-field"),
        pytest.param('id,amount\nT1,"10.5\nT2,3\n', id="unterminated-quote"),
    ],
)
def test_structural_damage_is_refused(tmp_path, bad):
    out = tmp_path / "bad.parquet"
    with pytest.raises(CsvIntegrityError):
        csv_to_parquet(duckdb.connect(), files(tmp_path, CLEAN, bad), out)
    assert not out.exists()


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(
            "id,amount\n" + "".join(f"T{i},{i}.5\n" for i in range(200)) + "T9,abc\n",
            id="bad-number",
        ),
        pytest.param(
            "id,amount\n" + "".join(f"T{i},{i}.5\n" for i in range(200)) + 'T9,"3,5"\n',
            id="decimal-comma",
        ),
    ],
)
def test_a_column_demoted_to_text_by_a_few_values_is_refused(tmp_path, bad):
    out = tmp_path / "demoted.parquet"
    with pytest.raises(CsvIntegrityError, match="demoted to VARCHAR"):
        csv_to_parquet(duckdb.connect(), files(tmp_path, CLEAN, bad), out)
    assert not out.exists()


def test_union_by_name_accepts_a_gained_column_but_not_lost_rows(tmp_path):
    con = duckdb.connect()
    gained = files(tmp_path, CLEAN, "id,amount,channel\nT1,2.0,web\n")
    assert csv_to_parquet(con, gained, tmp_path / "gained.parquet", union_by_name=True) == 2
    ragged = files(tmp_path, CLEAN, "id,amount\nT1,1.0\nT2,3,x\n", sub="ragged")
    with pytest.raises(CsvIntegrityError):
        csv_to_parquet(con, ragged, tmp_path / "ragged.parquet", union_by_name=True)


def test_type_demotions_ignores_genuine_text(tmp_path):
    out = tmp_path / "text.parquet"
    duckdb.sql(
        f"copy (select * from (values ('A1'), ('B2'), ('C3')) t(code)) to '{out}' (format parquet)"
    )
    assert type_demotions(duckdb.connect(), out) == []
