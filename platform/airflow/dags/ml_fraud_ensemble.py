"""Fraud ensemble training -> MLflow registry -> human approval -> @champion alias.

1. train rules + IsolationForest/COPOD/robust Mahalanobis on the train split (point-in-time features, no
   fraud_score), evaluate out of time on valid/test;
2. detector CI: recall per injected anomaly type at the review budget must clear the floors;
3. log params, metrics, the model card and full data lineage (dbt manifest hash, bronze manifest digest,
   training query + row count) to MLflow; register a new version of `fraud_ensemble`;
4. model-risk approval (Airflow human-in-the-loop) -> only then the version becomes `@champion`, which is
   what the stream scorer loads. Rejection leaves the current champion untouched. All steps hit the ledger.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.hitl import ApprovalOperator
from airflow.sdk import dag, task

from latam_dags.common import (
    AUDIT_CALLBACKS,
    DEFAULT_ARGS,
    DUCKDB_POOL,
    FRAUD_MODEL,
    LAKEHOUSE,
    PLATFORM_PY,
)


@dag(
    dag_id="ml_fraud_ensemble",
    schedule=[LAKEHOUSE],
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "owner": "ml-engineering"},
    tags=["ml", "fraud", "mlflow", "model-risk"],
    doc_md=__doc__,
    **AUDIT_CALLBACKS,
)
def ml_fraud_ensemble():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False, pool=DUCKDB_POOL)
    def train_and_register(lineage_run_id: str) -> dict:
        import hashlib
        import os
        import tempfile

        import joblib
        import mlflow
        from sklearn.metrics import average_precision_score, roc_auc_score

        from latam_platform import config, ops
        from latam_platform.ml import fraud_ensemble as fe

        con = ops.lakehouse(read_only=True)
        cols = ", ".join(fe.FEATURES)
        q_train = f"select {cols} from features.ml_fraud_train using sample 200000 (reservoir, 7)"
        train = con.sql(q_train).df()
        sets = {
            s: con.sql(
                f"select {cols}, label_is_fraud from features.ml_fraud_{s} using sample 200000 (reservoir, 7)"
            ).df()
            for s in ("valid", "test")
        }
        model = fe.FraudEnsemble(seed=7).fit(train)
        ci = fe.detector_ci(model, sets["test"].drop(columns="label_is_fraud"))
        metrics = {}
        for s, df in sets.items():
            sc = model.score(df)
            metrics[f"{s}_label_auc"] = float(roc_auc_score(df.label_is_fraud, sc.risk_score))
            metrics[f"{s}_label_ap"] = float(
                average_precision_score(df.label_is_fraud, sc.risk_score)
            )
            metrics[f"{s}_base_rate"] = float(df.label_is_fraud.mean())
            metrics[f"{s}_step_up_rate"] = float((sc.decision == "STEP_UP").mean())
            metrics[f"{s}_decline_rate"] = float((sc.decision == "DECLINE").mean())
        metrics |= {f"ci_recall_{k}": v for k, v in ci["recall_at_budget"].items()}

        manifest = (config.REPO_ROOT / "platform/dbt/target-airflow/manifest.json").read_bytes()
        bronze = b"".join(
            p.read_bytes() for p in sorted((config.MANIFESTS / "bronze").glob("*.json"))
        )
        lineage = {
            "dbt_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "bronze_manifests_sha256": hashlib.sha256(bronze).hexdigest(),
            "training_query": q_train,
            "training_rows": len(train),
            "airflow_run_id": lineage_run_id,
            "label_caveat": "is_fraud is derived from legacy fraud_score; labels carry no behavioural signal",
        }
        card = {
            "name": "fraud_ensemble",
            "purpose": "real-time transaction risk scoring (step-up/decline)",
            "type": "rules + unsupervised ensemble (IsolationForest, COPOD, robust Mahalanobis)",
            "features": fe.FEATURES,
            "excluded": ["fraud_score (label leakage)", "protected attributes"],
            "tier": "1 (affects customers in real time)",
            "owner": "ml-engineering",
            "validator": "model-risk",
            "limitations": [
                "not trained on confirmed fraud",
                "thresholds set by review capacity, not by labels",
            ],
            "detector_ci": ci,
            "metrics": metrics,
            "lineage": lineage,
        }

        mlflow.set_tracking_uri(os.environ.get("LATAM_MLFLOW_URI", "http://mlflow:5000"))
        mlflow.set_experiment("fraud_ensemble")
        with mlflow.start_run(run_name=f"train-{lineage_run_id}") as run:
            mlflow.set_tags({**{k: str(v) for k, v in lineage.items()}, "model_tier": "1"})
            mlflow.log_params(
                {
                    "features": len(fe.FEATURES),
                    "detectors": "iforest,copod,mcd",
                    "seed": 7,
                    "review_budget": ci["budget"],
                }
            )
            mlflow.log_metrics(metrics)
            mlflow.log_dict(card, "model_card.json")
            with tempfile.TemporaryDirectory() as d:
                path = f"{d}/ensemble.joblib"
                joblib.dump(model, path)
                info = mlflow.pyfunc.log_model(
                    name="model",
                    python_model=fe.FraudEnsemblePyfunc(),
                    artifacts={"ensemble": path},
                    input_example=train.head(5),
                    code_paths=[str(config.REPO_ROOT / "platform/libs/latam_platform")],
                    registered_model_name="fraud_ensemble",
                )
        version = info.registered_model_version
        ops.ledger(
            "ml.model_registered",
            f"fraud_ensemble/{version}",
            {"mlflow_run_id": run.info.run_id, "ci_passed": ci["passed"], "metrics": metrics},
            lineage_run_id,
        )
        if not ci["passed"]:
            raise RuntimeError(
                f"detector CI failed, version {version} must not be promoted: {ci['failed']}"
            )
        return {"version": str(version), "run_id": run.info.run_id, "ci": ci["recall_at_budget"]}

    approval = ApprovalOperator(
        task_id="model_risk_approval",
        subject="Promote fraud_ensemble to @champion?",
        body="Review the model card and metrics of the registered version in MLflow (experiment fraud_ensemble). "
        "Approving makes it the version the real-time scorer loads.",
        fail_on_reject=True,
        execution_timeout=pendulum.duration(days=3),
    )

    @task.external_python(python=PLATFORM_PY, expect_airflow=False, outlets=[FRAUD_MODEL])
    def promote(registered: dict, lineage_run_id: str) -> str:
        import os

        import mlflow

        from latam_platform import ops

        mlflow.set_tracking_uri(os.environ.get("LATAM_MLFLOW_URI", "http://mlflow:5000"))
        client = mlflow.MlflowClient()
        client.set_registered_model_alias("fraud_ensemble", "champion", registered["version"])
        ops.ledger(
            "ml.model_promoted",
            f"fraud_ensemble/{registered['version']}",
            {"alias": "champion", "approved_via": "airflow-hitl"},
            lineage_run_id,
        )
        return registered["version"]

    reg = train_and_register(lineage_run_id="{{ run_id }}")
    reg >> approval >> promote(reg, lineage_run_id="{{ run_id }}")


ml_fraud_ensemble()
