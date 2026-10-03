"""Command line entry points used locally and by Airflow tasks.

uv run python -m latam_platform.cli landing-manifest
uv run python -m latam_platform.cli bronze-build [--table transactions] [--force]
uv run python -m latam_platform.cli quarantine-backup
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from latam_platform import config
from latam_platform.lakehouse import bronze, landing


def cmd_landing_manifest(_args) -> dict:
    prev = landing.latest_manifest()
    cur = landing.build_manifest()
    diff = (
        landing.diff_manifests(prev, cur)
        if prev
        else {"new": [f["path"] for f in cur["files"]], "deleted": [], "modified": []}
    )
    landing.write_manifest(cur)
    summary = {
        "run_id": cur["run_id"],
        "n_files": cur["n_files"],
        "bytes": cur["bytes"],
        "root_digest": cur["root_digest"],
        "new": len(diff["new"]),
        "deleted": diff["deleted"],
        "modified": diff["modified"],
    }
    if diff["deleted"] or diff["modified"]:
        raise SystemExit(f"LANDING INTEGRITY INCIDENT: {json.dumps(summary)}")
    return summary


def cmd_bronze_build(args) -> list[dict]:
    manifest = landing.latest_manifest() or {"files": []}
    lines = {f["path"]: f["lines"] for f in manifest["files"]}
    run_id = datetime.now(UTC).strftime("bronze-%Y%m%dT%H%M%SZ")
    tables = [config.TABLES[t] for t in args.table] if args.table else list(config.TABLES.values())
    return [bronze.build_table(t, run_id, lines or None, force=args.force) for t in tables]


def cmd_quarantine_backup(_args) -> list[dict]:
    return bronze.build_quarantine_backup(datetime.now(UTC).strftime("quarantine-%Y%m%dT%H%M%SZ"))


def cmd_governance_check(_args) -> dict:
    from latam_platform import governance

    rep = governance.check_manifest()
    out = {"checked_models": rep.checked_models, "errors": rep.errors, "warnings": rep.warnings}
    if not rep.ok:
        raise SystemExit("GOVERNANCE CHECK FAILED: " + json.dumps(out, indent=1))
    return out


def cmd_lake_init(_args) -> list[str]:
    dirs = [
        config.BRONZE,
        config.HOLDOUT,
        config.QUARANTINE,
        config.MANIFESTS,
        config.LAKE / "graph",
        config.LAKE / "features",
        config.LAKE / "knowledge",
        config.LAKE / "stream_landing",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return [str(d) for d in dirs]


def main() -> None:
    p = argparse.ArgumentParser(prog="latam_platform")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("landing-manifest").set_defaults(fn=cmd_landing_manifest)
    b = sub.add_parser("bronze-build")
    b.add_argument("--table", action="append")
    b.add_argument(
        "--force", action="store_true", help="dev only: allow rewriting changed partitions"
    )
    b.set_defaults(fn=cmd_bronze_build)
    sub.add_parser("quarantine-backup").set_defaults(fn=cmd_quarantine_backup)
    sub.add_parser("governance-check").set_defaults(fn=cmd_governance_check)
    sub.add_parser("lake-init").set_defaults(fn=cmd_lake_init)
    args = p.parse_args()
    print(json.dumps(args.fn(args), indent=1, default=str))


if __name__ == "__main__":
    main()
