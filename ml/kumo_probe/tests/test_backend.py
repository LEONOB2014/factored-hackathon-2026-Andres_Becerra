"""CPU stand-in for sdm. The real package is imported only inside the predict functions."""

from __future__ import annotations

import sys
import types

import numpy as np
import pandas as pd
from kumo_probe.loaders import prepare
from kumo_probe.scenarios import by_key
from kumo_probe.sdm_backend import predict_relational, predict_tabular, scores_from_output


class _Out:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def to_pandas(self) -> pd.DataFrame:
        return self.frame


def _nrows(tensor: dict) -> int:
    return len(tensor["df"])


class _Tabular:
    def __init__(self, task=None, size="large", pretrained=True, device=None) -> None:
        calls.append(("KumoTabular", task, size, pretrained, device))
        self.task = task

    def fit(self, *args, **kwargs) -> None:
        calls.append(("fit-tabular", tuple(sorted(kwargs))))

    def predict(self, x) -> _Out:
        calls.append(("predict-tabular",))
        n = _nrows(x)
        if self.task == "regression":
            return _Out(pd.DataFrame({"q500": np.full(n, 1.5)}))
        return _Out(pd.DataFrame({"0": np.zeros(n), "1": np.ones(n)}))

    def clear(self) -> None:
        calls.append(("clear-tabular",))

    def train(self) -> None:
        calls.append(("train",))


class _Relational:
    def __init__(self, task=None, pretrained=True, device=None) -> None:
        calls.append(("KumoRelational", task, pretrained, device))
        self.task = task

    def fit(self, x, y, related, num_hops: int = 1) -> None:
        calls.append(
            (
                "fit-relational",
                num_hops,
                list(related.relationships),
                list(related.task_links),
            )
        )

    def predict(self, x, related) -> _Out:
        calls.append(("predict-relational", list(related.task_links)))
        n = _nrows(x)
        if self.task == "regression":
            return _Out(pd.DataFrame({"q500": np.full(n, 2.5)}))
        return _Out(pd.DataFrame({"0": np.zeros(n), "1": np.full(n, 0.75)}))

    def clear(self) -> None:
        calls.append(("clear-relational",))


class _TableTensor:
    @staticmethod
    def from_pandas(df, stypes=None, device=None) -> dict:
        calls.append(("from_pandas", list(df.columns), dict(stypes or {}), device))
        return {"df": df, "stypes": stypes, "device": device}


class _Related:
    def __init__(self, tables, relationships, task_links) -> None:
        self.tables = tables
        self.relationships = relationships
        self.task_links = task_links
        calls.append(("RelatedTables", sorted(tables), list(relationships), list(task_links)))


calls: list = []


def _install(monkeypatch) -> None:
    calls.clear()
    sdm = types.ModuleType("sdm")
    models = types.ModuleType("sdm.models")
    sdm.TableTensor = _TableTensor
    sdm.RelatedTables = _Related
    models.KumoTabular = _Tabular
    models.KumoRelational = _Relational
    sdm.models = models
    monkeypatch.setitem(sys.modules, "sdm", sdm)
    monkeypatch.setitem(sys.modules, "sdm.models", models)
    monkeypatch.delenv("KUMO_SIZE", raising=False)


def _branch_frame(n: int = 45) -> pd.DataFrame:
    rng = np.random.default_rng(2)
    ts = pd.date_range("2024-06-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "transaction_id": [f"t{i}" for i in range(n)],
            "transaction_ts_utc": ts,
            "amount_usd": rng.normal(size=n),
            "transaction_type": "purchase",
            "transaction_category": "retail",
            "is_cash": np.zeros(n),
            "customer_id": [f"c{i % 5}" for i in range(n)],
            "branch_id": [f"b{i % 2}" for i in range(n)],
            "segment": "mass",
            "age_years": np.full(n, 40),
            "branch_type": "mall",
            "open_fraction": np.where(np.arange(n) % 5 == 0, 0.0, 1.0),
        }
    )


def _agent_frame(n: int = 30) -> pd.DataFrame:
    ts = pd.date_range("2024-06-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "agent_id": [f"a{i % 3}" for i in range(n)],
            "hour_start": ts,
            "contacts": np.full(n, 2.0),
            "handle_seconds": np.full(n, 16.0),
            "in_shift": np.ones(n),
            "contact_hour_of_day": ts.hour,
            "experience_level": "junior",
            "agent_type": "voice",
            "specialty": "cards",
        }
    )


def test_scores_from_output_reads_the_documented_columns() -> None:
    binary = scores_from_output(pd.DataFrame({"0": [0.2], "1": [0.8]}), "classification")
    assert binary.tolist() == [0.8]
    median = scores_from_output(pd.DataFrame({"q001": [0.1], "q500": [4.0]}), "regression")
    assert median.tolist() == [4.0]
    fallback = scores_from_output(pd.DataFrame({"no": [0.1], "yes": [0.9]}), "classification")
    assert fallback.tolist() == [0.9]


def test_tabular_and_relational_call_the_documented_api(monkeypatch) -> None:
    _install(monkeypatch)
    prepared = prepare(by_key("branch_teller"), _branch_frame())
    tabular = predict_tabular(prepared, device="cuda", batch_size=8)
    relational = predict_relational(prepared, device="cuda", batch_size=8)
    assert len(tabular) == len(prepared.y_test)
    assert len(relational) == len(prepared.y_test)
    assert set(tabular.tolist()) == {1.0}
    assert set(relational.tolist()) == {0.75}

    names = [name for name, *_rest in calls]
    assert "train" not in names
    assert names.count("predict-tabular") >= 2
    assert ("KumoTabular", "classification", "large", True, "cuda") in calls
    assert ("fit-tabular", ("x", "y")) in calls
    assert ("KumoRelational", "classification", True, "cuda") in calls
    fit = next(item for item in calls if item[0] == "fit-relational")
    assert fit[1] == 1
    assert fit[2] == []
    assert {"customer_id", "branch_id"} <= {link["task_columns"] for link in fit[3]}
    devices = {item[3] for item in calls if item[0] == "from_pandas"}
    assert devices == {"cuda"}
    columns = [item[1] for item in calls if item[0] == "from_pandas"]
    assert all("open_fraction" not in cols for cols in columns)
    assert "clear-tabular" in names
    assert "clear-relational" in names


def test_regression_output_uses_q500(monkeypatch) -> None:
    _install(monkeypatch)
    prepared = prepare(by_key("agent_handle"), _agent_frame())
    scores = predict_relational(prepared, device="cuda", batch_size=4)
    assert len(scores) == len(prepared.y_test)
    assert set(scores.tolist()) == {2.5}
    y_stypes = [item[2] for item in calls if item[0] == "from_pandas" and item[1] == ["aht"]]
    assert y_stypes
    assert all(stypes["aht"] == "numerical" for stypes in y_stypes)
