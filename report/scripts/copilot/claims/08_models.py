"""Chapter 8 · The frozen challenge set with each language model inside BETA AID.

Every model run used the copilot after the fix of Chapter 6, so its baseline is the learned configuration's rerun
after that fix (no language model). The stored model runs lacked the retrieval embedder (the rag extra), so the
knowledge cases ended as tool failures in every one of them; the comparisons therefore use the other cases, and the
knowledge cases are reported from a replay with retrieval working (copilot/eval/replay_cases.py). Paired exact McNemar
tests on the same cases: each model against that baseline (one family) and every pair of models (another).

    REPORT_DOC=copilot uv run python scripts/copilot/claims/08_models.py
"""

from __future__ import annotations

from itertools import combinations

import pandas as pd

from report_lib import protocol
from report_lib.build import Chapter
from report_lib.copilot_data import (
    CASES,
    CHALLENGE_AFTER,
    DETAILS,
    OPEN,
    RUNS,
    cases,
    challenge_pass,
    load,
    model_challenge_pass,
    out,
    run,
)
from report_lib.estimators import bh
from report_lib.estimators.intervals import wilson
from report_lib.estimators.resampling import mcnemar_exact
from report_lib.texgen import render_table

STORED = "stored by the challenge run, which records no interval"
LABEL = {r.key: r.label for r in RUNS}


def main() -> None:
    alpha = float(protocol.load()["stats"]["alpha"])
    ch = Chapter(8, "mod")
    base = challenge_pass(CHALLENGE_AFTER, "learned")
    knowledge = sorted(c["id"] for c in cases() if c["cat"] == "knowledge")
    ids = sorted(i for i in base if i not in knowledge)  # the cases retrieval does not touch
    ch.count("knowledge-cases", len(knowledge), CASES)
    ch.count("compared-cases", len(ids), CASES)
    passes, rows, fails, knowledge_failed = {}, [], [], 0
    for r in RUNS:
        d, src = run(r), OPEN / r.file
        s = d["challenge"]["summary"]
        p = model_challenge_pass(r)
        if sum(p.values()) != s["correct"]["k"]:
            raise SystemExit(f"{r.key}: failed cases and summary disagree")
        passes[r.key] = p
        k = r.key
        ok = sum(p[i] for i in ids)
        ch.proportion(f"{k}-correct-compared", ok, len(ids), wilson(ok, len(ids)), src)
        knowledge_failed += all(not p[i] for i in knowledge)
        for key, topic in (("correct", "correct"), ("safe_automated_resolution_in_scope", "safe-in-scope"),
                           ("unsafe_cases", "unsafe"), ("containment", "containment")):  # fmt: skip
            m = s[key]
            ch.proportion(f"{k}-{topic}", m["k"], m["n"], wilson(m["k"], m["n"]), src)
        llm = d["challenge"]["llm"]
        calls = llm["classify"]["calls"] + llm["rephrase"]["calls"]
        ch.count(f"{k}-calls", calls, src)
        ch.count(f"{k}-classify", llm["classify"]["calls"], src)
        ch.count(f"{k}-rephrase", llm["rephrase"]["calls"], src)
        ttft = (
            llm["rephrase"]["ttft_ms_p50"]
            if llm["rephrase"]["calls"]
            else llm["classify"]["ttft_ms_p50"]
        )
        ch.descriptive(f"{k}-ttft-p50", ttft, src, STORED, unit="ms", digits=3)
        ch.descriptive(f"{k}-turn-p95", s["latency_ms_p95"], src, STORED, unit="ms", digits=3)
        w = wilson(ok, len(ids))
        rows.append({"model": r.label, "correct (stored)": s["correct"]["rate"], "correct (compared)": ok / len(ids),
                     "lower": w.lo, "upper": w.hi, "unsafe cases": s["unsafe_cases"]["k"],
                     "safe resolution in scope": s["safe_automated_resolution_in_scope"]["rate"],
                     "model calls": calls, "turn p95 ms": s["latency_ms_p95"]})  # fmt: skip
        fails.append({"model": r.label, "failed cases": ", ".join(i for i in ids if not p[i])})
    bok = sum(base[i] for i in ids)
    ch.proportion("base-correct-compared", bok, len(ids), wilson(bok, len(ids)), CHALLENGE_AFTER)
    ch.count("knowledge-failed-runs", knowledge_failed, OPEN / RUNS[0].file)
    ch.count("base-knowledge-passed", sum(base[i] for i in knowledge), CHALLENGE_AFTER)
    rows.append({"model": "no language model (learned, after the fix)", "correct (stored)": sum(base.values()) / len(base),
                 "correct (compared)": bok / len(ids), "lower": wilson(bok, len(ids)).lo,
                 "upper": wilson(bok, len(ids)).hi, "unsafe cases": 0,
                 "safe resolution in scope": float("nan"), "model calls": 0, "turn p95 ms": float("nan")})  # fmt: skip
    fails.append(
        {
            "model": "no language model (learned, after the fix)",
            "failed cases": ", ".join(i for i in ids if not base[i]),
        }
    )

    tests = [
        (k, mcnemar_exact([passes[k][i] for i in ids], [base[i] for i in ids])) for k in passes
    ]
    q = bh.adjust([t.p for _, t in tests])
    for (k, t), qv in zip(tests, q, strict=True):
        ch.count(f"{k}-only-model", t.b, CHALLENGE_AFTER)
        ch.count(f"{k}-only-base", t.c, CHALLENGE_AFTER)
        ch.test(f"{k}-vs-base", t.b, t.p, qv, "models-vs-no-model", len(tests), OPEN / next(
            r.file for r in RUNS if r.key == k), null="equal accuracy with and without the model",
            method="exact McNemar")  # fmt: skip
    ch.count("vs-base-q05", int((q <= alpha).sum()), CHALLENGE_AFTER)
    # where the models differ from the baseline: the cases each run gains and loses
    cat = {c["id"]: c["cat"] for c in cases()}
    gains = {k: frozenset(i for i in ids if passes[k][i] and not base[i]) for k in passes}
    losses = {k: [i for i in ids if base[i] and not passes[k][i]] for k in passes}
    common = frozenset.intersection(*gains.values())
    ch.count("common-gains", len(common), CHALLENGE_AFTER)
    ch.count("runs-same-gains", sum(g == common for g in gains.values()), CHALLENGE_AFTER)
    ch.count(
        "runs-lose-multicard",
        sum(any(cat[i] == "multi_card" for i in v) for v in losses.values()),
        CASES,
    )
    ch.count(
        "runs-lose-out-of-scope",
        sum(any(cat[i] == "out_of_scope" for i in v) for v in losses.values()),
        CASES,
    )
    ch.count("loss-categories", len({cat[i] for v in losses.values() for i in v}), CASES)
    pairs = list(combinations(passes, 2))
    pt = [mcnemar_exact([passes[a][i] for i in ids], [passes[b][i] for i in ids]) for a, b in pairs]
    pq = bh.adjust([t.p for t in pt])
    ch.count("pairs", len(pairs), CHALLENGE_AFTER)
    ch.count("pairs-q05", int((pq <= alpha).sum()), CHALLENGE_AFTER)
    ch.descriptive("pairs-min-p", float(min(t.p for t in pt)), CHALLENGE_AFTER,
                   "the smallest unadjusted p-value of the family, before the Benjamini-Hochberg adjustment", digits=2)  # fmt: skip
    ch.count("max-discordant", max(t.b + t.c for t in pt), CHALLENGE_AFTER)
    ch.count("base-correct", sum(base.values()), CHALLENGE_AFTER)

    replays = sorted(DETAILS.glob("replay_*.json"))
    ch.count("replays", len(replays), replays[0])
    replay_rows = []
    for path in replays:
        d = load(path)
        by_id = {c["id"]: c for c in d["cases"]}
        key = next(
            r.key
            for r in RUNS
            if (run(r)["model"], run(r).get("provider")) == (d["model"], d["provider"])
        )
        label = LABEL[key]
        ok = []
        for cid in knowledge:
            case = next(c for c in cases() if c["id"] == cid)
            last = by_id[cid]["turns"][-1]
            want = case["expect"]
            good = last["outcome"] == want["outcome"] and (
                not want.get("queue") or last.get("handoff_queue") == want["queue"]
            )
            ok.append(good)
            replay_rows.append({"model": label, "case": cid,
                                "expected": want["outcome"] + (f" ({want['queue']})" if want.get("queue") else ""),
                                "got": last["outcome"] + (f" ({last['handoff_queue']})" if last.get("handoff_queue") else ""),
                                "rule": last.get("policy_rule", "").replace("_", " "),
                                "grounding": (last.get("grounding") or "").replace("_", " ")})  # fmt: skip
        ch.count(f"{key}-replay-passed", sum(ok), path)
    src = out("knowledge_replay.csv")
    pd.DataFrame(replay_rows).to_csv(src, index=False)
    render_table(src, "knowledge-replay", "The knowledge cases replayed with retrieval working, for the hosted "
                 "models: the outcome each case required, the outcome it got, the policy rule that decided it and "
                 "the verdict of the grounding check on a generated answer.", widths={"model": "3.4cm"})  # fmt: skip

    src = out("models_challenge.csv")
    pd.DataFrame(rows).to_csv(src, index=False)
    render_table(src, "models-challenge", "The frozen challenge set with each model inside BETA AID, and without a "
                 "model. Stored is the share of all cases as the run recorded it; compared leaves out the knowledge "
                 "cases, which the model runs could not retrieve for, and carries the Wilson interval. Model calls "
                 "count the classify and rephrase calls over all cases.", digits=3)  # fmt: skip
    src = out("models_failures.csv")
    pd.DataFrame(fails).to_csv(src, index=False)
    render_table(
        src,
        "models-failures",
        "The cases each configuration failed.",
        widths={"failed cases": "8cm"},
    )
    ch.write()


if __name__ == "__main__":
    main()
