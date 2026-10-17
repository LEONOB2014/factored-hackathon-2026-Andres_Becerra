"""Figure 7.1 · The empty-share check on campaign sends: all rows against the fixed band, applicable rows against z."""

from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from report_lib import figures
from report_lib.paths import BUILD

SRC = BUILD / "sources" / "ch07_empty_share_daily.csv"
BAND = 0.3


def main() -> None:
    d = pd.read_csv(SRC, parse_dates=["day"])
    fig, axes = plt.subplots(2, 2, figsize=(6.4, 3.8), sharex=True)
    for row, (col, label) in enumerate((("subject", "subject"), ("was_opened", "was opened"))):
        a, b = axes[row]
        base = d[f"{col}_baseline"].iloc[0]
        a.axhspan(base - BAND, base + BAND, color="#deebf7", linewidth=0)
        a.axhline(base, color="#2171b5", linewidth=0.6)
        a.plot(d.day, d[f"{col}_all"], color="#252525", linewidth=0.4)
        out = (d[f"{col}_all"] - base).abs() >= BAND
        a.plot(d.day[out], d[f"{col}_all"][out], "o", color="#cb181d", markersize=2)
        a.set_ylim(0, 1)
        a.set_ylabel(f"{label}\nempty share", fontsize=7)
        b.fill_between(
            d.day, d[f"{col}_cond_lo"], d[f"{col}_cond_hi"], color="#deebf7", linewidth=0
        )
        b.axhline(d[f"{col}_cond_baseline"].iloc[0], color="#2171b5", linewidth=0.6)
        b.plot(d.day, d[f"{col}_cond"], color="#252525", linewidth=0.4)
        b.set_ylim(0, 0.2)
        for ax in (a, b):
            ax.tick_params(labelsize=6, length=2)
            ax.spines[["top", "right"]].set_visible(False)
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[0, 0].set_title("all rows: contract baseline, fixed band", fontsize=7)
    axes[0, 1].set_title("applicable rows: reference baseline, binomial band", fontsize=7)
    fig.tight_layout()
    figures.save(fig, "fig-07-empty-share", [SRC])
    plt.close(fig)


if __name__ == "__main__":
    main()
