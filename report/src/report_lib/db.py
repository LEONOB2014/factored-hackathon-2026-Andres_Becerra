"""One DuckDB connection for scripted re-runs: latam_eda's main and backup views with the bounded profile.

`latam_eda.pipeline.SETTINGS` (4 GB memory, 6 GB spill, 4 threads) is the profile proven on the 16 GB laptop;
spill goes to build/tmp.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from report_lib import eda as _eda  # noqa: F401  (puts ../eda/src on sys.path)
from report_lib.paths import BUILD


def connect(temp_dir: Path = BUILD / "tmp") -> duckdb.DuckDBPyConnection:
    from latam_eda import data, pipeline

    temp_dir.mkdir(parents=True, exist_ok=True)
    con = data.connect()
    for k, v in pipeline.SETTINGS.items():
        con.sql(f"SET {k} = '{v}'")
    con.sql(f"SET temp_directory = '{temp_dir.as_posix()}'")
    return con
