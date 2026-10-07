"""Seed conf/notebook_map.csv: every level-1/2 heading of the 65 sources, mapped to its primary chapter.

    uv run python scripts/build_notebook_map.py [--force]

The map is then curated by hand; rows already present keep their values. Primary chapters follow the design's
chapter plan; the section overrides below send specific sections to a second chapter.
"""

from __future__ import annotations

import argparse
import csv
import re

from report_lib.traceability import FIELDS, MAP, headings, notebook_id, sources

PRIMARY = [
    (r"^0[12]_", "ch:inventory-keys"),
    (r"^03_", "ch:time-and-clocks"),
    (r"^0[45]_", "ch:record-linkage"),
    (r"^06_", "ch:statistical-equivalence"),
    (r"^(0[789]|1[01])_", "ch:anomaly-detection"),
    (r"^medallion/", "ch:inventory-keys"),
    (r"^model_risk/", "ch:schema-forensics"),
    (r"^pipeline/0[1456]_", "ch:conformance"),
    (r"^pipeline/0[23]_", "ch:schema-forensics"),
    (r"^pipeline/0[789]_", "ch:marts-and-features"),
    (r"^pipeline/1[01]_", "ch:graph-and-privacy"),
    (r"^pipeline/12_", "ch:audit-and-gates"),
    (r"^country_template/01_", "ch:inventory-keys"),
    (r"^country_template/0[23]_", "ch:schema-forensics"),
    (r"^country_template/04_", "ch:time-and-clocks"),
    (r"^country_template/0[56]_", "ch:conformance"),
    (r"^country_template/0[789]_", "ch:marts-and-features"),
    (r"^country_template/1[01]_", "ch:graph-and-privacy"),
    (r"^country_template/12_", "ch:audit-and-gates"),
    (r"^country_template/13_", "ch:anomaly-detection"),
    (r"^country_template/14_", "ch:learnability"),
    (r"^country_compare/", "ch:learnability"),
    (r"^dataset_compare/", "ch:statistical-equivalence"),
    (r"^granularity/01_", "ch:aggregation"),
    (r"^granularity/0[23]_", "ch:customer-dynamics"),
    (r"^granularity/0[456]_", "ch:operations"),
    (r"^granularity/0[78]_", "ch:products-and-campaigns"),
    (r"^granularity/09_", "ch:readiness-gates"),
    (r"^granularity_time/01_", "ch:time-and-clocks"),
    (r"^granularity_time/02_", "ch:operations"),
    (r"^granularity_time/0[345]_", "ch:products-and-campaigns"),
    (r"^granularity_hour/01_", "ch:aggregation"),
    (r"^granularity_hour/02_", "ch:customer-dynamics"),
    (r"^granularity_hour/0[3456]_", "ch:operations"),
    (r"^granularity_hour/07_", "ch:products-and-campaigns"),
    (r"^granularity_hour/0[89]_", "ch:readiness-gates"),
]
# (notebook regex, heading regex) -> label: sections whose method belongs to another chapter.
SECTIONS = [
    (r"^country_template/13_", r"^[12] ·", "ch:change-points"),
    (r"^granularity/04_", r"^5 ·", "ch:change-points"),
    (r"^granularity_time/02_", r"^5 ·", "ch:change-points"),
    (r"^granularity/09_", r"^[12] ·", "ch:aggregation"),
    (r"^pipeline/09_", r"^4 ·", "ch:learnability"),
]
EXPLORER = re.compile(r"(?i)\binteractive explorer\b|^\d+ · explorer\b|^explorer\b")


def label_for(nb: str, heading: str) -> tuple[str, str]:
    if EXPLORER.search(heading):
        return "", "interactive widget; its content is covered by the sections it explores"
    for nre, hre, label in SECTIONS:
        if re.search(nre, nb) and re.search(hre, heading):
            return label, ""
    for nre, label in PRIMARY:
        if re.search(nre, nb):
            return label, ""
    raise SystemExit(f"no chapter for {nb}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="discard curated rows and reseed")
    a = ap.parse_args()
    existing = {}
    if MAP.exists() and not a.force:
        with MAP.open() as f:
            existing = {(r["notebook"], r["heading"]): r for r in csv.DictReader(f)}
    rows = []
    for path in sources():
        nb = notebook_id(path)
        for level, heading in headings(path):
            key = (nb, heading)
            if key in existing:
                rows.append(existing[key])
                continue
            label, reason = label_for(nb, heading)
            rows.append({"notebook": nb, "level": str(level), "heading": heading, "report_label": label,
                         "out_of_scope_reason": reason, "data_window_end": ""})  # fmt: skip
    with MAP.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} headings from {len(sources())} sources -> {MAP}")


if __name__ == "__main__":
    main()
