"""Chapter 7 · Language models alone and inside BETA AID, on the same adapted attacks.

Per model: violations raw and wrapped (Wilson; a zero also gets its one-sided exact upper bound), violations by
attack kind and type, the wrapped outcomes, and latency from the per-call rows (bootstrap intervals). Paired exact
McNemar tests on the same attacks: raw against wrapped for each model, and raw between every pair of models, each a
Benjamini-Hochberg family.

    REPORT_DOC=copilot uv run python scripts/copilot/claims/07_attacks.py
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd

from report_lib import protocol
from report_lib.build import Chapter
from report_lib.copilot_data import ATTACK_KINDS, ATTACKS, KIND_LABEL, OPEN, RUNS, load, out, run
from report_lib.estimators import bh
from report_lib.estimators.intervals import wilson
from report_lib.estimators.resampling import bootstrap, mcnemar_exact, zero_events_upper
from report_lib.texgen import render_table

LABEL = {r.key: r.label for r in RUNS}
OUTCOMES = (
    "answered",
    "clarify",
    "confirm_requested",
    "deny",
    "handoff",
    "refused",
    "tool_failure",
)


HIGH = float(protocol.load()["stats"]["high_percentile"])


def p95(x) -> float:
    return float(np.percentile(x, HIGH))


def main() -> None:
    P = protocol.load()["stats"]
    reps, seed = int(P["bootstrap_reps"]), int(P["seed"])
    ch = Chapter(7, "atk")
    attacks = load(ATTACKS)
    ch.count("attacks", len(attacks), ATTACKS)
    for kind, n in Counter(a["kind"] for a in attacks).items():
        ch.count(f"n-{kind.split('_')[0]}", n, ATTACKS)
    for lang, n in Counter(a["lang"] for a in attacks).items():
        ch.count(f"n-{lang}", n, ATTACKS)
    ch.count("runs", len(RUNS), OPEN / RUNS[0].file)

    summary, by_kind, outcomes, raw_ok, refused_sets = [], [], [], {}, []
    for r in RUNS:
        d, src = run(r), OPEN / r.file
        raw, wrapped = pd.DataFrame(d["raw"]["rows"]), pd.DataFrame(d["wrapped"]["rows"])
        n = len(raw)
        rv = raw.violations.map(bool).to_numpy()
        wv = wrapped.violations.map(bool).to_numpy()
        if (
            rv.sum() != d["raw"]["summary"]["violated"]
            or wv.sum() != d["wrapped"]["summary"]["violated"]
        ):
            raise SystemExit(f"{r.key}: rows and summary disagree")
        k = r.key
        ch.proportion(f"{k}-raw", rv.sum(), n, wilson(rv.sum(), n), src)
        ch.proportion(f"{k}-wrapped", wv.sum(), n, wilson(wv.sum(), n), src)
        if wv.sum() == 0:
            ch.descriptive(f"{k}-wrapped-upper", zero_events_upper(n, float(P["level"])), src,
                           "one-sided exact upper bound for a proportion with no events", digits=2)  # fmt: skip
        t = mcnemar_exact(
            ~rv, ~wv
        )  # pass = no violation; c counts attacks only the wrapped model withstood
        raw_ok[k] = ~rv
        ch.count(f"{k}-only-raw", t.c, src)
        summary.append((k, t))
        ttft = raw.ttft_ms.to_numpy()
        ch.metric(f"{k}-ttft-p50", bootstrap(ttft, np.median, reps, seed), n, src, digits=3)
        ch.metric(f"{k}-ttft-p95", bootstrap(ttft, p95, reps, seed), n, src, digits=3)
        turn = wrapped.ms.to_numpy()
        ch.metric(f"{k}-turn-p50", bootstrap(turn, np.median, reps, seed), n, src, digits=3)
        ch.metric(f"{k}-turn-p95", bootstrap(turn, p95, reps, seed), n, src, digits=3)
        ch.descriptive(f"{k}-tokens-out", float(raw.tokens_out.mean()), src,
                       "mean over the raw calls, a description of the replies' length", digits=3)  # fmt: skip
        row = {"model": r.label}
        for kind in ATTACK_KINDS:
            m = (raw.kind == kind).to_numpy()
            row[KIND_LABEL[kind]] = int(rv[m].sum())
            ch.count(f"{k}-raw-{kind.split('_')[0]}", int(rv[m].sum()), src)
        types = Counter(v for vs in raw.violations for v in vs)
        row["violation types"] = (
            ", ".join(f"{t.replace('_', ' ')} {n_}" for t, n_ in sorted(types.items())) or "none"
        )
        by_kind.append(row)
        oc = Counter(wrapped.outcome)
        outcomes.append({"model": r.label, **{o.replace("_", " "): oc.get(o, 0) for o in OUTCOMES}})
        refused_sets.append(set(wrapped.id[wrapped.outcome == "refused"]))
        ch.count(f"{k}-refused", oc.get("refused", 0), src)
        llm = d["wrapped"]["llm"]
        ch.count(f"{k}-wrapped-classify", llm["classify"]["calls"], src)
        ch.count(f"{k}-wrapped-rephrase", llm["rephrase"]["calls"], src)

    first = OPEN / RUNS[0].file
    ch.count("refused-by-all", len(set.intersection(*refused_sets)), first)
    ch.count("refused-by-any", len(set.union(*refused_sets)), first)
    # raw against wrapped, per model: one family
    q = bh.adjust([t.p for _, t in summary])
    for (k, t), qv in zip(summary, q, strict=True):
        src = OPEN / next(r.file for r in RUNS if r.key == k)
        ch.test(f"{k}-raw-vs-wrapped", t.c, t.p, qv, "raw-vs-wrapped", len(summary), src,
                null="equal violation rates alone and inside BETA AID", method="exact McNemar")  # fmt: skip
    # raw, every pair of models: one family
    pairs = list(combinations([r.key for r in RUNS], 2))
    tests = [mcnemar_exact(raw_ok[a], raw_ok[b]) for a, b in pairs]
    q = bh.adjust([t.p for t in tests])
    paired = []
    for (a, b), t, qv in zip(pairs, tests, q, strict=True):
        src = OPEN / next(r.file for r in RUNS if r.key == a)
        ch.test(f"raw-{a}-vs-{b}", t.b, t.p, qv, "raw-between-models", len(pairs), src,
                null="equal raw violation rates of the two models on the same attacks", method="exact McNemar")  # fmt: skip
        paired.append({"first": LABEL[a], "second": LABEL[b], "only first withstood": t.b, "only second withstood": t.c,
                       "p": t.p, "q": qv})  # fmt: skip
    ch.count("pairs", len(pairs), first)
    ch.count("pairs-q05", int((q <= float(P["alpha"])).sum()), first)

    for name, rows, label, caption in (
        ("attacks_by_kind.csv", by_kind, "attacks-by-kind",
         "Raw violations by attack kind for each model, and the violation types they contained (one reply can "
         "contain more than one type). Inside BETA AID no model had a violation of any kind."),
        ("attacks_outcomes.csv", outcomes, "attacks-outcomes",
         "What BETA AID did with each attack, by the model inside it."),
        ("attacks_paired.csv", paired, "attacks-paired",
         "Raw violations compared between every pair of models on the same attacks: attacks only one of the two "
         "withstood, the exact McNemar p-value and its Benjamini-Hochberg q-value over the pairs."),
    ):  # fmt: skip
        src = out(name)
        pd.DataFrame(rows).to_csv(src, index=False)
        render_table(
            src,
            label,
            caption,
            digits=2,
            widths={"violation types": "6.2cm"} if "kind" in name else None,
        )
    ch.write()


if __name__ == "__main__":
    main()
