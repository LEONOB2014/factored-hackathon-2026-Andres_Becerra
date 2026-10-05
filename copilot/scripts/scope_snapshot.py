"""Cut the demo snapshot by country, for a regional deployment that holds only its own countries' data.

Residency (knowledge/std-data-residency, ADR-007): a country's customer data is stored and processed only in the
regions approved for it. Mexico: northamerica-south1 (Querétaro). Colombia and Argentina have no in-country region;
the proposed one is southamerica-east1 (São Paulo), under a documented international-transfer basis.

    cd copilot && uv run python scripts/scope_snapshot.py MX          # data/copilot/scopes/mx/snapshot.duckdb
    uv run python scripts/scope_snapshot.py CO AR --name sa           # data/copilot/scopes/sa/snapshot.duckdb
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = Path(os.environ.get("COPILOT_SNAPSHOT", REPO / "data" / "copilot" / "snapshot.duckdb"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("countries", nargs="+", help="country codes kept, e.g. MX, or CO AR")
    ap.add_argument("--name", help="scope folder name (default: the codes joined)")
    args = ap.parse_args()
    codes = sorted({c.upper() for c in args.countries})
    out = SNAPSHOT.parent / "scopes" / (args.name or "-".join(codes).lower()) / "snapshot.duckdb"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = duckdb.connect(str(out))
    con.execute(f"attach '{SNAPSHOT}' as src (read_only)")
    con.execute(
        "create table cards as select * from src.cards where country_code in (select unnest(?))",
        [codes],
    )
    con.execute(
        "create table meta as select m.as_of, ? as exported_at, m.source || ' (scope ' || ? || ')' as source, "
        "(select count(distinct customer_id) from cards) as customers, (select count(*) from cards) as cards "
        "from src.meta m",
        [datetime.now(UTC).isoformat(), ",".join(codes)],
    )
    got = con.execute(
        "select country_code, count(distinct customer_id), count(*) from cards group by 1 order by 1"
    ).fetchall()
    con.execute("detach src")
    con.close()
    print(f"wrote {out}: {got}")


if __name__ == "__main__":
    main()
