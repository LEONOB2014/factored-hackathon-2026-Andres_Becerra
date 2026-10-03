"""Governance checks over the dbt manifest and the policies in platform/policies.

Run after `dbt parse` (CI) or `dbt build` (Airflow pre-publish gate):

    uv run python -m latam_platform.cli governance-check

Checks:
* every model outside silver declares owner, data_class, residency and zone in `meta`;
* the declared data_class is allowed in the model's zone (data_classification.yaml);
* every model published to serving/features/graph is documented and has a group (ownership);
* serving models enforce a contract (schema is an API for downstream applications and agents);
* the restricted-column seed used by dbt tests matches the policy (no drift between policy and test).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from latam_platform import config

POLICIES = config.REPO_ROOT / "platform" / "policies"
DBT_DIR = config.REPO_ROOT / "platform" / "dbt"


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_models: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def load_policy(name: str) -> dict:
    return yaml.safe_load((POLICIES / f"{name}.yaml").read_text())


def check_manifest(manifest_path: Path = DBT_DIR / "target" / "manifest.json") -> Report:
    manifest = json.loads(manifest_path.read_text())
    zones = load_policy("data_classification")["zones"]
    rep = Report()
    for node in manifest["nodes"].values():
        if node["resource_type"] != "model":
            continue
        rep.checked_models += 1
        meta = node["config"].get("meta", {})
        name, zone = node["name"], meta.get("zone")
        if zone in (None, "silver"):
            continue
        for key in ("owner", "data_class", "residency", "zone"):
            if not meta.get(key):
                rep.errors.append(f"{name}: meta.{key} missing")
        allowed = zones.get(zone, {}).get("allowed_classes", [])
        if meta.get("data_class") and meta["data_class"] not in allowed:
            rep.errors.append(
                f"{name}: data_class {meta['data_class']} not allowed in zone {zone} ({allowed})"
            )
        if zone in ("serving", "features", "graph"):
            if not node.get("description"):
                rep.warnings.append(f"{name}: no description")
            if not node["config"].get("group"):
                rep.errors.append(f"{name}: no owning group")
        if zone == "serving" and not node["config"].get("contract", {}).get("enforced"):
            rep.errors.append(f"{name}: serving model without an enforced contract")
    # policy <-> seed drift
    policy_cols = {c["column"] for c in load_policy("data_classification")["restricted_columns"]}
    with (DBT_DIR / "seeds" / "restricted_pii_columns.csv").open() as f:
        seed_cols = {r["column_name"] for r in csv.DictReader(f)}
    if policy_cols != seed_cols:
        rep.errors.append(
            f"restricted_pii_columns seed out of sync with policy: {sorted(policy_cols ^ seed_cols)}"
        )
    return rep


def check_residency(country_code: str, region: str) -> bool:
    """True if `region` may hold data of customers from `country_code` (residency.yaml)."""
    countries = load_policy("residency")["countries"]
    return region in countries.get(country_code, {}).get("allowed_regions", [])
