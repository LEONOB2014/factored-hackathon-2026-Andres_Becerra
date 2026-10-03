"""Contract-driven silver: the reviewed source contracts, the SQL generated from them, and the drift breaker.

No dataset needed: the generated SQL runs in an in-memory DuckDB over a handful of raw-text records, and the
drift / hold models run over synthetic partition profiles.
"""

from __future__ import annotations

import importlib.util
import math
import re
from pathlib import Path

import duckdb
import jinja2
import pytest
import yaml

DBT = Path(__file__).resolve().parents[2] / "dbt"
CONTRACTS = DBT.parent / "contracts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, DBT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate_silver_from_contracts")
VC = gen.value_classes()

TOY = {
    "table": "toy",
    "kind": "fact",
    "entity_key": ["id"],
    "contract_version": "toyversion01",
    "columns": {
        "id": {"type": "VARCHAR", "required": True, "key_pattern": "^TOY-[0-9A-Z]{4}$"},
        "ts": {"type": "TIMESTAMP", "required": True, "formats": ["ts_space"]},
        "amount": {"type": "DOUBLE", "required": False, "formats": ["int", "dec_dot", "sci"]},
        "flag": {"type": "BOOLEAN", "required": False, "formats": ["bool"]},
        "country": {
            "type": "VARCHAR",
            "required": False,
            "vocabulary": ["Colombia", "México"],
            "variants": {"Mexico": "México"},
        },
        "phone": {
            "type": "VARCHAR",
            "required": False,
            "pii": "phone",
            "key_pattern": "^[0-9]{10}$",
        },
        "subject": {"type": "VARCHAR", "required": False, "scan": ["null_word", "slot"]},
    },
}
COLS = list(TOY["columns"])
# raw text as lossless bronze stores it; None = the column was absent from the file's header
ROWS = [
    # record_no, status, id, ts, amount, flag, country, phone, subject
    (1, "ok", "TOY-AB12", "2024-01-01 10:00:00", "12.5", "True", "México", "5512345678", "Hola"),
    (2, "ok", "TOY-AB13", "2024-01-01T10:00:00", "12,5", "1", "Mexico", "", "Oferta en nan!"),
    (3, "ok", "X-1", "2024-01-01 11:00:00", "", "", "Peru", "call me 55", "Hola {nombre}"),
    (4, "ok", "", None, "1e3", "False", "", "", ""),
    (5, "ragged", "TOY-AB14", "2024-01-01 12:00:00", "7", "True", "Colombia", "5598765432", "Hola"),
]


def _raw_table(con: duckdb.DuckDBPyConnection, rows=ROWS, name: str = "src") -> None:
    cols = ", ".join(f"{c} VARCHAR" for c in COLS)
    con.sql(f"""CREATE OR REPLACE TABLE {name} ({cols}, _partition_date VARCHAR, _source_file VARCHAR,
                _record_no BIGINT, _record_sha256 VARCHAR, _parse_status VARCHAR, _raw_record VARCHAR)""")
    for no, status, *vals in rows:
        con.execute(
            f"INSERT INTO {name} VALUES ({', '.join('?' * (len(COLS) + 6))})",
            [
                *vals,
                "2024-01-01",
                "data/toy/f.csv",
                no,
                f"sha{no}",
                status,
                "raw,record" if status != "ok" else None,
            ],
        )


def _sql(text: str, table: str = "src") -> str:
    return re.sub(r"\{\{ source\('\w+', '\w+'\) \}\}", table, text)


@pytest.fixture
def con():
    c = duckdb.connect()
    _raw_table(c)
    yield c
    c.close()


# --------------------------------------------------------------------------------------- contracts
def test_generated_dbt_files_match_the_contracts():
    assert gen.stale(gen.render_all()) == [], "run scripts/generate_silver_from_contracts.py"


def test_value_classes_compile_and_contracts_are_well_formed():
    for rx in [*VC["classes"].values(), *VC["scans"].values()]:
        duckdb.sql(f"SELECT regexp_matches('x', '{rx.replace(chr(39), chr(39) * 2)}')")
    pii = {
        line.split(",")[0]
        for line in (DBT / "seeds" / "restricted_pii_columns.csv").read_text().splitlines()[1:]
    }
    for path in sorted((CONTRACTS / "sources").glob("*.yml")):
        c = yaml.safe_load(path.read_text())
        assert path.stem == c["table"]
        assert set(c["entity_key"]) <= set(c["columns"]), path.name
        for col, spec in c["columns"].items():
            assert spec["type"] in {
                "VARCHAR",
                "DOUBLE",
                "BIGINT",
                "BOOLEAN",
                "DATE",
                "TIMESTAMP",
                "TIME",
            }
            assert set(spec.get("formats", [])) <= set(VC["classes"]), (path.name, col)
            assert set(spec.get("scan", [])) <= set(VC["scans"]), (path.name, col)
            assert set(spec.get("variants", {}).values()) <= set(spec.get("vocabulary", [])), (
                path.name,
                col,
            )
            assert not (set(spec.get("variants", {})) & set(spec.get("vocabulary", []))), (
                path.name,
                col,
            )
            if col in pii:  # personal data is never enumerated into the contract
                assert "vocabulary" not in spec and spec.get("pii"), (path.name, col)


# ------------------------------------------------------------------------------------------- typed
def test_typed_model_casts_and_flags_every_breach(con):
    rows = con.sql(_sql(gen.typed_model("bronze_raw", TOY, VC))).fetchall()
    cols = [d[0] for d in con.sql(_sql(gen.typed_model("bronze_raw", TOY, VC))).description]
    by_no = {r[cols.index("_record_no")]: dict(zip(cols, r, strict=True)) for r in rows}
    assert len(by_no) == len(ROWS), "every bronze record is kept, flagged or not"
    issues = {no: sorted(r["_dq_issues"]) for no, r in by_no.items()}
    assert issues[1] == []
    assert issues[2] == sorted(["ts:F", "amount:T", "flag:F", "country:V2", "subject:P"])
    assert issues[3] == sorted(["id:K", "country:V1", "phone:K", "subject:S"])
    assert issues[4] == sorted(["id:N", "ts:N"])
    assert issues[5] == ["*:G"]
    assert by_no[1]["amount"] == 12.5 and by_no[1]["flag"] is True
    assert by_no[2]["amount"] is None, "a value that does not cast becomes NULL (and a finding)"
    assert by_no[4]["amount"] == 1000.0 and by_no[4]["ts"] is None
    assert by_no[3]["amount"] is None and by_no[2]["phone"] is None, (
        "'' becomes NULL, as in typed bronze"
    )


def test_findings_keep_lineage_and_only_the_shape_of_personal_data(con):
    rows = con.sql(_body(_sql(gen.findings_model({"toy": TOY}, VC)))).fetchall()
    cols = [d[0] for d in con.sql(_body(_sql(gen.findings_model({"toy": TOY}, VC)))).description]
    f = [dict(zip(cols, r, strict=True)) for r in rows]
    got = {(r["record_no"], r["column_name"], r["issue_code"]): r["raw_value"] for r in f}
    assert len(f) == 12  # 5 + 4 + 2 + 1 breaches in records 2-5
    assert got[(2, "amount", "T")] == "12,5"
    assert got[(2, "subject", "P")] == "Oferta en nan!"
    assert got[(2, "country", "V2")] == "Mexico"
    assert got[(3, "phone", "K")] == "shape:AAAA AA 99", "personal data only as a shape"
    assert got[(5, "*", "G")].startswith("shape:")
    assert all(r["source_file"] == "data/toy/f.csv" and r["record_sha256"] for r in f)
    assert {r["entity_id"] for r in f if r["record_no"] == 2} == {"TOY-AB13"}


def _body(sql: str) -> str:
    """The SQL of a generated model without its leading comment block."""
    return "\n".join(line for line in sql.splitlines() if not line.startswith("--"))


# ----------------------------------------------------------------------------------------- profile
def test_partition_profile_counts_what_the_drift_checks_read(con):
    p = con.sql(_body(_sql(gen.profile_model({"toy": TOY}, VC)))).df().set_index("column_name")
    assert set(p["n_rows"]) == {5} and set(p["n_grammar"]) == {1}
    assert (
        p.loc["amount", "n_cast"] == 1
        and p.loc["ts", "n_format"] == 1
        and p.loc["flag", "n_format"] == 1
    )
    assert p.loc["ts", "n_absent"] == 1 and p.loc["amount", "n_empty"] == 1
    assert (
        p.loc["id", "n_key"] == 1
        and p.loc["country", "n_unknown"] == 1
        and p.loc["country", "n_variant"] == 1
    )
    assert p.loc["subject", "n_placeholder"] == 2
    assert p.loc["amount", "log10_median"] == pytest.approx(
        math.log10(12.5)
    )  # median of 12.5, 1000, 7


# ------------------------------------------------------------------------------- drift and holds
def _render(model: str, **tables: str) -> str:
    text = (DBT / "models" / "silver" / "quality" / f"{model}.sql").read_text()
    env = jinja2.Environment(autoescape=False)  # noqa: S701  renders SQL, not HTML
    return env.from_string(text).render(
        ref=lambda name: tables.get(name, name),
        var=lambda name: {"stream_cutoff": "2026-05-18", "data_end": "2026-06-17"}[name],
        env_var=lambda name, default=None: default,
    )


def _profile_row(day: str, column: str, **kw) -> dict:
    base = {"zone": "bronze", "table_name": "tx", "contract_version": "v", "partition_date": day,
            "n_rows": 1000, "n_grammar": 0, "column_name": column, "n_absent": 0, "n_empty": 0, "n_cast": 0,
            "n_format": 0, "n_key": 0, "n_unknown": 0, "n_variant": 0, "n_placeholder": 0, "n_nonzero": 1000,
            "log10_median": 2.0}  # fmt: skip
    return {**base, **kw}


@pytest.fixture
def drift_con():
    c = duckdb.connect()
    c.sql("""CREATE TABLE source_contract_columns AS SELECT * FROM (VALUES
        ('tx', 'amount',  1, 'DOUBLE',  true,  0.0, false, false, '', 2.0, 0.02, 'v'),
        ('tx', 'channel', 2, 'VARCHAR', true,  0.0, true,  false, '', NULL, NULL, 'v'),
        ('tx', 'note',    3, 'VARCHAR', false, 0.2, false, false, '', NULL, NULL, 'v'))
        t(table_name, column_name, ordinal, data_type, required, empty_share, enumerated, keyed, pii_type,
          scale_log10_median, scale_mad, contract_version)""")
    rows = [
        _profile_row("2025-01-01", "amount"),                                   # clean
        _profile_row("2025-01-02", "amount", n_cast=40),                        # decimal comma: 4 % do not cast
        _profile_row("2025-01-03", "amount", log10_median=5.0),                 # x1000 (unit change)
        _profile_row("2025-01-04", "channel", n_unknown=600, n_nonzero=0),      # vocabulary translated
        _profile_row("2025-01-05", "channel", n_unknown=3, n_nonzero=0),        # a rare new category
        _profile_row("2025-01-06", "note", n_empty=800, n_nonzero=0),           # empty share +60 pp (B)
        _profile_row("2025-01-07", "amount", n_grammar=2),                      # broken CSV grammar
        _profile_row("2025-01-08", "amount", n_absent=1000, n_nonzero=0),       # column gone from the file
    ]  # fmt: skip
    import pandas as pd

    profile = pd.DataFrame(rows)  # noqa: F841
    c.sql("CREATE TABLE dq_partition_profile AS SELECT *, partition_date::date AS pd FROM profile")
    c.sql(
        "ALTER TABLE dq_partition_profile DROP partition_date; ALTER TABLE dq_partition_profile RENAME pd TO partition_date"
    )
    c.sql("""CREATE TABLE dq_partition_header AS SELECT * FROM (VALUES
        ('tx', DATE '2025-01-09', 'data/tx/year=2025/month=01/day=09/tx.csv', ['amount', 'channel', 'note', 'extra'],
         []::VARCHAR[], ['extra'], false),
        ('tx', DATE '2025-01-01', 'data/tx/year=2025/month=01/day=01/tx.csv', ['amount', 'channel', 'note'],
         []::VARCHAR[], []::VARCHAR[], false))
        t(table_name, partition_date, source_file, header, missing_columns, extra_columns, reordered)""")
    c.sql("CREATE TABLE dq_partition_releases (table_name VARCHAR, partition_date DATE, released_by VARCHAR, "
          "approved_by VARCHAR, released_on DATE, reason VARCHAR, ticket VARCHAR)")  # fmt: skip
    yield c
    c.close()


def test_drift_holds_severe_schema_changes_and_only_reports_mild_ones(drift_con):
    drift_con.sql(f"CREATE TABLE dq_schema_drift AS {_render('dq_schema_drift')}")
    got = {
        (str(d), check, sev)
        for d, check, sev in drift_con.sql(
            "SELECT partition_date, check_name, severity FROM dq_schema_drift"
        ).fetchall()
    }
    assert ("2025-01-02", "format", "A") in got
    assert ("2025-01-03", "scale", "A") in got
    assert ("2025-01-04", "vocabulary", "A") in got
    assert ("2025-01-05", "vocabulary", "B") in got
    assert ("2025-01-06", "empty_share", "B") in got
    assert ("2025-01-07", "grammar", "A") in got
    assert ("2025-01-08", "absent", "A") in got and ("2025-01-08", "required_empty", "A") not in got
    assert ("2025-01-09", "header_extra", "A") in got
    assert not any(d == "2025-01-01" for d, _, _ in got), "a clean partition raises nothing"

    def held() -> set[str]:
        sql = f"SELECT partition_date FROM ({_render('dq_partition_holds')})"
        return {str(d) for (d,) in drift_con.sql(sql).fetchall()}

    assert held() == {
        "2025-01-02",
        "2025-01-03",
        "2025-01-04",
        "2025-01-07",
        "2025-01-08",
        "2025-01-09",
    }
    drift_con.sql("INSERT INTO dq_partition_releases VALUES ('tx', '2025-01-03', 'steward', 'risk', '2025-01-10', "
                  "'confirmed restatement to cents', 'DQ-1')")  # fmt: skip
    assert "2025-01-03" not in held(), "a reviewed release lifts the hold"
