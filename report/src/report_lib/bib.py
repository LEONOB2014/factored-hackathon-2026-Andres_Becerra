"""Bibliography checks: every cited key exists, has a DOI, ISBN or URL, and was verified by hand.

conf/bib_verification.csv records, for each key, the identifier that was resolved, the date and the title it
resolved to. A person checks that the source is primary; this module checks that the record exists.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from report_lib.paths import CONF, TEX

ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n@|\Z)", re.S)
CITE = re.compile(r"\\(?:cite|citet|citep|textcite|parencite|autocite|footcite|fullcite|nocite|citeauthor|"
                  r"citeyear)\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")  # fmt: skip


def entries(bib_text: str) -> dict[str, str]:
    return {
        key: body
        for kind, key, body in ENTRY.findall(bib_text)
        if kind.lower() not in {"comment", "string"}
    }


def cited_keys(tex_texts: list[str]) -> set[str]:
    keys = set()
    for t in tex_texts:
        t = re.sub(r"(?<!\\)%.*", "", t)
        for group in CITE.findall(t):
            keys.update(k.strip() for k in group.split(",") if k.strip())
    return keys


def problems(bib_text: str, verification: list[dict[str, str]], tex_texts: list[str]) -> list[str]:
    out = []
    bib = entries(bib_text)
    verified = {r["key"]: r for r in verification}
    for key, body in sorted(bib.items()):
        if not re.search(r"\b(doi|isbn|url)\s*=", body, re.I):
            out.append(f"{key}: needs a doi, isbn or url")
        row = verified.get(key)
        if row is None:
            out.append(f"{key}: missing from bib_verification.csv")
        elif not all(
            row.get(f, "").strip() for f in ("identifier", "date_resolved", "resolved_title")
        ):
            out.append(f"{key}: verification row is incomplete")
    for key in sorted(cited_keys(tex_texts) - set(bib)):
        out.append(f"{key}: cited but not in refs.bib")
    return out


def check_repository(tex: Path = TEX, conf: Path = CONF) -> list[str]:
    with (conf / "bib_verification.csv").open() as f:
        verification = list(csv.DictReader(f))
    texts = [p.read_text() for p in sorted(tex.rglob("*.tex"))]
    return problems((tex / "refs.bib").read_text(), verification, texts)
