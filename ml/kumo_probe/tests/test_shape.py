"""The out-of-time split, the context cap, and the two Kumo table shapes."""

from __future__ import annotations

import numpy as np
import pandas as pd
from kumo_probe.eda_path import ensure_eda_src
from kumo_probe.loaders import (
    capped_features,
    load_frame,
    out_of_time_split,
    prepare,
    sample_context,
)
from kumo_probe.scenarios import SCENARIOS, by_key


def _branch_frame(n: int = 45) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    ts = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "transaction_id": [f"t{i}" for i in range(n)],
            "transaction_ts_utc": ts,
            "amount_usd": rng.normal(size=n),
            "transaction_type": np.where(rng.random(n) > 0.5, "purchase", "withdrawal"),
            "transaction_category": "retail",
            "is_cash": rng.integers(0, 2, n),
            "customer_id": [f"c{i % 7}" for i in range(n)],
            "branch_id": [f"b{i % 3}" for i in range(n)],
            "segment": np.where(rng.random(n) > 0.5, "mass", "affluent"),
            "age_years": rng.integers(20, 70, n),
            "branch_type": np.where(rng.random(n) > 0.5, "mall", "street"),
            "open_fraction": np.where(rng.random(n) > 0.8, 0.0, 1.0),
        }
    )


def _agent_frame(n: int = 30) -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "agent_id": [f"a{i % 4}" for i in range(n)],
            "hour_start": ts,
            "contacts": np.full(n, 2),
            "handle_seconds": np.full(n, 20.0),
            "in_shift": np.ones(n),
            "contact_hour_of_day": ts.hour,
            "experience_level": "mid",
            "agent_type": "voice",
            "specialty": "cards",
        }
    )


def test_split_uses_the_gate_quantile_and_keeps_order() -> None:
    frame = _branch_frame(9).sample(frac=1, random_state=1)
    time_col = "transaction_ts_utc"
    train, test = out_of_time_split(frame, time_col)
    cut = frame[time_col].quantile(2 / 3)
    mask = frame[time_col] <= cut
    pd.testing.assert_series_equal(
        train[time_col], frame.loc[mask, time_col].reset_index(drop=True), check_names=False
    )
    assert train[time_col].max() <= cut
    assert test[time_col].min() > cut
    assert len(train) + len(test) == len(frame)


def test_context_sample_is_reproducible_and_capped() -> None:
    frame = pd.DataFrame({"x": np.arange(100)})
    first = sample_context(frame, 15, seed=2026)
    second = sample_context(frame, 15, seed=2026)
    other = sample_context(frame, 15, seed=1)
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 15
    assert first.x.is_monotonic_increasing
    assert not first.x.equals(other.x)
    assert len(sample_context(frame.iloc[:10], 15)) == 10


def test_column_cap_keeps_numeric_columns_first() -> None:
    spec = by_key("branch_teller")
    assert capped_features(spec, max_columns=2) == ["amount_usd", "age_years"]
    wide_numeric = tuple(f"n{i:03d}" for i in range(101))
    capped = type(spec)(**{**spec.__dict__, "numeric": wide_numeric, "categorical": ("only_cat",)})
    kept = capped_features(capped)
    assert kept == list(wide_numeric[:100])
    assert "only_cat" not in kept


def test_prepare_caps_context_and_flat_columns_without_the_label_source() -> None:
    prepared = prepare(by_key("branch_teller"), _branch_frame(), max_context=15, max_columns=2)
    assert len(prepared.context) == 15
    assert len(prepared.y_test) == len(prepared.test)
    assert len(prepared.y_train) == len(prepared.train)
    assert len(prepared.train) > len(prepared.context)
    assert list(prepared.flat_query.columns) == ["amount_usd", "age_years"]
    assert list(prepared.flat_context.columns) == ["amount_usd", "age_years", "outside"]
    for frame in (
        prepared.flat_context,
        prepared.flat_query,
        prepared.task_context,
        prepared.task_query,
    ):
        assert "open_fraction" not in frame.columns
    assert prepared.flat_stypes["amount_usd"] == "numerical"
    assert prepared.flat_stypes["outside"] == "categorical"
    assert prepared.task_stypes["customer_id"] == "id"
    assert prepared.task_stypes["branch_id"] == "id"


def test_branch_links_and_agent_dimension() -> None:
    branch = prepare(by_key("branch_teller"), _branch_frame())
    assert branch.relationships == []
    assert branch.task_links == [
        {"task_columns": "customer_id", "table": "customers", "table_columns": "customer_id"},
        {"task_columns": "branch_id", "table": "branches", "table_columns": "branch_id"},
    ]
    customers = branch.related_context["customers"]["customer_id"]
    assert set(customers) <= set(branch.context.customer_id)
    assert "segment" in branch.related_context["customers"].columns
    assert "branch_type" in branch.related_query["branches"].columns
    assert "age_years" not in branch.task_query.columns

    agent = prepare(by_key("agent_handle"), _agent_frame())
    assert agent.task_links == [
        {"task_columns": "agent_id", "table": "agents", "table_columns": "agent_id"}
    ]
    assert list(agent.task_query.columns) == [
        "agent_id",
        "contacts",
        "in_shift",
        "contact_hour_of_day",
    ]
    assert "experience_level" not in agent.task_query.columns
    assert list(agent.related_context["agents"].columns) == [
        "agent_id",
        "experience_level",
        "agent_type",
        "specialty",
    ]
    assert agent.flat_stypes["aht"] == "numerical"
    assert (agent.train.aht == 10).all()


def test_load_frame_runs_the_scenario_sql_then_derives() -> None:
    seen: dict[str, str] = {}

    class _Star:
        def q(self, sql: str) -> pd.DataFrame:
            seen["sql"] = sql
            return _branch_frame(12)

    derived = load_frame(_Star(), by_key("branch_teller"))
    assert seen["sql"] == by_key("branch_teller").sql
    assert "outside" in derived.columns
    assert "open_fraction" not in derived.columns


def test_scenarios_match_the_gate_text() -> None:
    ensure_eda_src()
    from latam_eda.hour_models import REQUIREMENTS

    assert [spec.key for spec in SCENARIOS] == ["branch_teller", "agent_handle"]
    branch, agent = SCENARIOS
    assert branch.scenario == "04 branch"
    assert branch.model == "teller transaction outside opening hours"
    assert branch.material == 0.02
    assert branch.cause == "data defect"
    assert branch.benchmark == "base rate"
    assert "customer_id" in branch.sql
    assert "branch_id" in branch.sql
    assert "order by t.transaction_ts_utc, t.transaction_id" in branch.sql
    assert agent.scenario == "05 agent and queue"
    assert agent.model == "handle time per agent-hour"
    assert agent.material == 0.02
    assert agent.cause == "missing field"
    assert agent.benchmark == "agent's own mean"
    assert "order by f.hour_start, f.agent_id" in agent.sql
    for spec in SCENARIOS:
        assert REQUIREMENTS[(spec.scenario, spec.model)] == spec.requirement
