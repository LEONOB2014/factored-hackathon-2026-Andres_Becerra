"""latam_eda.correction_workbench on a tiny in-memory audit schema (no dataset)."""

import json

import duckdb
import pytest

from latam_eda import correction_workbench as wb


@pytest.fixture
def con():
    c = duckdb.connect()
    c.sql("CREATE SCHEMA audit")
    c.sql("""CREATE TABLE audit.dq_cell_findings AS SELECT * FROM (VALUES
        ('bronze', 'transactions', DATE '2025-01-01', 'f1.csv', 1, 'TRX-1', 'transaction_country', 'V2', 'Mexico', NULL),
        ('bronze', 'transactions', DATE '2025-01-02', 'f2.csv', 7, 'TRX-7', 'transaction_country', 'V2', 'Mexico', 'cp-1'),
        ('bronze', 'customers', DATE '2026-06-17', 'c.csv', 3, 'CLI-3', 'email', 'K', 'shape:AAA@AAA.AA', NULL))
        t(zone, table_name, partition_date, source_file, record_no, entity_id, column_name, issue_code, raw_value,
          correction_proposal_id)""")
    yield c


def test_pattern_groups_count_cells_and_mark_personal_data(con):
    g = wb.pattern_groups(con).set_index(["table_name", "column_name"])
    mexico = g.loc[("transactions", "transaction_country")]
    assert (mexico.cells, mexico.partitions, mexico.already_corrected, bool(mexico.pii)) == (
        2,
        2,
        1,
        False,
    )
    assert bool(g.loc[("customers", "email")].pii) is True
    assert len(wb.records(con, "transactions", "transaction_country", "Mexico")) == 2


def test_proposals_are_complete_and_never_overwritten(tmp_path):
    p = wb.pattern_proposal(
        "cp-mexico", "transactions", "transaction_country", "Mexico", "México", "variant"
    )
    path = wb.write_proposal(p, tmp_path)
    assert json.loads(path.read_text())["pattern"]["to_value"] == "México"
    with pytest.raises(FileExistsError):
        wb.write_proposal(p, tmp_path)
    with pytest.raises(ValueError, match="shape"):
        wb.pattern_proposal("cp-x", "customers", "email", "shape:AAA", "a@b.co", "fix")
    with pytest.raises(ValueError, match="reason"):
        wb.revert_proposal("cp-undo", ["cp-mexico"], " ")
    with pytest.raises(ValueError, match="proposal_id"):
        wb.release_proposal("Bad Id", "transactions", "2025-01-01", "reviewed")
    assert "steward" in wb.next_step("cp-mexico")
