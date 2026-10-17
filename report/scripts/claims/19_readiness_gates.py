"""Chapter 19 · The readiness gates and their registered re-estimation.

Reads the published hour-grain scorecard (eda/reports/tables/granularity_hour_readiness.csv) and the registered
re-estimates that `eda/scripts/readiness_check.py --cluster` wrote for main and backup under the frozen protocol, and
records, per gate and copy, a registered claim: the gain over the benchmark with its clustered or day-block bootstrap
interval. It then compares each re-estimate with the published verdict and root cause (the disagreement rule) and the
main and backup re-estimates with each other (the copy tolerance), and reproduces the Benjamini-Hochberg q-values of
the time and hour series' ledgers.

    cd eda && uv run scripts/readiness_check.py --dataset main --scope ALL --cluster
    cd eda && uv run scripts/readiness_check.py --dataset backup --scope ALL --cluster
    uv run python scripts/claims/19_readiness_gates.py
"""

from __future__ import annotations

import re
import subprocess

import numpy as np
import pandas as pd
from scipy import stats

from report_lib import protocol
from report_lib.build import Chapter
from report_lib.estimators import bh
from report_lib.estimators.intervals import Interval
from report_lib.manifest import Claim
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

OUT = BUILD / "sources"
READY = REPO / "data" / "derived" / "readiness"
PUBLISHED = TABLES / "granularity_hour_readiness.csv"
PROTOCOL = REPO / "report" / "conf" / "protocol.toml"


def gate_id(scenario: str, model: str) -> str:
    slug = lambda s: re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")  # noqa: E731
    return f"{slug(scenario)}.{slug(model)}"


def label(verdict: str, cause) -> str:
    """Verdict and root cause for the table; an error message is cut to its type."""
    cause = cause if isinstance(cause, str) and cause else "-"
    cause = re.sub(r"(scenario raised \w+):.*", r"\1", cause)
    return f"{verdict}: {cause}"


def protocol_commit() -> str:
    """The last commit that changed protocol.toml: the specification in force for this run."""
    return subprocess.run(["git", "log", "-1", "--format=%H", "--", str(PROTOCOL)], capture_output=True, text=True,
                          check=True, cwd=REPO, env=protocol.git_env()).stdout.strip()  # fmt: skip


def registered(ch: Chapter) -> pd.DataFrame:
    proto = protocol.load()["gates"]
    ids, units = proto["ids"], proto["units"]
    z = stats.norm.ppf(0.975)
    pub = pd.read_csv(PUBLISHED)
    pub["gate"] = [gate_id(s, m) for s, m in zip(pub.scenario, pub.model, strict=True)]
    pub = pub.set_index("gate")
    assert sorted(pub.index) == sorted(ids), "published scorecard and protocol gates differ"
    for tag in ("green", "amber", "red"):
        ch.count(f"pub-{tag}", int((pub.verdict == tag).sum()), PUBLISHED, source_type="table")
    ch.count("gates", len(ids), PROTOCOL)
    ch.status, ch.protocol_commit = "registered", protocol_commit()
    re_ = {}
    for copy in ("main", "backup"):
        p = READY / f"hour_readiness_{copy}_all_cluster.csv"
        r = pd.read_csv(p)
        r["gate"] = [gate_id(s, m) for s, m in zip(r.scenario, r.model, strict=True)]
        r = r.set_index("gate").loc[ids]
        re_[copy] = r
        for g, row in r.iterrows():
            if not np.isfinite(
                row.get("delta", np.nan)
            ):  # the scenario raised: a registered row with its cause
                ch.claims.append(Claim(id=f"ch19.{copy}.{g}", kind="descriptive", value=0.0,
                                       reason=f"not assessable: {row.root_cause}", **ch._src(p, "scripted")))  # fmt: skip
                continue
            method = (
                "block-bootstrap" if str(row.resampling).startswith("day") else "cluster-bootstrap"
            )
            ch.difference(f"{copy}.{g}", Interval(float(row.delta), float(row.delta_lo), float(row.delta_hi), method),
                          p, cluster_unit=units[g].split(" (")[0], digits=3)  # fmt: skip
        for tag in ("green", "amber", "red", "not assessable"):
            ch.count(f"{copy}-{tag.replace(' ', '-')}", int((r.verdict == tag).sum()), p)
    ch.status = None
    m, b = re_["main"], re_["backup"]
    rows = []
    for g in ids:
        sd_m, sd_b = m.loc[g, "mde"] / 2.8, b.loc[g, "mde"] / 2.8
        tol = z * np.hypot(
            sd_m, sd_b
        )  # NaN when a copy is not assessable: the comparison is then not made
        rows.append({"gate": g, "published": label(pub.loc[g, "verdict"], pub.loc[g, "root_cause"]),
                     "main": label(m.loc[g, "verdict"], m.loc[g, "root_cause"]),
                     "backup": label(b.loc[g, "verdict"], b.loc[g, "root_cause"]),
                     "unit": m.loc[g, "resampling"], "clusters": int(m.loc[g, "n_clusters"]),
                     "disagrees": (m.loc[g, "verdict"], str(m.loc[g, "root_cause"])) != (pub.loc[g, "verdict"], str(pub.loc[g, "root_cause"])),
                     "copy difference": float(m.loc[g, "delta"] - b.loc[g, "delta"]), "copy tolerance": float(tol),
                     "copy disagreement": bool(abs(m.loc[g, "delta"] - b.loc[g, "delta"]) > tol),
                     "comparable": bool(np.isfinite(tol) and np.isfinite(m.loc[g, "delta"] - b.loc[g, "delta"]))})  # fmt: skip
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch19_gates.csv", index=False)
    src = READY / "hour_readiness_main_all_cluster.csv"
    ch.count("disagree", int(t.disagrees.sum()), src)
    ch.count("copy-disagree", int(t["copy disagreement"].sum()), src)
    ch.count("copy-comparable", int(t.comparable.sum()), src)
    ch.count("verdict-changed", int((m.verdict != pub.loc[ids, "verdict"]).sum()), src)
    ch.census("nan-share-max", float(m.nan_share.max()), src, digits=2)
    ch.census("clusters-min", float(m.n_clusters.min()), src)
    # the SLA gate's constant benchmark carries a random tie-breaking jitter whose draw depends on the RNG state
    sla = "06-case-clock.sla-breach-at-creation"
    ch.census("sla-model-auc", float(m.loc[sla, "value"]), src, digits=4)
    ch.census(
        "sla-bench-pub",
        float(pub.loc[sla, "benchmark_value"]),
        PUBLISHED,
        source_type="table",
        digits=4,
    )
    ch.census("sla-bench-reg", float(m.loc[sla, "benchmark_value"]), src, digits=4)
    ch.census(
        "sla-delta-pub", float(pub.loc[sla, "delta"]), PUBLISHED, source_type="table", digits=3
    )
    ch.census("sla-delta-const", float(m.loc[sla, "value"] - 0.5), src, digits=3)
    same = [
        g for g in ids if g != sla and np.isclose(m.loc[g, "delta"], pub.loc[g, "delta"], atol=1e-9)
    ]
    ch.count("same-delta", len(same), src)
    return t


def ledgers(ch: Chapter) -> None:
    for name, tag in (("granularity_time_signal", "time"), ("granularity_hour_signal", "hour")):
        p = TABLES / f"{name}.csv"
        s = pd.read_csv(p)
        ok = s.p_value.notna()
        q = bh.adjust(s.loc[ok, "p_value"].to_numpy())
        ch.count(f"{tag}-tests", int(ok.sum()), p, source_type="table")
        ch.count(f"{tag}-discoveries", int((q <= 0.05).sum()), p, source_type="table")
        stored = s.loc[ok, "q_value"].to_numpy()
        ch.count(
            f"{tag}-q-reproduced", int(np.allclose(q, stored, atol=1e-12)), p, source_type="table"
        )


def amendments(ch: Chapter) -> None:
    import tomllib

    am = pd.DataFrame(tomllib.loads(PROTOCOL.read_text()).get("amendments", []))
    am[["date", "field", "reason"]].to_csv(OUT / "ch19_amendments.csv", index=False)
    ch.count("amendments", len(am), PROTOCOL)
    ch.count("amendments-gates", int(am.field.str.startswith("gates.").sum()), PROTOCOL)
    render_table(OUT / "ch19_amendments.csv", "ch19-amendments", "Every amendment to the frozen protocol, with its date, "
                 "the field it adds or changes, and its reason (conf/protocol.toml).", widths={"reason": "8.5cm"})  # fmt: skip


def main() -> None:
    ch = Chapter(19, "ch19")
    OUT.mkdir(parents=True, exist_ok=True)
    t = registered(ch)
    ledgers(ch)
    amendments(ch)
    render_table(OUT / "ch19_gates.csv", "ch19-gates", "The readiness gates: the published verdict and root cause, the "
                 "registered re-estimate on main and on backup under the frozen protocol, the number of clusters "
                 "resampled, whether main disagrees with the published scorecard, and the main-backup "
                 "difference of the gain against the copy tolerance.",
                 columns=["gate", "published", "main", "backup", "clusters", "disagrees", "copy difference",
                          "copy tolerance"], digits=3,
                 widths={"gate": "3.4cm", "published": "2.5cm", "main": "2.5cm", "backup": "2.5cm"})  # fmt: skip
    print(t[["gate", "published", "main", "backup", "disagrees", "copy disagreement"]].to_string())
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
