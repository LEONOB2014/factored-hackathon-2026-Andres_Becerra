"""Compare the retrievers on eval/kb_questions.yaml: hit@1, hit@3, MRR, no-answer handling, governance, latency.

    cd copilot && uv run python eval/kb_retrieval.py            # bundled only (no dev stack)
    uv run python eval/kb_retrieval.py --stack                   # + pgvector, Neo4j GraphRAG and hybrid
Writes eval/reports/kb_retrieval.{json,md}. The relevance threshold (below it the copilot says it has no document)
is chosen on the dev split only: the midpoint between answerable and unanswerable top scores.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import yaml

from copilot.kb import (
    BundledRetriever,
    GraphRetriever,
    HybridRetriever,
    PgVectorRetriever,
    active_chunks,
)

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
THRESHOLD_FILE = HERE.parent / "corpus" / "kb_threshold.json"


def run(retriever, questions, k: int = 3) -> list[dict]:
    rows = []
    for q in questions:
        r = retriever.search(q["q"], k)
        docs = [c.doc_id for c in r.chunks]
        rank = next((i + 1 for i, d in enumerate(docs) if d == q["expect"]), None)
        rows.append(
            {
                **q,
                "docs": docs,
                "top_score": r.chunks[0].score if r.chunks else 0.0,
                "rank": rank,
                "ms": r.ms,
                "via": [c.via for c in r.chunks],
            }
        )
    return rows


def threshold(rows: list[dict]) -> float:
    pos = [r["top_score"] for r in rows if r["split"] == "dev" and r["expect"] and r["rank"] == 1]
    neg = [r["top_score"] for r in rows if r["split"] == "dev" and not r["expect"]]
    if not pos or not neg:
        return 0.0
    return round((min(pos) + max(neg)) / 2, 4)


def metrics(rows: list[dict], thr: float) -> dict:
    test = [r for r in rows if r["split"] == "test"]
    ans = [r for r in test if r["expect"]]
    none = [r for r in test if not r["expect"]]
    active = {c.doc_id for c in active_chunks()}
    return {
        "n_test": len(test),
        "hit@1": round(sum(r["rank"] == 1 for r in ans) / len(ans), 3),
        "hit@3": round(sum(r["rank"] is not None and r["rank"] <= 3 for r in ans) / len(ans), 3),
        "mrr": round(sum(1 / r["rank"] for r in ans if r["rank"]) / len(ans), 3),
        "answerable_kept": round(sum(r["top_score"] >= thr for r in ans) / len(ans), 3),
        "unanswerable_rejected": round(sum(r["top_score"] < thr for r in none) / len(none), 3),
        "governance_violations": sum(d not in active for r in test for d in r["docs"]),
        "graph_expanded_hits": sum(
            any(str(v).startswith(("graph", "graph:")) or "graph:" in str(v) for v in r["via"])
            for r in test
        ),
        "latency_ms_p50": round(statistics.median(r["ms"] for r in test), 1),
        "latency_ms_p95": round(sorted(r["ms"] for r in test)[int(0.95 * (len(test) - 1))], 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stack", action="store_true", help="also query pgvector and Neo4j on the dev stack"
    )
    args = ap.parse_args()
    questions = yaml.safe_load((HERE / "kb_questions.yaml").read_text())["questions"]
    retrievers = [BundledRetriever()]
    if args.stack:
        pg, graph = PgVectorRetriever(), GraphRetriever()
        retrievers += [pg, graph, HybridRetriever(pg, graph)]
    report = {}
    bundled_rows = None
    for r in retrievers:
        r.search("warm up", 1)
        rows = run(r, questions)
        bundled_rows = bundled_rows or rows
        thr = threshold(rows)
        report[r.name] = {"threshold": thr, **metrics(rows, thr), "rows": rows}
    # the deployed copilot uses the bundled retriever's dev-chosen threshold
    THRESHOLD_FILE.write_text(
        json.dumps({"retriever": "bundled", "threshold": report["bundled"]["threshold"]}) + "\n"
    )
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "kb_retrieval.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    )
    cols = [
        "threshold",
        "hit@1",
        "hit@3",
        "mrr",
        "answerable_kept",
        "unanswerable_rejected",
        "governance_violations",
        "graph_expanded_hits",
        "latency_ms_p50",
        "latency_ms_p95",
    ]
    md = [
        "# Knowledge-base retrieval: held-out comparison",
        "",
        f"{len(questions)} ES/PT questions over English documents (`eval/kb_questions.yaml`); thresholds chosen on the dev split, metrics on the test split. "
        "Governance violations count any returned chunk of a document outside the active set (retired, superseded, draft or expired).",
        "",
        "| retriever | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    md += [
        f"| {name} | " + " | ".join(str(v[c]) for c in cols) + " |" for name, v in report.items()
    ]
    (REPORTS / "kb_retrieval.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
