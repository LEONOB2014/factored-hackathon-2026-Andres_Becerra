"""Knowledge base sync (GraphRAG): knowledge/*.md + approved warehouse documents -> pgvector + Neo4j.

Runs hourly and whenever the lakehouse is rebuilt. Only approved documents inside their effective window are
indexed; superseded, retired, expired and draft versions are pruned from both indexes (history stays in the
append-only registry); documents with personal data are rejected; the active set must reconcile across the
registry, pgvector and Neo4j or the run fails. Each prune fires the `kb_document_expired` regulatory trigger.
Embeddings are computed locally (multilingual E5): no document text leaves the environment.
"""

from __future__ import annotations

from datetime import UTC

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, KNOWLEDGE, PLATFORM_PY


@dag(
    dag_id="kb_sync",
    schedule="@hourly",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "ai-engineering"},
    tags=["knowledge", "graphrag", "pgvector", "neo4j", "governance"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def kb_sync():
    @task.external_python(
        python=PLATFORM_PY, expect_airflow=False, outlets=[KNOWLEDGE], pool="neo4j_writer"
    )
    def sync(lineage_run_id: str) -> dict:
        import json
        from datetime import datetime

        from latam_platform import config, kb_pipeline, ops

        manifest = json.loads(
            (config.REPO_ROOT / "platform/dbt/target-airflow/manifest.json").read_text()
        )
        models = {n["name"] for n in manifest["nodes"].values() if n["resource_type"] == "model"}
        docs = [
            kb_pipeline.parse(p) for p in sorted((config.REPO_ROOT / "knowledge").glob("*_v*.md"))
        ]
        embed = kb_pipeline.local_embedder()
        neo = ops.neo4j_driver()
        kb_pipeline.ensure_neo4j_schema(neo)
        with ops.pg("knowledge") as pg:
            rep = kb_pipeline.sync(
                pg,
                neo,
                docs,
                lineage_run_id,
                embed,
                kb_pipeline.POLICY["embedding_model"]["name"],
                models,
            )
        neo.close()
        out = {
            k: (
                v
                if not isinstance(v, list)
                else [list(x) if isinstance(x, tuple) else x for x in v]
            )
            for k, v in rep.items()
        }
        ops.ledger("kb.sync_completed", "knowledge.kb", out, lineage_run_id)
        if rep["pruned"]:
            with ops.audit() as a:
                for doc_id, version in rep["pruned"]:
                    a.execute(
                        "INSERT INTO compliance.trigger_event (trigger_id, fired_at, subject_ref, evidence, action, status)"
                        " VALUES ('kb_document_expired', %s, %s, %s, 'prune_from_active_index', 'actioned')",
                        (
                            datetime.now(UTC),
                            f"{doc_id}@{version}",
                            json.dumps({"run": lineage_run_id}),
                        ),
                    )
        if not rep["reconciled"]:
            raise RuntimeError(f"knowledge indexes do not reconcile: {out}")
        return out

    sync(lineage_run_id="{{ run_id }}")


kb_sync()
