"""Generate Mermaid lineage diagrams of the dbt project from target/manifest.json (never hand-maintained).

    cd platform/dbt && uv run python scripts/mermaid_lineage.py   ->  docs/platform/generated/dbt_lineage.md

Two views: a zone-level graph (sources -> silver -> gold -> features/graph/knowledge/privacy/serving/audit with
model counts) and the model-level graph of each consumer-facing zone.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "platform/dbt/target/manifest.json"
OUT = ROOT / "docs/platform/generated/dbt_lineage.md"


def zone(node: dict) -> str:
    if node["resource_type"] == "source":
        return f"source:{node['source_name']}"
    if node["resource_type"] == "seed":
        return "reference"
    if node["resource_type"] == "snapshot":
        return "snapshots"
    return node["config"].get("schema") or node["fqn"][1]


def main() -> None:
    m = json.loads(MANIFEST.read_text())
    nodes = {**m["nodes"], **m["sources"]}
    models = {
        k: v
        for k, v in nodes.items()
        if v["resource_type"] in ("model", "seed", "snapshot", "source")
    }
    edges = Counter()
    sizes = Counter(zone(v) for v in models.values())
    for k, v in models.items():
        for dep in v.get("depends_on", {}).get("nodes", []):
            if dep in models and zone(models[dep]) != zone(v):
                edges[(zone(models[dep]), zone(v))] += 1
    lines = [
        "# dbt lineage (generated)",
        "",
        f"_Generated from `platform/dbt/target/manifest.json` "
        f"({sum(1 for v in models.values() if v['resource_type'] == 'model')} models)._",
        "",
        "## Zone-level lineage",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    ids = {z: z.replace(":", "_") for z in sizes}
    for z, n in sorted(sizes.items()):
        lines.append(f'  {ids[z]}["{z}<br/>{n} nodes"]')
    for (a, b), n in sorted(edges.items()):
        lines.append(f"  {ids[a]} -->|{n}| {ids[b]}")
    lines += ["```", ""]
    by_zone = defaultdict(list)
    for k, v in models.items():
        by_zone[zone(v)].append(k)
    for z in ("serving", "features", "graph", "knowledge", "privacy"):
        lines += [f"## Model-level lineage into `{z}`", "", "```mermaid", "flowchart LR"]
        for k in sorted(by_zone.get(z, [])):
            for dep in models[k].get("depends_on", {}).get("nodes", []):
                if dep in models:
                    lines.append(f"  {models[dep]['name']} --> {models[k]['name']}")
        lines += ["```", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
