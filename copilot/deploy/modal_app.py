"""Deploy the copilot to Modal: one ASGI app serving the UI, the API and the Grain Atlas at /atlas.

Data stays out of git and out of the image: the demo snapshot and the knowledge-base index go to a Modal Volume.

    # once: authenticate, upload the data, and (optionally) store the Claude key as a Modal secret
    modal setup
    modal volume create copilot-data
    modal volume put copilot-data ../data/copilot/snapshot.duckdb /snapshot.duckdb
    modal volume put copilot-data ../data/copilot/kb_index /kb_index
    modal secret create copilot-anthropic ANTHROPIC_API_KEY=...      # typed by the maintainer, never committed
    # deploy (from copilot/)
    COPILOT_MODAL_SECRET=copilot-anthropic modal deploy deploy/modal_app.py

One warm container (min = max = 1): conversations, sessions and the operational store live in that process, and a
warm container avoids cold starts while the jury tries it. Without the secret the copilot runs its deterministic path.
"""

from __future__ import annotations

import os
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
REPO = PROJECT.parent
ATLAS = REPO / "eda" / "reports" / "dashboards" / "grain_atlas" / "grain_atlas.html"
READINESS = REPO / "eda" / "reports" / "tables" / "granularity_hour_readiness.csv"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"


def _download_embedder() -> None:
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(EMBEDDING_MODEL)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.8.0", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install(
        "anthropic>=0.69",
        "duckdb>=1.5.6",
        "fastapi>=0.115",
        "numpy>=2.0",
        "pyyaml>=6.0",
        "scikit-learn>=1.9.1",
        "sentence-transformers>=3.0",
        "uvicorn>=0.32",
    )
    .run_function(_download_embedder)
    .env(
        {
            "PYTHONPATH": "/app/copilot/src",
            "COPILOT_SNAPSHOT": "/data/snapshot.duckdb",
            "COPILOT_KB_INDEX": "/data/kb_index",
            "COPILOT_STORE": "/var/copilot/operations.sqlite",  # per container: demo actions reset on redeploy
            "COPILOT_AUDIT": "/var/copilot/audit.jsonl",
            "COPILOT_ATLAS": "/app/atlas.html",
            "COPILOT_KNOWLEDGE": "/app/knowledge",
            "COPILOT_READINESS": "/app/readiness.csv",
            "COPILOT_EVAL_DIR": "/app/eval_reports",
            "COPILOT_CORS_ORIGINS": os.environ.get(
                "COPILOT_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
            ),
        }
    )
    .add_local_dir(PROJECT / "src", "/app/copilot/src", ignore=["**/__pycache__"])
    .add_local_dir(PROJECT / "corpus", "/app/copilot/corpus")
    .add_local_dir(REPO / "knowledge", "/app/knowledge")
    .add_local_file(ATLAS, "/app/atlas.html")
    .add_local_file(READINESS, "/app/readiness.csv")
    .add_local_dir(PROJECT / "eval" / "reports", "/app/eval_reports")
)

app = modal.App("beta-aid-copilot", image=image)
volume = modal.Volume.from_name("copilot-data")
secret_name = os.environ.get("COPILOT_MODAL_SECRET")


@app.function(
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name(secret_name)] if secret_name else [],
    min_containers=1,
    max_containers=1,
    timeout=600,
)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def web():
    from copilot.app import app as fastapi_app

    return fastapi_app
