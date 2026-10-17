"""Chapter 1 · A census of the report itself: the claims of chapters 3 to 19, the notebook map and the bibliography.

Named 99 so that `make claims` runs it after every chapter it counts; it writes chapter 1's claims file, which it
excludes from its own counts. The counted summary is written to build/sources/ch01_ledger_census.csv, whose digest
every claim here records.

    uv run python scripts/claims/99_ledger_census.py
"""

from __future__ import annotations

import collections
import csv

import pandas as pd

from report_lib import claims
from report_lib.build import Chapter
from report_lib.paths import BUILD, CLAIMS_DIR, CONF

OUT = BUILD / "sources" / "ch01_ledger_census.csv"
CLUSTERED = {"cluster-bootstrap", "block-bootstrap", "wild-cluster-bootstrap", "cr2"}
IID = {"naive-iid", "wilson-iid", "poisson-exact"}


def census() -> dict[str, int]:
    ledger = {k: c for k, c in claims.load_all(CLAIMS_DIR).items() if c.chapter != 1}
    status = collections.Counter(c.status for c in ledger.values())
    methods = [c.interval_method for c in ledger.values() if c.interval_method]
    nb = pd.read_csv(CONF / "notebook_map.csv", keep_default_na=False)
    with (CONF / "bib_verification.csv").open() as f:
        bib = list(csv.DictReader(f))
    return {
        "claims": len(ledger),
        "exploratory": status["exploratory"],
        "registered": status["registered"],
        "positive-control": status["positive-control"],
        "chapters": len({c.chapter for c in ledger.values()}),
        "sources": len({(c.source_path, c.source_sha256) for c in ledger.values()}),
        "with-interval": len(methods),
        "clustered": sum(m in CLUSTERED for m in methods),
        "iid": sum(m in IID for m in methods),
        "naive": sum(m == "naive-iid" for m in methods),
        "notebooks": nb["notebook"].nunique(),
        "headings": len(nb),
        "headings-mapped": int((nb["report_label"] != "").sum()),
        "headings-out": int((nb["out_of_scope_reason"] != "").sum()),
        "references": len(bib),
    }


def main() -> None:
    counts = census()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(counts.items()), columns=["quantity", "value"]).to_csv(OUT, index=False)
    ch = Chapter(1, "ch01")
    for topic, value in counts.items():
        ch.count(f"ledger-{topic}", value, OUT)
    print(ch.write(), counts)


if __name__ == "__main__":
    main()
