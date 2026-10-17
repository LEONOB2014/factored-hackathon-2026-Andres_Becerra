"""db.connect() applies latam_eda's bounded DuckDB profile and spills to the given directory (eng review E4)."""

import duckdb

from latam_eda import pipeline
from report_lib import (
    db,
    eda,  # noqa: F401
)


def _setting(con, name):
    return con.sql(f"SELECT current_setting('{name}')").fetchone()[0]


def test_bounded_profile_and_temp_directory(tmp_path):
    con = db.connect(tmp_path / "spill")
    ref = duckdb.connect()
    for k, v in pipeline.SETTINGS.items():
        ref.sql(f"SET {k} = '{v}'")
    for k in pipeline.SETTINGS:
        assert _setting(con, k) == _setting(ref, k), k
    assert _setting(con, "temp_directory") == (tmp_path / "spill").as_posix()
