"""Figure 6.1 · Classifier two-sample test: AUC of separating main rows from backup rows, against the halves baseline."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from report_lib import figures
from report_lib.paths import TABLES

SRC = TABLES / "c2st.csv"


def main() -> None:
    c = pd.read_csv(SRC).sort_values("auc_main_vs_backup")
    fig, ax = plt.subplots(figsize=(6.0, 2.4))
    y = range(len(c))
    ax.errorbar(c.auc_baseline, y, xerr=1.96 * c.sd_baseline, fmt="o", color="#969696", markersize=4,
                label="main half against main half", capsize=2)  # fmt: skip
    ax.errorbar(c.auc_main_vs_backup, y, xerr=1.96 * c["sd"], fmt="o", color="#2171b5", markersize=4,
                label="main against backup", capsize=2)  # fmt: skip
    ax.axvline(0.5, color="#252525", linewidth=0.6, linestyle="--")
    ax.set_yticks(list(y), [t.replace("_", " ") for t in c.table], fontsize=7)
    ax.set_xlabel("cross-validated AUC", fontsize=8)
    ax.tick_params(labelsize=7, length=2)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    figures.save(fig, "fig-06-c2st", [SRC])
    plt.close(fig)


if __name__ == "__main__":
    main()
