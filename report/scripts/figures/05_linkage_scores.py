"""Figure 5.1 · Fellegi-Sunter scores of candidate customer pairs, by whether the pair shares an ID."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from report_lib import figures
from report_lib.paths import BUILD

SRC = BUILD / "sources" / "ch05_fs_scores.csv"


def main() -> None:
    h = pd.read_csv(SRC)
    fig, ax = plt.subplots(figsize=(6.4, 2.4))
    for cls, colour in (("different ID", "#fd8d3c"), ("shares an ID", "#2171b5")):
        d = h[h.cls == cls]
        ax.bar(d["bin"] + 0.5, d.n, width=1.0, color=colour, alpha=0.75, label=cls, linewidth=0)
    ax.axvline(10, color="#252525", linewidth=0.8, linestyle="--")
    ax.set_xlabel("log-likelihood-ratio score (bits)", fontsize=8)
    ax.set_yscale("log")
    ax.set_ylabel("candidate pairs (log scale)", fontsize=8)
    ax.legend(fontsize=7, frameon=False)
    ax.tick_params(labelsize=7, length=2)
    ax.spines[["top", "right"]].set_visible(False)
    sizes = h.groupby("cls").n.sum().to_dict()
    figures.save(fig, "fig-05-linkage-scores", [SRC], group_sizes=sizes)
    plt.close(fig)


if __name__ == "__main__":
    main()
