"""Optional MLflow tracing of every turn: a root span per turn with its stages as child spans, and the Claude calls
captured by MLflow's Anthropic autologging. Off unless COPILOT_MLFLOW_URI is set and mlflow
is installed (`uv sync --extra tune`); the deployed app keeps its own per-turn traces in the audit log instead.

Spans only ever receive masked text: card numbers are masked by the gateway before any span records the message.

The stack server is MLflow 3.1. The `tune` extra's client (3.16) first posts traces to the v3 route
(`/api/3.0/mlflow/traces`), which 3.1 does not implement. A 404 falls back to the v2 trace API and the
spans do land, but `StartTraceV3` is retried for `MLFLOW_ASYNC_TRACE_LOGGING_RETRY_TIMEOUT` (default
500s) and each HTTP call waits `MLFLOW_HTTP_REQUEST_TIMEOUT` (default 120s). The client's atexit flush
joins that work with no deadline, and a synchronous export (async logging off, or a flush in progress)
runs inside `span()`. A turn therefore waits on the server. While this URI is set we force async export
and, unless the operator already chose them, bound those two waits and the retry count.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

log = logging.getLogger(__name__)
_mlflow: Any = None

# Short enough that a dead v3 route cannot stall a turn or process exit for minutes,
# long enough for the local 3.1 server (a three-turn flush measured about 2s).
_HTTP_TIMEOUT_S = "8"
_RETRY_TIMEOUT_S = "8"
_MAX_RETRIES = "2"
_FLUSH_TIMEOUT_S = 20.0


class _Null(AbstractContextManager):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_inputs(self, _): ...

    def set_outputs(self, _): ...

    def set_attributes(self, _): ...


class _Guarded(AbstractContextManager):
    """Open and close a real span, and swallow exporter failures so a turn still finishes."""

    def __init__(self, opener: Callable[[], AbstractContextManager]):
        self._opener = opener
        self._inner: AbstractContextManager | None = None

    def __enter__(self):
        try:
            self._inner = self._opener()
            entered = self._inner.__enter__()
        except Exception as e:  # tracing must never break the copilot
            log.warning("span not opened: %s", e)
            self._inner = None
            return _Null()
        return entered if entered is not None else _Null()

    def __exit__(self, exc_type, exc, tb):
        inner = self._inner
        if inner is None:
            return False
        try:
            return inner.__exit__(exc_type, exc, tb)
        except Exception as e:  # tracing must never break the copilot
            log.warning("span not closed: %s", e)
            return False


def _bound_export_waits() -> None:
    """Keep trace export off the turn thread and cap how long a worker may wait on the server."""
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"] = "true"
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", _HTTP_TIMEOUT_S)
    os.environ.setdefault("MLFLOW_ASYNC_TRACE_LOGGING_RETRY_TIMEOUT", _RETRY_TIMEOUT_S)
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", _MAX_RETRIES)


def setup() -> bool:
    """Point tracing at the MLflow server; returns whether tracing is on."""
    global _mlflow
    uri = os.environ.get(
        "COPILOT_MLFLOW_URI"
    )  # explicit opt-in only: a generic MLFLOW_TRACKING_URI is not enough
    if not uri:
        return False
    try:
        import mlflow
    except ImportError:
        log.warning("COPILOT_MLFLOW_URI is set but mlflow is not installed; tracing stays off")
        return False
    _bound_export_waits()
    try:
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(os.environ.get("COPILOT_MLFLOW_EXPERIMENT", "copilot-traces"))
    except Exception as e:  # tracing must never break the copilot
        log.warning("MLflow at %s unavailable, tracing stays off: %s", uri, e)
        return False
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
    return _Guarded(lambda: _mlflow.start_span(name=name, span_type=span_type))


def flush(timeout_s: float = _FLUSH_TIMEOUT_S) -> None:
    """Ask the async exporter to finish, and return anyway once `timeout_s` elapses."""
    if _mlflow is None:
        return
    fn = getattr(_mlflow, "flush_trace_async_logging", None)
    if fn is None:
        return
    done = threading.Event()

    def _run() -> None:
        try:
            fn()
        except Exception as e:  # tracing must never break the copilot
            log.warning("trace flush failed: %s", e)
        finally:
            done.set()

    threading.Thread(target=_run, name="copilot-trace-flush", daemon=True).start()
    if not done.wait(timeout_s):
        log.warning("trace flush exceeded %ss; not waiting any longer", timeout_s)


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
