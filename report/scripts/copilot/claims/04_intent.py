"""Chapter 4 · The intent model: training data, tuning, the confidence threshold, and the held-out comparison with
the keyword baseline.

Reads the per-phrasing export (copilot/eval/export_details.py) and the stored tuning record. Held-out phrasings are
independent items (Wilson intervals, exact McNemar, bootstrap of macro-F1). Out-of-fold training phrasings are not:
each base phrasing appears with its variants, so their rates resample whole base phrasings (cluster bootstrap).

    REPORT_DOC=copilot uv run python scripts/copilot/claims/04_intent.py
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

from report_lib import protocol
from report_lib.build import Chapter
from report_lib.copilot_data import DETAILS, INTENT, PARAMS, out
from report_lib.estimators.intervals import cluster_bootstrap_ratio, wilson
from report_lib.estimators.resampling import bootstrap, mcnemar_exact
from report_lib.texgen import render_table

STORED = "stored by the tuning run, which records no interval"
HELD, OOF, SUMMARY = (
    DETAILS / "held_out_intent.csv",
    DETAILS / "oof_intent.csv",
    DETAILS / "training_summary.json",
)


def ece(conf: np.ndarray, correct: np.ndarray, bins: int) -> float:
    """Expected calibration error over equal-width bins, as the tuning script computes it."""
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def main() -> None:
    P = protocol.load()["stats"]
    reps, seed = int(P["bootstrap_reps"]), int(P["seed"])
    ch = Chapter(4, "int")

    s = json.loads(SUMMARY.read_text())
    for topic, v in (("base-phrasings", s["base_phrasings"]), ("augmented", s["augmented_phrasings"]),
                     ("intents", s["intents"]), ("base-es", s["base_by_language"]["es"]),
                     ("base-pt", s["base_by_language"]["pt"]), ("base-transcripts", s["base_by_source"]["transcripts"]),
                     ("held-out", s["held_out_phrasings"]), ("folds", s["folds"])):  # fmt: skip
        ch.count(topic, v, SUMMARY)

    tuned = json.loads(PARAMS.read_text())
    p = tuned["params"]
    ch.constant("reg-c", p["C"], PARAMS, digits=3)
    ch.constant("ngram-min", p["ngram_min"], PARAMS)
    ch.constant("ngram-max", p["ngram_max"], PARAMS)
    ch.constant("threshold", p["threshold"], PARAMS)
    ch.constant("target-precision", tuned["target_precision"], PARAMS)
    ch.descriptive("cv-f1", tuned["cv_macro_f1"], PARAMS, STORED, digits=3)

    # out of fold, clustered by base phrasing
    o = pd.read_csv(OOF)
    o["ok"] = (o.learned == o.expected).astype(float)
    o["confident"] = (o.confidence >= p["threshold"]).astype(float)
    g = o.group.to_numpy()
    ch.proportion("oof-accuracy", o.ok.sum(), len(o), cluster_bootstrap_ratio(o.ok, np.ones(len(o)), g, B=reps,
                  seed=seed), OOF, cluster_unit="base phrasing")  # fmt: skip
    ch.proportion("oof-coverage", o.confident.sum(), len(o),
                  cluster_bootstrap_ratio(o.confident, np.ones(len(o)), g, B=reps, seed=seed), OOF,
                  cluster_unit="base phrasing")  # fmt: skip
    ch.proportion("oof-acc-confident", (o.ok * o.confident).sum(), o.confident.sum(),
                  cluster_bootstrap_ratio(o.ok * o.confident, o.confident, g, B=reps, seed=seed), OOF,
                  cluster_unit="base phrasing")  # fmt: skip
    ch.count("oof-groups", o.group.nunique(), OOF)

    # held out
    h = pd.read_csv(HELD)
    n = len(h)
    y = h.expected.to_numpy()
    learned_ok, keyword_ok = (
        (h.learned == h.expected).to_numpy(),
        (h.keyword == h.expected).to_numpy(),
    )
    for name, ok in (("learned", learned_ok), ("keyword", keyword_ok)):
        ch.proportion(f"acc-{name}", ok.sum(), n, wilson(ok.sum(), n), HELD)
        for lang in ("es", "pt"):
            m = (h.lang == lang).to_numpy()
            ch.proportion(
                f"acc-{name}-{lang}", ok[m].sum(), m.sum(), wilson(ok[m].sum(), m.sum()), HELD
            )
        pred = h[name].to_numpy()
        ch.metric(f"f1-{name}", bootstrap(np.arange(n), lambda i, pred=pred: f1_score(y[i], pred[i], average="macro",
                  zero_division=0), reps, seed), n, HELD)  # fmt: skip
    conf = h.confidence.to_numpy()
    ch.descriptive("ece-learned", ece(conf, learned_ok.astype(float), int(P["ece_bins"])), HELD,
                   "expected calibration error: a summary of the reliability diagram, no interval", digits=2)  # fmt: skip
    confident = conf >= p["threshold"]
    ch.proportion("cover", confident.sum(), n, wilson(confident.sum(), n), HELD)
    ch.proportion("acc-confident", (learned_ok & confident).sum(), confident.sum(),
                  wilson((learned_ok & confident).sum(), confident.sum()), HELD)  # fmt: skip
    ch.proportion("acc-unsure", (learned_ok & ~confident).sum(), (~confident).sum(),
                  wilson((learned_ok & ~confident).sum(), (~confident).sum()), HELD)  # fmt: skip
    t = mcnemar_exact(learned_ok, keyword_ok)
    ch.count("mcnemar-b", t.b, HELD)
    ch.count("mcnemar-c", t.c, HELD)
    ch.test("mcnemar", t.b, t.p, t.p, "intent-vs-keyword", 1, HELD, null="equal held-out accuracy",
            method="exact McNemar")  # fmt: skip
    ch.count("errors", int((~learned_ok).sum()), HELD)
    ch.count("errors-oos", int(((~learned_ok) & (y == "out_of_scope")).sum()), HELD)
    ch.count("oos-items", int((y == "out_of_scope").sum()), HELD)

    stored = json.loads(INTENT.read_text())["held_out"][0]
    ch.descriptive("ms-p50", stored["latency_ms_p50"], INTENT, STORED, unit="ms", digits=2)
    ch.descriptive("ms-p95", stored["latency_ms_p95"], INTENT, STORED, unit="ms", digits=2)

    # per-intent recall, both systems
    rows = []
    for intent, grp in h.groupby("expected"):
        rows.append({"intent": intent.replace("_", " "), "phrasings": len(grp),
                     "learned": (grp.learned == intent).mean(), "keyword": (grp.keyword == intent).mean()})  # fmt: skip
    per = out("intent_recall.csv")
    pd.DataFrame(rows).to_csv(per, index=False)
    render_table(per, "intent-recall", "Held-out recall by intent: the share of each intent's phrasings that the "
                 "learned model and the keyword baseline label correctly.", digits=2)  # fmt: skip
    ch.write()


if __name__ == "__main__":
    main()
