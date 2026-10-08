"""Chapter 6 · The frozen challenge set: what it contains, how the keyword router and the learned intent model score
on it inside the same copilot (no language model), and the rerun after the one fix.

The first scored run is the held-out result. The rerun after the fix is reported as such: the fix was made after
seeing that run's failures, so the rerun no longer measures held-out performance.

    REPORT_DOC=copilot uv run python scripts/copilot/claims/06_challenge.py
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from report_lib.build import Chapter
from report_lib.copilot_data import CASES, CHALLENGE, CHALLENGE_AFTER, cases, load, out
from report_lib.estimators.intervals import wilson
from report_lib.estimators.resampling import mcnemar_exact
from report_lib.texgen import render_table

METRICS = {"correct": "correct", "safe_automated_resolution_in_scope": "safe-in-scope",
           "safe_automated_resolution_attempted": "safe-attempted", "containment": "containment",
           "missed_transfers": "missed", "unnecessary_transfers": "unnecessary", "unsafe_cases": "unsafe"}  # fmt: skip
STORED = "stored by the challenge run, which records no interval"


def expected(e: dict) -> str:
    out_ = e["outcome"] if isinstance(e["outcome"], str) else " or ".join(e["outcome"])
    return (
        out_
        + (f" ({e['queue']})" if e.get("queue") else "")
        + (f", {e['action']}" if e.get("action") else "")
    )


def main() -> None:
    ch = Chapter(6, "chl")
    cs = cases()
    ch.count("cases", len(cs), CASES)
    for lang, n in Counter(c["lang"] for c in cs).items():
        ch.count(f"cases-{lang}", n, CASES)
    for scope, n in Counter(c["scope"] for c in cs).items():
        ch.count(f"scope-{scope}", n, CASES)
    cats = Counter(c["cat"] for c in cs)
    ch.count("categories", len(cats), CASES)
    ch.count("multi-turn", sum(len(c["turns"]) > 1 for c in cs), CASES)
    comp = [{"category": k.replace("_", " "), "cases": v,
             "es": sum(c["cat"] == k and c["lang"] == "es" for c in cs),
             "pt": sum(c["cat"] == k and c["lang"] == "pt" for c in cs),
             "scope": "/".join(sorted({c["scope"] for c in cs if c["cat"] == k}))} for k, v in sorted(cats.items())]  # fmt: skip
    src = out("challenge_composition.csv")
    pd.DataFrame(comp).to_csv(src, index=False)
    render_table(src, "challenge-composition", "The frozen challenge set by category: cases in each language and "
                 "the scope the copilot is expected to handle them in (resolve alone, escalate to a person, or "
                 "guard: refuse, deny or ask for authentication).")  # fmt: skip

    for path, tag in ((CHALLENGE, "first"), (CHALLENGE_AFTER, "after")):
        rep = load(path)
        if tag == "first":
            ch.count("manifest-ok", int(rep["manifest_ok"]), path)
        for variant in ("keyword", "learned"):
            s = rep["variants"][variant]["summary"]
            rows = rep["variants"][variant]["rows"]
            if sum(r["pass"] for r in rows) != s["all"]["correct"]["k"]:
                raise SystemExit(f"{path.name} {variant}: rows and summary disagree")
            for key, topic in METRICS.items():
                m = s["all"][key]
                ch.proportion(
                    f"{tag}-{variant}-{topic}", m["k"], m["n"], wilson(m["k"], m["n"]), path
                )
            if tag == "first":
                for lang in ("es", "pt"):
                    m = s[lang]["correct"]
                    ch.proportion(
                        f"{tag}-{variant}-correct-{lang}",
                        m["k"],
                        m["n"],
                        wilson(m["k"], m["n"]),
                        path,
                    )
                ch.descriptive(
                    f"{variant}-ms-p50",
                    s["all"]["latency_ms_p50"],
                    path,
                    STORED,
                    unit="ms",
                    digits=2,
                )
                ch.descriptive(
                    f"{variant}-ms-p95",
                    s["all"]["latency_ms_p95"],
                    path,
                    STORED,
                    unit="ms",
                    digits=3,
                )
        a = {r["id"]: r["pass"] for r in rep["variants"]["learned"]["rows"]}
        b = {r["id"]: r["pass"] for r in rep["variants"]["keyword"]["rows"]}
        ids = sorted(a)
        t = mcnemar_exact([a[i] for i in ids], [b[i] for i in ids])
        if tag == "first":
            ch.count("mcnemar-b", t.b, path)
            ch.count("mcnemar-c", t.c, path)
            ch.test("mcnemar", t.b, t.p, t.p, "challenge-learned-vs-keyword", 1, path,
                    null="equal accuracy of learned and keyword routing on the frozen cases", method="exact McNemar")  # fmt: skip

    first = load(CHALLENGE)
    # by category, first scored run, both variants (for the figure and the appendix)
    by_cat = []
    for variant in ("keyword", "learned"):
        for cat, grp in pd.DataFrame(first["variants"][variant]["rows"]).groupby("cat"):
            by_cat.append(
                {
                    "variant": variant,
                    "category": cat,
                    "passed": int(grp["pass"].sum()),
                    "cases": len(grp),
                }
            )
    pd.DataFrame(by_cat).to_csv(out("challenge_by_category.csv"), index=False)
    # the failures of the production configuration (learned), first scored run
    fails = []
    for r in first["variants"]["learned"]["rows"]:
        if not r["pass"]:
            fails.append({"case": r["id"], "lang": r["lang"], "category": r["cat"].replace("_", " "),
                          "expected": expected(r["expected"]), "got": r["outcome"],
                          "unsafe": ", ".join(u.replace("_", " ") for u in r["unsafe"]) or "no"})  # fmt: skip
    ch.count("learned-failures", len(fails), CHALLENGE)
    src = out("challenge_failures.csv")
    pd.DataFrame(fails).to_csv(src, index=False)
    render_table(src, "challenge-failures", "Every case the learned configuration failed in the first scored run, "
                 "with the outcome the case required and the outcome it got.",
                 widths={"expected": "4.2cm"})  # fmt: skip
    ch.write()


if __name__ == "__main__":
    main()
