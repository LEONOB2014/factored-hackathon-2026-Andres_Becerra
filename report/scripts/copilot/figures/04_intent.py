"""Figures 4.1-4.3 · The intent model on the held-out phrasings: confusion matrix, reliability diagram, and accuracy
against coverage as the confidence threshold moves (held out and out of fold).

    REPORT_DOC=copilot uv run python scripts/copilot/figures/04_intent.py
"""

from __future__ import annotations

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from report_lib import figures, protocol
from report_lib.copilot_data import DETAILS, INK, LEARNED, MUTED, PARAMS

HELD, OOF = DETAILS / "held_out_intent.csv", DETAILS / "oof_intent.csv"


def style(ax) -> None:
    ax.tick_params(labelsize=7, length=2)
    ax.spines[["top", "right"]].set_visible(False)


def confusion() -> None:
    h = pd.read_csv(HELD)
    labels = sorted(h.expected.unique())
    m = (
        pd.crosstab(h.expected, h.learned)
        .reindex(index=labels, columns=labels, fill_value=0)
        .to_numpy()
    )
    fig, ax = plt.subplots(figsize=(5.6, 4.9))
    ax.imshow(m, cmap="Blues", vmin=0)
    names = [x.replace("_", " ") for x in labels]
    ax.set_xticks(range(len(labels)), names, rotation=60, ha="right", fontsize=7)
    ax.set_yticks(range(len(labels)), names, fontsize=7)
    for i in range(len(labels)):
        for j in range(len(labels)):
            if m[i, j]:
                ax.text(j, i, str(m[i, j]), ha="center", va="center", fontsize=6.5,
                        color="white" if m[i, j] > m.max() / 2 else INK)  # fmt: skip
    ax.set_xlabel("label given by the learned model", fontsize=8)
    ax.set_ylabel("intent the phrasing was written for", fontsize=8)
    ax.tick_params(length=0)
    figures.save(fig, "fig-int-confusion", [HELD])
    plt.close(fig)


def reliability() -> None:
    h = pd.read_csv(HELD)
    bins = int(protocol.load()["stats"]["ece_bins"])
    conf, ok = h.confidence.to_numpy(), (h.learned == h.expected).to_numpy()
    edges = np.linspace(0, 1, bins + 1)
    xs, ys, ns = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            xs.append(conf[m].mean())
            ys.append(ok[m].mean())
            ns.append(int(m.sum()))
    fig, ax = plt.subplots(figsize=(3.4, 3.2))
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=0.8, linestyle="--")
    ax.plot(xs, ys, color=LEARNED, linewidth=1)
    ax.scatter(xs, ys, s=[12 + 3 * n for n in ns], color=LEARNED, zorder=3)
    for x, y, n in zip(xs, ys, ns, strict=True):
        ax.annotate(
            str(n), (x, y), textcoords="offset points", xytext=(5, -9), fontsize=6, color=INK
        )
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("mean confidence in the bin", fontsize=8)
    ax.set_ylabel("share labelled correctly", fontsize=8)
    style(ax)
    figures.save(fig, "fig-int-reliability", [HELD])
    plt.close(fig)


def coverage() -> None:
    threshold = json.loads(PARAMS.read_text())["params"]["threshold"]
    fig, ax = plt.subplots(figsize=(5.4, 3.1))
    for path, label, color in (
        (OOF, "training phrasings, out of fold", MUTED),
        (HELD, "held-out phrasings", LEARNED),
    ):
        d = pd.read_csv(path)
        conf, ok = d.confidence.to_numpy(), (d.learned == d.expected).to_numpy()
        ts = np.round(np.arange(0.20, 0.96, 0.01), 2)
        cov = [(conf >= t).mean() for t in ts]
        acc = [ok[conf >= t].mean() if (conf >= t).any() else np.nan for t in ts]
        ax.plot(cov, acc, color=color, linewidth=1.2, label=label)
        at = conf >= threshold
        ax.scatter([at.mean()], [ok[at].mean()], color=color, s=22, zorder=3)
    ax.annotate(f"threshold {threshold}", (0.6, 0.97), fontsize=7, color=INK)
    ax.set_xlabel("share of phrasings the model labels on its own (coverage)", fontsize=8)
    ax.set_ylabel("accuracy on those phrasings", fontsize=8)
    ax.legend(fontsize=7, frameon=False, loc="lower left")
    style(ax)
    figures.save(fig, "fig-int-coverage", [HELD, OOF, PARAMS])
    plt.close(fig)


if __name__ == "__main__":
    confusion()
    reliability()
    coverage()
