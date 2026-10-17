"""Verdict wiring: the gate's benchmark, bootstrap, and readiness row."""

from __future__ import annotations

import numpy as np
import pandas as pd
from kumo_probe.loaders import Prepared
from kumo_probe.scenarios import by_key
from kumo_probe.score import benchmark_scores, score_predictions


def _classification() -> Prepared:
    spec = by_key("branch_teller")
    y_true = np.array([0, 1] * 200, dtype=float)
    frame = pd.DataFrame({"outside": y_true.astype(int)})
    return Prepared(
        spec=spec,
        train=frame,
        test=frame,
        context=frame.iloc[:20].reset_index(drop=True),
        y_train=y_true,
        y_test=y_true,
    )


def _regression() -> Prepared:
    spec = by_key("agent_handle")
    n = 200
    agents = np.array(["A", "B"] * (n // 2))
    train = pd.DataFrame({"agent_id": agents, "aht": np.full(n, 50.0)})
    test_y = np.where(agents == "A", 0.0, 100.0)
    test = pd.DataFrame({"agent_id": agents, "aht": test_y})
    return Prepared(
        spec=spec,
        train=train,
        test=test,
        context=train.iloc[:10].reset_index(drop=True),
        y_train=train.aht.to_numpy(),
        y_test=test.aht.to_numpy(),
    )


def test_base_rate_benchmark_is_the_train_rate_with_fixed_noise() -> None:
    prepared = _classification()
    first = benchmark_scores(prepared)
    second = benchmark_scores(prepared)
    assert np.allclose(first, second)
    assert abs(float(first.mean()) - 0.5) < 1e-6
    assert float(np.std(first)) > 0


def test_perfect_classifier_is_green_and_the_benchmark_is_not() -> None:
    prepared = _classification()
    perfect = score_predictions(prepared, {"kumo tabular": prepared.y_test}, rounds=200)[0]
    assert perfect["scenario"] == "04 branch"
    assert perfect["model"] == "teller transaction outside opening hours"
    assert perfect["benchmark"] == "base rate"
    assert perfect["metric"] == "AUC"
    assert perfect["opinion"] == "kumo tabular"
    assert perfect["verdict"] == "green"
    assert perfect["root_cause"] == ""
    assert perfect["n_train"] == len(prepared.train)
    assert perfect["n_context"] == len(prepared.context)
    assert perfect["delta"] >= 0.02
    assert perfect["delta_lo"] > 0
    # Same rule as hour_models._row: widen the test only when the effect is undetectable.
    if perfect["mde"] > perfect["material"]:
        needed = int(np.ceil(perfect["n_test"] * (perfect["mde"] / perfect["material"]) ** 2))
    else:
        needed = perfect["n_test"]
    assert perfect["n_test_needed"] == needed

    tied = score_predictions(prepared, {"kumo tabular": benchmark_scores(prepared)}, rounds=200)[0]
    assert tied["verdict"] != "green"
    assert tied["delta"] == 0
    assert tied["mde"] <= tied["material"]
    assert tied["n_test_needed"] == tied["n_test"]


def test_perfect_handle_time_beats_the_agent_mean() -> None:
    prepared = _regression()
    rows = score_predictions(
        prepared,
        {"kumo tabular": prepared.y_test, "kumo relational": prepared.y_test},
        rounds=200,
    )
    assert [row["opinion"] for row in rows] == ["kumo tabular", "kumo relational"]
    for row in rows:
        assert row["scenario"] == "05 agent and queue"
        assert row["model"] == "handle time per agent-hour"
        assert row["benchmark"] == "agent's own mean"
        assert row["metric"] == "MAE (s)"
        assert row["verdict"] == "green"
        assert row["value"] == 0
        assert row["delta"] >= 0.02
        assert row["n_train"] == 200
        assert row["n_context"] == 10
