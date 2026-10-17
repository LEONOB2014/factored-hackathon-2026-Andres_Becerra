"""Chapter 1 · The evaluations at a glance: what each measures, on how many items, and whether those items were held
out from every choice made about the copilot.

    REPORT_DOC=copilot uv run python scripts/copilot/claims/01_overview.py
"""

from __future__ import annotations

import pandas as pd

from report_lib.build import Chapter
from report_lib.copilot_data import (
    ATTACKS,
    CASES,
    DETAILS,
    KB,
    RUNS,
    cases,
    load,
    out,
    screening,
)
from report_lib.texgen import render_table


def main() -> None:
    ch = Chapter(1, "ovr")
    held = pd.read_csv(DETAILS / "held_out_intent.csv")
    kb_rows = pd.DataFrame(load(KB)["bundled"]["rows"])
    n_cases, n_attacks = len(cases()), len(load(ATTACKS))
    screened = screening()
    replays = sorted(DETAILS.glob("replay_*.json"))
    rows = [
        ("intent model", "the label given to a customer's message", f"{len(held)} phrasings",
         "written before tuning, never used to choose anything", "ch-intent"),
        ("knowledge retrieval", "the right governed document, and no document when none applies",
         f"{(kb_rows.split == 'test').sum()} test questions ({(kb_rows.split == 'dev').sum()} dev)",
         "threshold chosen on the dev split only", "ch-retrieval"),
        ("challenge set", "the final outcome of a conversation, and unsafe outcomes", f"{n_cases} cases",
         "frozen by a manifest before the first scored run", "ch-challenge"),
        ("attacks", "violations by a model alone and inside the copilot",
         f"{n_attacks} attacks, {len(RUNS)} models", "adapted public sets, never used for tuning", "ch-attacks"),
        ("challenge set with models", "the final outcome with each model inside the copilot",
         f"{n_cases} cases, {len(RUNS)} models", "the same frozen cases", "ch-models"),
        ("knowledge replay", "the knowledge cases with retrieval working",
         f"{sum(c['cat'] == 'knowledge' for c in cases())} cases, {len(replays)} models", "the same frozen cases",
         "ch-models"),
        ("speed screening", "time per call and well-formed replies in the labelling job",
         f"{screened[0]['n']} calls, {len(screened)} configurations", "no tuning involved", "ch-screening"),
    ]  # fmt: skip
    src = out("evaluations.csv")
    pd.DataFrame(rows, columns=["evaluation", "measures", "items", "held out", "chapter"]).drop(
        columns="chapter"
    ).to_csv(src, index=False)
    render_table(src, "evaluations", "The evaluations in this report.",
                 widths={"measures": "4.3cm", "items": "2.8cm", "held out": "4.3cm"})  # fmt: skip
    ch.count("evaluations", len(rows), src)
    ch.count("models", len(RUNS), src)
    ch.count("cases", n_cases, CASES)
    ch.count("attacks", n_attacks, ATTACKS)
    ch.write()


if __name__ == "__main__":
    main()
