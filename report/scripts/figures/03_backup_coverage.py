"""Figure 3.1 · Volume coverage of the backup copy: backup rows over main rows, per fact table and process month."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from report_lib import figures
from report_lib.paths import BUILD

SRC = BUILD / "sources" / "ch03_monthly_coverage.csv"


def main() -> None:
    cov = pd.read_csv(SRC)
    cov["ratio"] = cov.n_backup / cov.n_main.replace(0, np.nan)
    order = ["transactions", "digital_events", "call_center_interactions", "campaign_sends", "complaints",
             "call_transcripts", "satisfaction_surveys"]  # fmt: skip
    grid = cov.pivot(index="table", columns="ym", values="ratio").reindex(order)
    cmap = LinearSegmentedColormap.from_list("cov", ["#f2f0eb", "#9ecae1", "#2171b5", "#08306b"])
    cmap.set_bad("white")  # months without main rows; a backup gap is a pale (zero) cell
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    im = ax.imshow(np.ma.masked_invalid(grid.to_numpy(dtype=float)), aspect="auto", cmap=cmap, vmin=0, vmax=1.2,
                   interpolation="nearest")  # fmt: skip
    ax.set_yticks(range(len(order)), [t.replace("_", " ") for t in order], fontsize=7)
    cols = list(grid.columns)
    ticks = [i for i, c in enumerate(cols) if c.endswith(("-01", "-07"))]
    ax.set_xticks(ticks, [cols[i] for i in ticks], fontsize=7, rotation=0)
    ax.set_xlabel("process month", fontsize=8)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("backup rows / main rows", fontsize=7)
    cb.ax.tick_params(labelsize=6)
    ax.tick_params(length=2)
    figures.save(fig, "fig-03-backup-coverage", [SRC])
    plt.close(fig)


if __name__ == "__main__":
    main()
