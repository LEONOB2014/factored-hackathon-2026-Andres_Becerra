"""Graph learning pipelines (MLflow-tracked): temporal GNN and federated GNN across country silos.

* ml_tgn: TGN self-supervised future-link prediction on the customer->merchant stream (embeddings for
  downstream fraud/AML once confirmed labels exist). Bounded slice for laptop runtimes.
* ml_federated_gnn: GraphSAGE per country silo with FedAvg and DP-FedAvg, compared with local-only and
  centralised training. Silos never exchange rows, only model updates (residency by design).
Both log params, metrics and lineage tags; results are recorded even when they show no signal, because a
negative result is evidence for the data-acquisition plan (counterparties, device data, confirmed labels).
"""

from __future__ import annotations

import pendulum
from airflow.sdk import dag, task

from latam_dags.common import AUDIT_CALLBACKS, DEFAULT_ARGS, GRAPH, PLATFORM_PY


def _dag(dag_id: str, doc: str):
    return dag(
        dag_id=dag_id,
        schedule=[GRAPH],
        start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
        catchup=False,
        max_active_runs=1,
        default_args={**DEFAULT_ARGS, "owner": "ml-engineering"},
        tags=["ml", "graph", "mlflow"],
        doc_md=doc,
        **AUDIT_CALLBACKS,
    )


@_dag("ml_tgn", __doc__)
def ml_tgn():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def train(lineage_run_id: str, train_events: int = 80000, test_events: int = 20000) -> dict:
        import os

        import duckdb
        import mlflow
        import pandas as pd

        from latam_platform import config, ops
        from latam_platform.ml import tgn

        ev = duckdb.sql(
            f"select * from '{config.LAKE}/graph/tgn_tx_events.parquet' "
            "where split in ('train', 'test') order by ts"
        ).df()
        ev = pd.concat(
            [ev[ev.split == "train"].tail(train_events), ev[ev.split == "test"].head(test_events)]
        )
        mlflow.set_tracking_uri(os.environ.get("LATAM_MLFLOW_URI", "http://mlflow:5000"))
        mlflow.set_experiment("tgn_link_prediction")
        with mlflow.start_run(run_name=f"tgn-{lineage_run_id}") as run:
            res = tgn.train_tgn(ev, epochs=2)
            mlflow.log_params(
                {
                    "train_events": res["train_events"],
                    "test_events": res["test_events"],
                    "epochs": 2,
                    "memory_dim": 64,
                    "task": "future_link_prediction",
                }
            )
            mlflow.log_metrics(
                {"test_link_ap": res["test_link_ap"], "test_link_auc": res["test_link_auc"]}
            )
            for i, l in enumerate(res["train_loss"]):
                mlflow.log_metric("train_loss", l, step=i)
            mlflow.set_tags(
                {
                    "airflow_run_id": lineage_run_id,
                    "input": "lake/graph/tgn_tx_events.parquet",
                    "labels_used": "none (self-supervised)",
                }
            )
        ops.ledger(
            "ml.tgn_trained",
            "tgn_link_prediction",
            {**res, "mlflow_run_id": run.info.run_id},
            lineage_run_id,
        )
        return res

    train(lineage_run_id="{{ run_id }}")


@_dag("ml_federated_gnn", __doc__)
def ml_federated_gnn():
    @task.external_python(python=PLATFORM_PY, expect_airflow=False)
    def federate(lineage_run_id: str) -> dict:
        import os

        import duckdb
        import mlflow

        from latam_platform import config, ops
        from latam_platform.ml import federated_gnn

        nodes = duckdb.sql(f"select * from '{config.LAKE}/graph/fgl_silo_nodes.parquet'").df()
        edges = duckdb.sql(f"select * from '{config.LAKE}/graph/fgl_silo_edges.parquet'").df()
        mlflow.set_tracking_uri(os.environ.get("LATAM_MLFLOW_URI", "http://mlflow:5000"))
        mlflow.set_experiment("federated_gnn_complaint90d")
        results = {}
        for name, kw in {
            "fedavg": {},
            "dp_fedavg": {"dp_clip": 1.0, "dp_noise_multiplier": 0.5},
        }.items():
            with mlflow.start_run(run_name=f"{name}-{lineage_run_id}"):
                res = federated_gnn.run_federation(nodes, edges, rounds=10, local_epochs=2, **kw)
                mlflow.log_params(
                    {
                        "variant": name,
                        "rounds": res["rounds"],
                        "local_epochs": res["local_epochs"],
                        "dp_clip": kw.get("dp_clip"),
                        "dp_noise_multiplier": kw.get("dp_noise_multiplier", 0),
                    }
                )
                for setting in ("auc_local_only", "auc_federated", "auc_centralised"):
                    for silo, v in res[setting].items():
                        mlflow.log_metric(f"{setting}_{silo}", v)
                mlflow.set_tags(
                    {"airflow_run_id": lineage_run_id, "residency": "rows never leave their silo"}
                )
                results[name] = res
        ops.ledger(
            "ml.federated_gnn_trained", "federated_gnn_complaint90d", results, lineage_run_id
        )
        return results

    federate(lineage_run_id="{{ run_id }}")


ml_tgn()
ml_federated_gnn()
