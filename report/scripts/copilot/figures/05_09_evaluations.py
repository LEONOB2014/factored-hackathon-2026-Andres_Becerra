"""Figures of Chapters 5 to 9: retrieval rates, challenge set by category, violations raw and inside BETA AID, time
to first token, the challenge set with each model, and the speed screening.

Every rate carries its Wilson interval, recomputed here from the same item-level sources the claims use.

    REPORT_DOC=copilot uv run python scripts/copilot/figures/05_09_evaluations.py
"""

from __future__ import annotations

import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from report_lib import figures
from report_lib.copilot_data import (
    CHALLENGE,
    CHALLENGE_AFTER,
    CONFIG,
    INK,
    KB,
    LEARNED,
    MUTED,
    OPEN,
    RAW,
    RUNS,
    SCREENING,
    cases,
    challenge_pass,
    load,
    model_challenge_pass,
    run,
    screening,
)
from report_lib.estimators.intervals import wilson


def style(ax) -> None:
    ax.tick_params(labelsize=7, length=2)
    ax.spines[["top", "right"]].set_visible(False)


def err(k: int, n: int) -> tuple[float, float, float]:
    w = wilson(k, n)
    return k / n, k / n - w.lo, w.hi - k / n


def retrieval() -> None:
    rep = load(KB)
    names = {
        "bundled": "bundled (served)",
        "pgvector": "pgvector",
        "graph": "graph",
        "hybrid(pgvector+graph)": "hybrid",
    }
    measures = (("hit@1", "right document\nranked first"), ("hit@3", "right document\nin the top three"),
                ("kept", "answerable\nquestions kept"), ("rejected", "unanswerable\nquestions rejected"))  # fmt: skip
    fig, axes = plt.subplots(1, 4, figsize=(6.6, 2.5), sharey=True)
    for ax, (key, title) in zip(axes, measures, strict=True):
        for i, name in enumerate(names):
            r = rep[name]
            rows = pd.DataFrame(r["rows"])
            test = rows[rows.split == "test"]
            ans, none = test[test.expect.notna()], test[test.expect.isna()]
            rank = ans["rank"].astype(float)
            k, n = {"hit@1": ((rank == 1).sum(), len(ans)), "hit@3": ((rank <= 3).sum(), len(ans)),
                    "kept": ((ans.top_score >= r["threshold"]).sum(), len(ans)),
                    "rejected": ((none.top_score < r["threshold"]).sum(), len(none))}[key]  # fmt: skip
            p, lo, hi = err(int(k), int(n))
            ax.errorbar(p, i, xerr=[[lo], [hi]], fmt="o", color=LEARNED if name == "bundled" else INK, markersize=4,
                        capsize=2, linewidth=0.8)  # fmt: skip
        ax.set_title(title, fontsize=7.5)
        ax.set_xlim(-0.03, 1.03)
        style(ax)
    axes[0].set_yticks(range(len(names)), list(names.values()), fontsize=7)
    axes[0].invert_yaxis()
    fig.tight_layout()
    figures.save(fig, "fig-kb-rates", [KB])
    plt.close(fig)


def challenge_categories() -> None:
    first = load(CHALLENGE)
    cats = sorted({r["cat"] for r in first["variants"]["learned"]["rows"]})
    fig, ax = plt.subplots(figsize=(5.8, 4.0))
    for off, variant, color in ((-0.17, "keyword", RAW), (0.17, "learned", LEARNED)):
        rows = pd.DataFrame(first["variants"][variant]["rows"])
        for i, c in enumerate(cats):
            g = rows[rows.cat == c]
            p, lo, hi = err(int(g["pass"].sum()), len(g))
            ax.errorbar(p, i + off, xerr=[[lo], [hi]], fmt="o", color=color, markersize=3.5, capsize=1.5,
                        linewidth=0.7, label=variant if i == 0 else None)  # fmt: skip
    n = {c: sum(r["cat"] == c for r in first["variants"]["learned"]["rows"]) for c in cats}
    ax.set_yticks(range(len(cats)), [f"{c.replace('_', ' ')} ({n[c]})" for c in cats], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlim(-0.03, 1.03)
    ax.set_xlabel("share of the category's cases with the correct final outcome", fontsize=8)
    ax.legend(fontsize=7, frameon=False, loc="upper left", title="intent routing", title_fontsize=7)
    style(ax)
    figures.save(fig, "fig-chl-categories", [CHALLENGE])
    plt.close(fig)


def violations() -> None:
    fig, ax = plt.subplots(figsize=(5.8, 2.9))
    for i, r in enumerate(RUNS):
        d = run(r)
        for off, part, color, label in (
            (-0.15, "raw", RAW, "model alone"),
            (0.15, "wrapped", LEARNED, "inside BETA AID"),
        ):
            rows = d[part]["rows"]
            k = sum(bool(x["violations"]) for x in rows)
            p, lo, hi = err(k, len(rows))
            ax.errorbar(p, i + off, xerr=[[lo], [hi]], fmt="o", color=color, markersize=4, capsize=2, linewidth=0.8,
                        label=label if i == 0 else None)  # fmt: skip
    ax.set_yticks(range(len(RUNS)), [r.label for r in RUNS], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlim(-0.01, 0.3)
    ax.set_xlabel(f"share of the {len(rows)} attacks with a violation", fontsize=8)
    ax.legend(fontsize=7, frameon=False, loc="upper right")
    style(ax)
    figures.save(fig, "fig-atk-violations", [OPEN / r.file for r in RUNS])
    plt.close(fig)


def ttft() -> None:
    fig, ax = plt.subplots(figsize=(5.8, 3.0))
    colors = ["#0f766e", "#14b8a6", "#7c3aed", "#b45309", "#64748b", "#a3a3a3"]
    for r, color in zip(RUNS, colors, strict=True):
        x = np.sort([row["ttft_ms"] for row in run(r)["raw"]["rows"]])
        ax.step(
            x,
            np.arange(1, len(x) + 1) / len(x),
            where="post",
            color=color,
            linewidth=1.1,
            label=r.label,
        )
    ax.set_xscale("log")
    ax.set_xlabel("time to first token of a raw call (ms, log scale)", fontsize=8)
    ax.set_ylabel("share of calls at or below", fontsize=8)
    ax.legend(fontsize=6.5, frameon=False, loc="lower right")
    style(ax)
    figures.save(fig, "fig-atk-ttft", [OPEN / r.file for r in RUNS])
    plt.close(fig)


def models_forest() -> None:
    base = challenge_pass(CHALLENGE_AFTER, "learned")
    knowledge = {c["id"] for c in cases() if c["cat"] == "knowledge"}
    ids = sorted(i for i in base if i not in knowledge)
    entries = [(r.label, model_challenge_pass(r), LEARNED) for r in RUNS]
    entries.append(("no language model", base, RAW))
    fig, ax = plt.subplots(figsize=(5.8, 2.6))
    for i, (_label, p, color) in enumerate(entries):
        k = sum(p[c] for c in ids)
        m, lo, hi = err(k, len(ids))
        ax.errorbar(
            m, i, xerr=[[lo], [hi]], fmt="o", color=color, markersize=4, capsize=2, linewidth=0.8
        )
    ax.axvline(sum(base[c] for c in ids) / len(ids), color=MUTED, linewidth=0.6, linestyle="--")
    ax.set_yticks(range(len(entries)), [e[0] for e in entries], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel(
        f"share of the {len(ids)} compared cases with the correct final outcome", fontsize=8
    )
    style(ax)
    figures.save(fig, "fig-mod-forest", [CHALLENGE_AFTER, *(OPEN / r.file for r in RUNS)])
    plt.close(fig)


def screening_latency() -> None:
    timeout = (
        float(re.search(r'COPILOT_LLM_TIMEOUT", "([0-9.]+)"', CONFIG.read_text()).group(1)) * 1000
    )
    runs = [d for d in screening() if "error" not in d["warmup"]]
    runs.sort(key=lambda d: np.median([c["total_ms"] for c in d["calls"]]))
    name = {"tokenfactory": "Token Factory", "featherless": "Featherless"}
    fig, ax = plt.subplots(figsize=(5.8, 2.9))
    rng = np.random.default_rng(0)
    for i, d in enumerate(runs):
        x = np.array([c["total_ms"] for c in d["calls"] if "error" not in c])
        valid = np.array([c["valid_label"] for c in d["calls"] if "error" not in c])
        y = i + rng.uniform(-0.18, 0.18, len(x))
        ax.scatter(
            x[valid],
            y[valid],
            s=9,
            color=LEARNED,
            alpha=0.8,
            label="valid label" if i == 0 else None,
        )
        ax.scatter(
            x[~valid],
            y[~valid],
            s=9,
            color=RAW,
            marker="x",
            label="invalid reply" if i == 0 else None,
        )
        ax.plot([np.median(x)] * 2, [i - 0.3, i + 0.3], color=INK, linewidth=1.2)
    ax.axvline(timeout, color=RAW, linewidth=0.8, linestyle="--")
    ax.annotate(
        "copilot model timeout", (timeout * 1.05, -0.45), fontsize=6.5, color=RAW, va="center"
    )
    ax.set_xscale("log")
    ax.set_yticks(range(len(runs)), [f"{d['model'].split('/')[-1]}, {name[d['provider']]}" for d in runs],
                  fontsize=6.8)  # fmt: skip
    ax.set_xlabel("total time of an intent-labelling call (ms, log scale); bar: median", fontsize=8)
    ax.set_ylim(len(runs) - 0.5, -0.8)
    ax.legend(fontsize=6.5, frameon=False, loc="center right")
    style(ax)
    figures.save(fig, "fig-scr-latency", sorted(SCREENING.glob("*.json")) + [CONFIG])
    plt.close(fig)


if __name__ == "__main__":
    retrieval()
    challenge_categories()
    violations()
    ttft()
    models_forest()
    screening_latency()
