"""Re-run the hour-grain readiness scorecard on a lake: which models are trainable on this data, and why not.

    uv run scripts/readiness_check.py --dataset main --scope ALL
    uv run scripts/readiness_check.py --dataset backup --scope MX --out /tmp/readiness.csv

Builds (or reuses) the scratch lakehouse of the scope with `latam_eda.country.session`, builds the hour-grain star and
runs every scenario of `latam_eda.hour_models` with the readiness gate of `latam_eda.granularity`. A newly ingested
source is judged by the same rule as the notebooks: a gate turns green only when the out-of-time gain over its
benchmark is significant and material. The default output goes to data/derived/readiness/ (never into git).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from latam_eda import country  # noqa: E402
from latam_eda import granularity as g  # noqa: E402
from latam_eda import hour_models as hm  # noqa: E402
from latam_eda import pipeline as pipe  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", default="main", choices=["main", "backup"])
    ap.add_argument("--scope", default="ALL", choices=["ALL", *country.COUNTRIES])
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    out = a.out or (
        pipe.repo_root(Path.cwd())
        / "data"
        / "derived"
        / "readiness"
        / f"hour_readiness_{a.dataset}_{a.scope.lower()}.csv"
    )
    t0 = time.time()
    pl = country.session(a.scope, a.dataset)
    country.prepare(pl, "gold")
    star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])
    star.build(verbose=False)
    checks = star.check()
    if not checks.ok.all():
        print(checks[~checks.ok].to_string())
        raise SystemExit(
            "the hour star does not pass its checks: fix the data before judging models"
        )
    sc = hm.scorecard(star)
    pl.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    sc.to_csv(out, index=False)
    print(sc[["scenario", "model", "verdict", "root_cause"]].to_string(index=False))
    print(
        f"\n{(sc.verdict == 'green').sum()} green, {(sc.verdict == 'amber').sum()} amber, "
        f"{(sc.verdict == 'red').sum()} red -> {out} ({time.time() - t0:.0f} s)"
    )


if __name__ == "__main__":
    main()
