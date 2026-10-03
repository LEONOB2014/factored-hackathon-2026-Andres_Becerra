"""Landing ingest: prove what was received.

Fingerprints every landing file (SHA-256 + line counts), compares with the previous manifest (a modified or
deleted landing file is an integrity incident that fails the run), writes the manifest to the object-locked
bucket and records it in the audit ledger. Optionally pulls new objects from the source S3 bucket first.
"""

from __future__ import annotations

import pendulum
from airflow.sdk import Param, dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, LANDING, PLATFORM_PY


@dag(
    dag_id="landing_ingest",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "data-platform"},
    tags=["ingestion", "landing", "audit"],
    params={
        "download_from_s3": Param(
            False, type="boolean", description="Run eda/scripts/download_s3.py first"
        )
    },
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def landing_ingest():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def download(flag: str) -> str:
        import subprocess

        if flag.lower() != "true":
            return "skipped (landing already populated)"
        subprocess.run(["python", "/opt/latam/eda/scripts/download_s3.py"], check=True)
        return "downloaded"

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, outlets=[LANDING])
    def fingerprint_landing(lineage_run_id: str) -> dict:
        from latam_platform import ops
        from latam_platform.lakehouse import landing

        prev = landing.latest_manifest()
        cur = landing.build_manifest(run_id=f"landing-{lineage_run_id}")
        diff = (
            landing.diff_manifests(prev, cur)
            if prev
            else {"new": [f["path"] for f in cur["files"]], "deleted": [], "modified": []}
        )
        uri = ops.worm_put_json("bronze-worm", f"manifests/landing/{cur['run_id']}.json", cur)
        summary = {
            "n_files": cur["n_files"],
            "bytes": cur["bytes"],
            "root_digest": cur["root_digest"],
            "new": len(diff["new"]),
            "deleted": diff["deleted"],
            "modified": diff["modified"],
            "worm_uri": uri,
        }
        incident = bool(diff["deleted"] or diff["modified"])
        ops.ledger(
            "landing.integrity_incident" if incident else "landing.manifest_recorded",
            "data/raw",
            summary,
            lineage_run_id,
        )
        if incident:
            raise RuntimeError(f"landing zone was modified: {summary}")
        landing.write_manifest(cur)
        return summary

    download(flag="{{ params.download_from_s3 }}") >> fingerprint_landing(
        lineage_run_id="{{ run_id }}"
    )


landing_ingest()
