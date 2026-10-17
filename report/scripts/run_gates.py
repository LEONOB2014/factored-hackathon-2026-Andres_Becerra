"""Registered re-estimation of the readiness gates, with the protocol's runner-failure rule.

Runs every scenario of latam_eda.hour_models exactly as eda/scripts/readiness_check.py --cluster does (same session,
star, functions, bootstrap and verdict), except that a scenario that raises is recorded as "not assessable" with its
error as the root cause instead of aborting the scorecard (protocol.toml, gates.runner_failure). Run it in the eda
environment, which has the scenarios' dependencies:

    cd eda && uv run python ../report/scripts/run_gates.py --dataset backup
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eda" / "src"))

from latam_eda import country  # noqa: E402
from latam_eda import granularity as g  # noqa: E402
from latam_eda import hour_models as hm  # noqa: E402
from latam_eda import pipeline as pipe  # noqa: E402

PUBLISHED = (
    Path(__file__).resolve().parents[2]
    / "eda"
    / "reports"
    / "tables"
    / "granularity_hour_readiness.csv"
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", default="main", choices=["main", "backup"])
    ap.add_argument("--nan-share-max", type=float, default=hm.NAN_SHARE_MAX)
    a = ap.parse_args()
    out = (
        pipe.repo_root(Path.cwd())
        / "data"
        / "derived"
        / "readiness"
        / f"hour_readiness_{a.dataset}_all_cluster.csv"
    )
    t0 = time.time()
    pl = country.session("ALL", a.dataset)
    country.prepare(pl, "gold")
    star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])
    star.build(verbose=False)
    checks = star.check()
    if not checks.ok.all():
        print(checks[~checks.ok].to_string())
        raise SystemExit("the hour star does not pass its checks")
    published = pd.read_csv(PUBLISHED)
    rows = []
    for name, fn in hm.SCENARIOS.items():
        try:
            rows.extend(fn(star, cluster=True, nan_share_max=a.nan_share_max)[0])
        except Exception as exc:  # the runner-failure rule: record, do not abort
            for r in published[published.scenario == name].itertuples():
                rows.append({"scenario": name, "model": r.model, "metric": r.metric, "benchmark": r.benchmark,
                             "verdict": "not assessable",
                             "root_cause": f"scenario raised {type(exc).__name__}: {str(exc)[:120]}"})  # fmt: skip
    pl.close()
    sc = pd.DataFrame(rows)
    num = sc.select_dtypes("number").columns
    sc[num] = sc[num].round(6)
    sc = sc.sort_values(["scenario", "model"], kind="stable").reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    sc.to_csv(out, index=False)
    print(sc[["scenario", "model", "verdict", "root_cause"]].to_string(index=False))
    print(f"-> {out} ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
