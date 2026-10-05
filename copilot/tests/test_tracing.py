"""Tracing stays off without COPILOT_MLFLOW_URI, and a failing exporter cannot break a turn."""

from __future__ import annotations

import os
import sys
import time
import types

import pytest

from copilot import tracing

_ENV_KEYS = (
    "COPILOT_MLFLOW_URI",
    "COPILOT_MLFLOW_EXPERIMENT",
    "MLFLOW_ENABLE_ASYNC_TRACE_LOGGING",
    "MLFLOW_HTTP_REQUEST_TIMEOUT",
    "MLFLOW_ASYNC_TRACE_LOGGING_RETRY_TIMEOUT",
    "MLFLOW_HTTP_REQUEST_MAX_RETRIES",
)


@pytest.fixture
def isolated(monkeypatch):
    """Drop tracing's opt-in and the export bounds, and put the process env back afterwards.

    ``setup`` writes ``os.environ`` directly. ``monkeypatch.delenv`` does not record an undo when
    the key was already absent, so a bound set during the test would leak into later tests.
    """
    monkeypatch.setattr(tracing, "_mlflow", None)
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    yield monkeypatch
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _install_fake(monkeypatch, *, start_span, flush=None, fail_experiment=False):
    calls = {"tracking": None, "experiment": None, "autolog": 0}
    fake = types.ModuleType("mlflow")

    def set_tracking_uri(uri):
        calls["tracking"] = uri

    def set_experiment(name):
        if fail_experiment:
            raise RuntimeError("server down")
        calls["experiment"] = name

    anthropic = types.ModuleType("mlflow.anthropic")

    def autolog():
        calls["autolog"] += 1

    anthropic.autolog = autolog
    fake.anthropic = anthropic
    fake.set_tracking_uri = set_tracking_uri
    fake.set_experiment = set_experiment
    fake.start_span = start_span
    fake.update_current_trace = lambda **_k: None
    if flush is not None:
        fake.flush_trace_async_logging = flush
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    monkeypatch.setitem(sys.modules, "mlflow.anthropic", anthropic)
    return fake, calls


class _Span:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def set_inputs(self, _): ...

    def set_outputs(self, _): ...

    def set_attributes(self, _): ...


def test_unset_uri_does_not_touch_mlflow_or_timeouts(isolated):
    _fake, calls = _install_fake(isolated, start_span=lambda **_k: _Span())
    assert tracing.setup() is False
    assert tracing.enabled() is False
    assert calls["tracking"] is None
    assert "MLFLOW_HTTP_REQUEST_TIMEOUT" not in os.environ
    assert "MLFLOW_ENABLE_ASYNC_TRACE_LOGGING" not in os.environ
    with tracing.span("copilot.turn", "AGENT") as root:
        root.set_inputs({"text": "hola"})
        root.set_outputs({"outcome": "answered"})
        root.set_attributes({"intent": "balance"})
    tracing.tag_trace("s", "c", outcome="answered")
    tracing.flush(timeout_s=1)
    assert calls["autolog"] == 0


def test_setup_bounds_export_and_keeps_operator_timeouts(isolated):
    isolated.setenv("MLFLOW_HTTP_REQUEST_TIMEOUT", "30")
    _install_fake(isolated, start_span=lambda **_k: _Span())
    isolated.setenv("COPILOT_MLFLOW_URI", "http://127.0.0.1:5001")
    isolated.setenv("COPILOT_MLFLOW_EXPERIMENT", "copilot-traces")
    assert tracing.setup() is True
    assert os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"] == "true"
    assert os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] == "30"
    assert os.environ["MLFLOW_ASYNC_TRACE_LOGGING_RETRY_TIMEOUT"] == tracing._RETRY_TIMEOUT_S
    assert os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] == tracing._MAX_RETRIES


def test_span_failures_do_not_escape(isolated):
    def start_span(name, span_type="CHAIN"):
        if name == "open-fails":
            raise RuntimeError("exporter down")

        class _ExitBoom:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                raise RuntimeError("close failed")

            def set_outputs(self, _): ...

        return _ExitBoom()

    _install_fake(isolated, start_span=start_span)
    isolated.setenv("COPILOT_MLFLOW_URI", "http://127.0.0.1:5001")
    assert tracing.setup() is True
    with tracing.span("open-fails") as root:
        root.set_inputs({})
        root.set_outputs({})
        root.set_attributes({})
    with tracing.span("copilot.turn", "AGENT") as root:
        root.set_outputs({"outcome": "answered"})


def test_flush_returns_when_the_exporter_stalls(isolated):
    started = time.monotonic()

    def stall():
        time.sleep(2)

    _install_fake(isolated, start_span=lambda **_k: _Span(), flush=stall)
    isolated.setenv("COPILOT_MLFLOW_URI", "http://127.0.0.1:5001")
    assert tracing.setup() is True
    tracing.flush(timeout_s=0.2)
    assert time.monotonic() - started < 1.0


def test_experiment_failure_leaves_tracing_off(isolated):
    _install_fake(isolated, start_span=lambda **_k: _Span(), fail_experiment=True)
    isolated.setenv("COPILOT_MLFLOW_URI", "http://127.0.0.1:5001")
    assert tracing.setup() is False
    assert tracing.enabled() is False
    with tracing.span("copilot.turn") as root:
        root.set_outputs({})
