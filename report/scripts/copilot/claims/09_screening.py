"""Chapter 9 · Speed screening of hosted models in the copilot's intent-labelling job.

Per model and provider: total time per call (median and 95th percentile, bootstrap intervals), calls over the
copilot's model timeout, the share of replies that are a JSON object with a known intent (Wilson), and the warm-up
call. The same model on both providers is compared by the difference of medians (independent bootstrap).

    REPORT_DOC=copilot uv run python scripts/copilot/claims/09_screening.py
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from report_lib import protocol
from report_lib.build import Chapter
from report_lib.copilot_data import CONFIG, EVAL, SCREENING, out, screening
from report_lib.estimators.intervals import Interval, wilson
from report_lib.estimators.resampling import bootstrap
from report_lib.texgen import render_table

SHORT = {"Qwen/Qwen3-30B-A3B-Instruct-2507": "qwen30", "google/gemma-3-27b-it": "gemma27",
         "Qwen/Qwen2.5-72B-Instruct": "qwen72", "Qwen/Qwen2.5-14B-Instruct": "qwen14",
         "deepseek-ai/DeepSeek-V4-Flash-0731": "dsv4flash"}  # fmt: skip
PROVIDER = {"tokenfactory": "tf", "featherless": "fl"}
NAME = {"tokenfactory": "Token Factory", "featherless": "Featherless"}
SCREENER = EVAL / "screen_models.py"


HIGH = float(protocol.load()["stats"]["high_percentile"])


def p95(x) -> float:
    return float(np.percentile(x, HIGH))


def path_of(d: dict):
    return SCREENING / f"{d['provider']}__{re.sub(r'[^A-Za-z0-9.-]+', '_', d['model'])}.json"


def main() -> None:
    P = protocol.load()["stats"]
    reps, seed = int(P["bootstrap_reps"]), int(P["seed"])
    timeout_ms = 1000 * float(
        re.search(r'COPILOT_LLM_TIMEOUT", "([0-9.]+)"', CONFIG.read_text()).group(1)
    )
    ch = Chapter(9, "scr")
    budget = int(re.search(r"max_tokens=(\d+)", SCREENER.read_text()).group(1))
    ch.constant("token-budget", budget, SCREENER)
    rows, totals = [], {}
    runs = screening()
    ch.count("configurations", len(runs), path_of(runs[0]))
    ch.count("calls-per-model", runs[0]["n"], path_of(runs[0]))
    ch.constant("call-timeout", runs[0]["timeout_s"], path_of(runs[0]), unit="s")
    for d in runs:
        src, k = path_of(d), f"{SHORT[d['model']]}-{PROVIDER[d['provider']]}"
        label = f"{d['model'].split('/')[-1].removesuffix('-Instruct-2507').removesuffix('-Instruct')}, {NAME[d['provider']]}"
        if "error" in d["warmup"]:
            ch.count(f"{k}-refused", 1, src)
            rows.append({"model": f"{label} (refused: {d['warmup']['error']})"})
            continue
        calls = [c for c in d["calls"] if "error" not in c]
        total = np.array([c["total_ms"] for c in calls])
        totals[k] = total
        valid = sum(c["valid_label"] for c in calls)
        over = int((total > timeout_ms).sum())
        ch.count(f"{k}-ok", len(calls), src)
        ch.metric(f"{k}-p50", bootstrap(total, np.median, reps, seed), len(total), src, digits=3)
        ch.metric(f"{k}-p95", bootstrap(total, p95, reps, seed), len(total), src, digits=3)
        ch.descriptive(f"{k}-max", float(total.max()), src, "the slowest call: an observed extreme", unit="ms",
                       digits=3)  # fmt: skip
        ch.descriptive(f"{k}-warmup", float(d["warmup"]["total_ms"]), src, "a single warm-up call", unit="ms",
                       digits=3)  # fmt: skip
        ch.proportion(f"{k}-valid", valid, len(calls), wilson(valid, len(calls)), src)
        ch.count(f"{k}-over", over, src)
        invalid = [c for c in calls if not c["valid_label"]]
        ch.count(f"{k}-invalid-at-budget", sum(c["tokens_out"] >= budget for c in invalid), src)
        rows.append({"model": label, "median ms": float(np.median(total)), "p95 ms": p95(total),
                     "max ms": float(total.max()), "warm-up ms": d["warmup"]["total_ms"], "over timeout": over,
                     "valid labels": f"{valid}/{len(calls)}",
                     "tokens in/out": f"{round(float(np.mean([c['tokens_in'] for c in calls])))}/"
                                      f"{round(float(np.mean([c['tokens_out'] for c in calls])))}"})  # fmt: skip
    ch.constant("timeout", timeout_ms / 1000, CONFIG, unit="s")
    # the same model on both providers: Featherless minus Token Factory, difference of medians
    a, b = totals["qwen30-tf"], totals["qwen30-fl"]
    rng = np.random.default_rng(seed)
    draws = np.array(
        [np.median(rng.choice(b, len(b))) - np.median(rng.choice(a, len(a))) for _ in range(reps)]
    )
    alpha = 1 - float(P["level"])
    diff = Interval(float(np.median(b) - np.median(a)), float(np.quantile(draws, alpha / 2)),
                    float(np.quantile(draws, 1 - alpha / 2)), "bootstrap-iid")  # fmt: skip
    ch.difference("qwen30-fl-minus-tf", diff, path_of(next(d for d in runs if d["provider"] == "featherless" and
                  SHORT[d["model"]] == "qwen30")), cluster_unit="none", unit="ms", digits=3)  # fmt: skip
    src = out("screening.csv")
    pd.DataFrame(rows).to_csv(src, index=False)
    render_table(src, "screening", "Speed screening in the intent-labelling job: total time per call (median, "
                 "high percentile, slowest), the warm-up call, calls over the copilot's model timeout, replies that are "
                 "a JSON object with a known intent, and mean tokens per call.", digits=3)  # fmt: skip
    ch.write()


if __name__ == "__main__":
    main()
