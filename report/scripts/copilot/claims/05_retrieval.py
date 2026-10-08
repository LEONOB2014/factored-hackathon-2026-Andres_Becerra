"""Chapter 5 · Knowledge retrieval: four retrievers on the held-out questions, with the relevance threshold each
chose on the dev split.

Recomputes every rate from the stored per-question rows (and checks it against the stored summary), with Wilson
intervals over the test questions; the mean reciprocal rank gets a bootstrap interval.

    REPORT_DOC=copilot uv run python scripts/copilot/claims/05_retrieval.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from report_lib import protocol
from report_lib.build import Chapter
from report_lib.copilot_data import KB, load, out
from report_lib.estimators.intervals import wilson
from report_lib.estimators.resampling import bootstrap
from report_lib.texgen import render_table

KEYS = {
    "bundled": "bundled",
    "pgvector": "pgvector",
    "graph": "graph",
    "hybrid(pgvector+graph)": "hybrid",
}
STORED = "stored by the retrieval run, which records no interval"


def main() -> None:
    P = protocol.load()["stats"]
    ch = Chapter(5, "kb")
    report = load(KB)
    table = []
    for name, key in KEYS.items():
        r = report[name]
        rows = pd.DataFrame(r["rows"])
        test, dev = rows[rows.split == "test"], rows[rows.split == "dev"]
        ans, none = test[test.expect.notna()], test[test.expect.isna()]
        rank = ans["rank"].astype(float)
        hit1, hit3 = int((rank == 1).sum()), int((rank <= 3).sum())
        kept = int((ans.top_score >= r["threshold"]).sum())
        rejected = int((none.top_score < r["threshold"]).sum())
        recip = np.nan_to_num(1 / rank.to_numpy(), nan=0.0)
        for stored, mine in ((r["hit@1"], hit1 / len(ans)), (r["hit@3"], hit3 / len(ans)),
                             (r["answerable_kept"], kept / len(ans)), (r["unanswerable_rejected"], rejected / len(none)),
                             (r["mrr"], recip.mean())):  # fmt: skip
            if round(mine, 3) != stored:
                raise SystemExit(f"{name}: recomputed {mine:.3f} differs from the stored {stored}")
        ch.constant(f"{key}-threshold", r["threshold"], KB, digits=3)
        ch.proportion(f"{key}-hit1", hit1, len(ans), wilson(hit1, len(ans)), KB)
        ch.proportion(f"{key}-hit3", hit3, len(ans), wilson(hit3, len(ans)), KB)
        ch.proportion(f"{key}-kept", kept, len(ans), wilson(kept, len(ans)), KB)
        ch.proportion(f"{key}-rejected", rejected, len(none), wilson(rejected, len(none)), KB)
        ch.metric(
            f"{key}-mrr",
            bootstrap(recip, np.mean, int(P["bootstrap_reps"]), int(P["seed"])),
            len(ans),
            KB,
        )
        ch.count(f"{key}-violations", r["governance_violations"], KB)
        ch.count(f"{key}-graph-hits", r["graph_expanded_hits"], KB)
        ch.descriptive(f"{key}-ms-p50", r["latency_ms_p50"], KB, STORED, unit="ms", digits=3)
        ch.descriptive(f"{key}-ms-p95", r["latency_ms_p95"], KB, STORED, unit="ms", digits=3)
        table.append({"retriever": key, "threshold": r["threshold"], "hit@1": hit1 / len(ans),
                      "hit@3": hit3 / len(ans), "MRR": recip.mean(), "answerable kept": kept / len(ans),
                      "unanswerable rejected": rejected / len(none), "governance violations": r["governance_violations"],
                      "p50 ms": r["latency_ms_p50"], "p95 ms": r["latency_ms_p95"]})  # fmt: skip
    ch.count("questions", len(rows), KB)
    ch.count("test", len(test), KB)
    ch.count("dev", len(dev), KB)
    ch.count("test-answerable", len(ans), KB)
    ch.count("test-unanswerable", len(none), KB)
    ch.count("dev-unanswerable", int(dev.expect.isna().sum()), KB)
    src = out("retrieval.csv")
    pd.DataFrame(table).to_csv(src, index=False)
    render_table(src, "retrieval", "Retrievers on the held-out test questions. Rates are over the answerable "
                 "questions, except the rejection rate, which is over the unanswerable ones.", digits=3)  # fmt: skip
    ch.write()


if __name__ == "__main__":
    main()
