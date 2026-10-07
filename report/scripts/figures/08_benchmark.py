"""Figure 8.1 · Injected benchmark: average precision with customer-resampled intervals, and recall by anomaly type."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from report_lib import figures
from report_lib.paths import BUILD

AP = BUILD / "sources" / "ch08_benchmark_ap.csv"
REC = BUILD / "sources" / "ch08_recall_by_type.csv"


def main() -> None:
    ap = pd.read_csv(AP)
    rec = pd.read_csv(REC).set_index("detector").loc[ap.detector]
    fig, (a, b) = plt.subplots(
        1, 2, figsize=(6.6, 3.4), gridspec_kw={"width_ratios": [1, 1.25]}, sharey=True
    )
    y = range(len(ap))[::-1]
    a.errorbar(ap["average precision"], list(y), xerr=[ap["average precision"] - ap.lower, ap.upper - ap["average precision"]],
               fmt="o", color="#2171b5", markersize=3, capsize=2, linewidth=0.8)  # fmt: skip
    a.set_yticks(list(y), ap.detector, fontsize=6)
    a.set_xlim(0, 1)
    a.set_xlabel("average precision", fontsize=7)
    a.tick_params(labelsize=6, length=2)
    a.spines[["top", "right"]].set_visible(False)
    im = b.imshow(rec.to_numpy(), aspect="auto", cmap="Blues", vmin=0, vmax=1,
                  extent=(-0.5, rec.shape[1] - 0.5, -0.5, len(ap) - 0.5))  # fmt: skip
    for i, row in enumerate(rec.to_numpy()):
        for j, v in enumerate(row):
            b.text(j, len(ap) - 1 - i, f"{v:.2f}", ha="center", va="center", fontsize=5,
                   color="white" if v > 0.6 else "#252525")  # fmt: skip
    b.set_xticks(range(rec.shape[1]), [c.replace(" ", "\n") for c in rec.columns], fontsize=6)
    b.tick_params(length=0)
    fig.colorbar(im, ax=b, fraction=0.04, pad=0.02).ax.tick_params(labelsize=6)
    a.set_title("average precision, 95 % interval", fontsize=7)
    b.set_title("recall in the top hundredth of rows", fontsize=7)
    fig.tight_layout()
    figures.save(fig, "fig-08-benchmark", [AP, REC])
    plt.close(fig)


if __name__ == "__main__":
    main()
