"""Figure 4.1 · Date offset between content-identical transactions of the two copies (the matched filter)."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from report_lib import figures
from report_lib.paths import BUILD

SRC = BUILD / "sources" / "ch04_matched_filter.csv"


def main() -> None:
    mf = pd.read_csv(SRC)
    fig, (ax, inset) = plt.subplots(
        1, 2, figsize=(7.2, 2.4), gridspec_kw={"width_ratios": [3, 1.2]}
    )
    wide = mf[mf.k.between(-400, 400)]
    ax.bar(wide.k, wide.n, width=1.0, color="#2171b5", linewidth=0)
    ax.set_xlabel("backup date minus main date (days)", fontsize=8)
    ax.set_ylabel("content-identical pairs", fontsize=8)
    ax.tick_params(labelsize=7, length=2)
    near = mf[mf.k.between(-14, 14)]
    inset.bar(near.k, near.n, width=0.8, color="#08306b", linewidth=0)
    inset.set_xlabel("near zero (days)", fontsize=8)
    inset.tick_params(labelsize=7, length=2)
    for a in (ax, inset):
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    figures.save(fig, "fig-04-matched-filter", [SRC])
    plt.close(fig)


if __name__ == "__main__":
    main()
