"""Command line entry points used locally and by Airflow tasks.

uv run python -m latam_platform.cli landing-manifest
uv run python -m latam_platform.cli bronze-build [--table transactions] [--force]
uv run python -m latam_platform.cli quarantine-backup
uv run python -m latam_platform.cli bronze-raw-build [--table transactions] [--source main] [--force]
uv run python -m latam_platform.cli bronze-raw-verify [--table transactions] [--source main]
uv run python -m latam_platform.cli archive-typed-bronze   # once: retire typed bronze to a read-only archive
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from latam_platform import config
from latam_platform.lakehouse import bronze, bronze_raw, landing


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


def _tables(args) -> list:
    return [config.TABLES[t] for t in args.table] if args.table else list(config.TABLES.values())


def cmd_bronze_raw_build(args) -> list[dict]:
    """Lossless bronze of record: prove every file byte-exact, then write it as text (bronze_raw.py)."""
    run_id = datetime.now(UTC).strftime("bronze-raw-%Y%m%dT%H%M%SZ")
    return [
        bronze_raw.build_table_raw(
            t, run_id, source=args.source, force=args.force, workers=args.workers
        )
        for t in _tables(args)
    ]


def cmd_bronze_raw_verify(args) -> list[dict]:
    """Rebuild every file from the stored lossless bronze and compare with the landing manifest."""
    out = [bronze_raw.verify_table_raw(t, source=args.source) for t in _tables(args)]
    failed = [
        r["table"] for r in out if not r["verified"] and r.get("problems") != ["no proof manifest"]
    ]
    if failed:
        raise SystemExit("BRONZE RAW VERIFICATION FAILED: " + json.dumps(out, indent=1))
    return out


def cmd_governance_check(_args) -> dict:
    from latam_platform import governance

    rep = governance.check_manifest()
    out = {"checked_models": rep.checked_models, "errors": rep.errors, "warnings": rep.warnings}
    if not rep.ok:
        raise SystemExit("GOVERNANCE CHECK FAILED: " + json.dumps(out, indent=1))
    return out


def cmd_archive_typed_bronze(_args) -> dict:
    """Retire typed bronze: move it into a read-only archive and record the move in the audit ledger."""
    from latam_platform import ops

    out = bronze.archive_typed()
    if out["moved"]:
        ops.ledger("bronze.typed_archived", out["archive"], out, actor="data-platform")
    if not out["read_only"]:
        raise SystemExit("ARCHIVE NOT READ-ONLY: " + out["read_only_hint"])
    return out


def cmd_lake_init(_args) -> list[str]:
    dirs = [
        config.QUARANTINE,
        config.BRONZE_RAW,
        config.HOLDOUT_RAW,
        config.QUARANTINE_RAW,
        config.MANIFESTS,
        config.LAKE / "graph",
        config.LAKE / "features",
        config.LAKE / "knowledge",
        config.LAKE / "stream_landing",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    from latam_platform import dq_corrections

    dq_corrections.ensure_log()  # the correction log readers need, even before any correction
    return [str(d) for d in dirs] + [str(dq_corrections.root())]


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
    for name, fn in (
        ("bronze-raw-build", cmd_bronze_raw_build),
        ("bronze-raw-verify", cmd_bronze_raw_verify),
    ):
        r = sub.add_parser(name)
        r.add_argument("--table", action="append")
        r.add_argument("--source", default="main", choices=list(config.SOURCES))
        if name == "bronze-raw-build":
            r.add_argument(
                "--force", action="store_true", help="dev only: allow rewriting changed partitions"
            )
            r.add_argument("--workers", type=int, default=4)
        r.set_defaults(fn=fn)
    sub.add_parser("governance-check").set_defaults(fn=cmd_governance_check)
    sub.add_parser("lake-init").set_defaults(fn=cmd_lake_init)
    sub.add_parser("archive-typed-bronze").set_defaults(fn=cmd_archive_typed_bronze)
    args = p.parse_args()
    print(json.dumps(args.fn(args), indent=1, default=str))


if __name__ == "__main__":
    main()
