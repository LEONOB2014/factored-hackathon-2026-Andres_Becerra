"""Optional MLflow tracing of every turn: a root span per turn with its stages as child spans, and the Claude calls
captured by MLflow's Anthropic autologging. Off unless COPILOT_MLFLOW_URI (or MLFLOW_TRACKING_URI) is set and mlflow
is installed (`uv sync --extra tune`); the deployed app keeps its own per-turn traces in the audit log instead.

Spans only ever receive masked text: card numbers are masked by the gateway before any span records the message.
"""

from __future__ import annotations

import logging
import os
from contextlib import AbstractContextManager
from typing import Any

log = logging.getLogger(__name__)
_mlflow: Any = None


class _Null(AbstractContextManager):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_inputs(self, _): ...

    def set_outputs(self, _): ...

    def set_attributes(self, _): ...


def setup() -> bool:
    """Point tracing at the MLflow server; returns whether tracing is on."""
    global _mlflow
    uri = os.environ.get("COPILOT_MLFLOW_URI") or os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        return False
    try:
        import mlflow
    except ImportError:
        log.warning("COPILOT_MLFLOW_URI is set but mlflow is not installed; tracing stays off")
        return False
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(os.environ.get("COPILOT_MLFLOW_EXPERIMENT", "copilot-traces"))
    try:
        mlflow.anthropic.autolog()
    except Exception as e:  # tracing must never break the copilot
        log.warning("anthropic autolog unavailable: %s", e)
    _mlflow = mlflow
    return True


def enabled() -> bool:
    return _mlflow is not None


def span(name: str, span_type: str = "CHAIN"):
    if _mlflow is None:
        return _Null()
    return _mlflow.start_span(name=name, span_type=span_type)


def tag_trace(session_id: str | None, customer_id: str | None, **tags) -> None:
    if _mlflow is None:
        return
    try:
        meta = {k: str(v) for k, v in tags.items() if v is not None}
        if session_id:
            meta["mlflow.trace.session"] = session_id
        if customer_id:
            meta["mlflow.trace.user"] = customer_id
        _mlflow.update_current_trace(metadata=meta)
    except Exception as e:  # tracing must never break the copilot
        log.warning("trace metadata not recorded: %s", e)
