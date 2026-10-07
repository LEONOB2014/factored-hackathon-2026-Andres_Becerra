"""Figure 9.1 · Power of the level-shift detectors against planted steps in the real weekly series."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import NullFormatter, NullLocator

from report_lib import figures
from report_lib.paths import BUILD

SRC = BUILD / "sources" / "ch09_power.csv"
STYLE = {"kernel PELT (notebook)": ("#969696", "s"), "Gaussian PELT, BIC penalty": ("#2171b5", "o"),
         "binary segmentation, permutation": ("#cb181d", "^")}  # fmt: skip


def main() -> None:
    p = pd.read_csv(SRC)
    fig, ax = plt.subplots(figsize=(5.2, 2.8))
    for name, g in p.groupby("detector", sort=False):
        colour, marker = STYLE[name]
        ax.plot(
            100 * g["shift"],
            g.power,
            marker=marker,
            color=colour,
            markersize=3,
            linewidth=0.9,
            label=name,
        )
    ax.axhline(0.8, color="#252525", linewidth=0.5, linestyle=":")
    ax.set_xscale("log")
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xticks([2, 3, 5, 10, 20, 30], ["2", "3", "5", "10", "20", "30"])
    ax.set_xlabel("planted step in weekly log volume (per cent)", fontsize=7)
    ax.set_ylabel("share of steps found", fontsize=7)
    ax.set_ylim(0, 1.02)
    ax.tick_params(labelsize=6, length=2)
    ax.legend(fontsize=6, frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    figures.save(fig, "fig-09-power", [SRC])
    plt.close(fig)


if __name__ == "__main__":
    main()
