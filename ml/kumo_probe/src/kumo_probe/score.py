"""Score Kumo predictions with the same readiness gate the hour models use.

The benchmark is the gate's benchmark on the full out-of-time train, not on the
60_000-row context sample. Classification uses a noisy base rate (seed 2026).
Regression uses each test row's group mean from train, filled with the train
mean, then the relative MAE reduction the agent gate reports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from sklearn.metrics import mean_absolute_error, roc_auc_score

from kumo_probe.constants import BOOTSTRAP_ROUNDS, SEED

if TYPE_CHECKING:
    from kumo_probe.loaders import Prepared


def _gate():
    from kumo_probe.eda_path import ensure_eda_src

    ensure_eda_src()
    from latam_eda.granularity import paired_boot, readiness_row, readiness_verdict

    return paired_boot, readiness_row, readiness_verdict


def benchmark_scores(prepared: Prepared) -> np.ndarray:
    """The gate's benchmark vector, aligned to `prepared.y_test`."""
    spec = prepared.spec
    n_test = len(prepared.y_test)
    if spec.task == "classification":
        rate = float(np.mean(prepared.y_train))
        rng = np.random.default_rng(SEED)
        noise = rng.normal(0, 1e-9, n_test)
        return np.full(n_test, rate) + noise
    if spec.benchmark_key is None:
        raise ValueError(f"{spec.key} has no group column for its regression benchmark")
    key = spec.benchmark_key
    means = prepared.train.groupby(key)[spec.target].mean()
    fill = float(prepared.train[spec.target].mean())
    mapped = prepared.test[key].map(means).fillna(fill)
    return mapped.to_numpy(dtype=float)


def _n_test_needed(n_test: int, mde: float, material: float) -> int:
    """Same formula as `hour_models._row`."""
    if mde > material:
        return int(np.ceil(n_test * (mde / material) ** 2))
    return int(n_test)


def _neg_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return -float(mean_absolute_error(y_true, y_pred))


def score_predictions(
    prepared: Prepared,
    predictions: dict[str, np.ndarray],
    *,
    rounds: int = BOOTSTRAP_ROUNDS,
) -> list[dict]:
    """One readiness row per opinion. `predictions` maps an opinion name to test scores."""
    paired_boot, readiness_row, readiness_verdict = _gate()
    spec = prepared.spec
    y_true = np.asarray(prepared.y_test)
    bench = benchmark_scores(prepared)
    rows: list[dict] = []
    for opinion, pred in predictions.items():
        scores = np.asarray(pred, dtype=float)
        if scores.shape != y_true.shape:
            raise ValueError(
                f"{opinion} predictions have shape {scores.shape}, test has {y_true.shape}"
            )
        if spec.task == "classification":
            delta, boot = paired_boot(roc_auc_score, y_true, scores, bench, B=rounds, seed=SEED)
            value = float(roc_auc_score(y_true, scores))
            bench_value = float(roc_auc_score(y_true, bench))
        else:
            delta, boot = paired_boot(_neg_mae, y_true, scores, bench, B=rounds, seed=SEED)
            bench_value = float(mean_absolute_error(y_true, bench))
            if bench_value == 0:
                raise ValueError("benchmark MAE is zero; the relative reduction is undefined")
            value = float(mean_absolute_error(y_true, scores))
            delta = delta / bench_value
            boot = boot / bench_value
        gate = readiness_verdict(boot, delta, spec.material, spec.cause)
        row = readiness_row(
            spec.scenario,
            spec.model,
            spec.metric,
            value,
            spec.benchmark,
            bench_value,
            gate,
            spec.requirement,
            len(prepared.train),
            len(prepared.test),
        )
        row["n_test_needed"] = _n_test_needed(len(prepared.test), gate["mde"], spec.material)
        row["opinion"] = opinion
        row["n_context"] = int(len(prepared.context))
        rows.append(row)
    return rows
