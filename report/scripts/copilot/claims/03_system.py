"""Chapter 3 · The system under test: the policy's intents and autonomy levels, its vetoes, the model timeout and
the governed knowledge base.

    REPORT_DOC=copilot uv run python scripts/copilot/claims/03_system.py
"""

from __future__ import annotations

import re
from collections import Counter

import pandas as pd
import yaml

from report_lib.build import Chapter
from report_lib.copilot_data import CONFIG, POLICY, out
from report_lib.paths import REPO
from report_lib.texgen import render_table

KNOWLEDGE = REPO / "knowledge"


def front_matter(path) -> dict:
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    return yaml.safe_load(m.group(1)) if m else {}


def main() -> None:
    ch = Chapter(3, "sys")
    policy = yaml.safe_load(POLICY.read_text())
    intents = policy["intents"]
    ch.count("intents", len(intents), POLICY)
    levels = Counter(v["autonomy"] for v in intents.values())
    for level in ("A0", "A2", "A3"):
        ch.count(f"intents-{level.lower()}", levels[level], POLICY)
    ch.count("intents-step-up", sum(bool(v.get("step_up")) for v in intents.values()), POLICY)
    ch.count("vetoes", len(policy["vetoes"]), POLICY)
    timeout = float(re.search(r'COPILOT_LLM_TIMEOUT", "([0-9.]+)"', CONFIG.read_text()).group(1))
    ch.constant("model-timeout", timeout, CONFIG, unit="s")

    # the governed knowledge base: one row per document version, from its front matter
    rows = []
    for p in sorted(KNOWLEDGE.glob("*_v*.md")):
        m = front_matter(p)
        rows.append({"document": p.stem.rsplit("_v", 1)[0], "version": f"v{m.get('version')}",
                     "status": m.get("status"), "classification": m.get("classification"),
                     "effective_from": str(m.get("effective_from")), "effective_to": str(m.get("effective_to") or "open")})  # fmt: skip
    kb = out("kb_documents.csv")
    pd.DataFrame(rows).to_csv(kb, index=False)
    ch.count("kb-documents", len(rows), kb)
    status = Counter(r["status"] for r in rows)
    for s in ("approved", "draft", "superseded", "retired"):
        ch.count(f"kb-{s}", status[s], kb)
    ch.count("kb-public", sum(r["classification"] == "public" for r in rows), kb)
    render_table(kb, "kb-documents", "The governed knowledge base: every document version with its status, "
                 "classification and effective window, read from its front matter.")  # fmt: skip
    ch.write()


if __name__ == "__main__":
    main()
