"""Rebuild the gate's out-of-time split and shape it for Kumo.

The cut is `time_col.quantile(2/3)`: rows at or before the cut are train, rows
after it are test. Nothing is re-sorted, so a frame that arrived in the SQL
order stays in that order. The 60_000-row cap applies only to the in-context
train sample. The test split stays the gate's test rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from kumo_probe.constants import MAX_COLUMNS, MAX_CONTEXT_ROWS, QUANTILE, SEED

if TYPE_CHECKING:
    from kumo_probe.scenarios import Related, Scenario

Link = dict[str, str]


@dataclass
class Prepared:
    spec: Scenario
    train: pd.DataFrame
    test: pd.DataFrame
    context: pd.DataFrame
    y_train: np.ndarray
    y_test: np.ndarray
    flat_context: pd.DataFrame = field(default_factory=pd.DataFrame)
    flat_query: pd.DataFrame = field(default_factory=pd.DataFrame)
    flat_stypes: dict[str, str] = field(default_factory=dict)
    task_context: pd.DataFrame = field(default_factory=pd.DataFrame)
    task_query: pd.DataFrame = field(default_factory=pd.DataFrame)
    task_stypes: dict[str, str] = field(default_factory=dict)
    related_context: dict[str, pd.DataFrame] = field(default_factory=dict)
    related_query: dict[str, pd.DataFrame] = field(default_factory=dict)
    related_stypes: dict[str, dict[str, str]] = field(default_factory=dict)
    relationships: list[Link] = field(default_factory=list)
    task_links: list[Link] = field(default_factory=list)


def out_of_time_split(
    frame: pd.DataFrame, time_col: str, quantile: float = QUANTILE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train is `time <= quantile`, test is `time > quantile`. Order is kept."""
    cut = frame[time_col].quantile(quantile)
    train = frame.loc[frame[time_col] <= cut].reset_index(drop=True)
    test = frame.loc[frame[time_col] > cut].reset_index(drop=True)
    if train.empty or test.empty:
        raise ValueError(f"out-of-time split on {time_col} produced an empty side")
    return train, test


def sample_context(
    frame: pd.DataFrame, max_rows: int = MAX_CONTEXT_ROWS, seed: int = SEED
) -> pd.DataFrame:
    """A reproducible without-replacement sample. Positions are sorted so time order holds."""
    if max_rows < 1:
        raise ValueError("max_rows must be positive")
    if len(frame) <= max_rows:
        return frame.reset_index(drop=True)
    rng = np.random.default_rng(seed)
    picked = np.sort(rng.choice(len(frame), size=max_rows, replace=False))
    return frame.iloc[picked].reset_index(drop=True)


def capped_features(spec: Scenario, max_columns: int = MAX_COLUMNS) -> list[str]:
    """Numeric columns first, then categoricals, stopped at `max_columns`."""
    if max_columns < 1:
        raise ValueError("max_columns must be positive")
    return [*spec.numeric, *spec.categorical][:max_columns]


def _kind(spec: Scenario, column: str) -> str:
    numeric = set(spec.numeric) | set(spec.task_numeric)
    for related in spec.related:
        numeric.update(related.numeric)
    if column in numeric:
        return "numerical"
    return "categorical"


def _values(frame: pd.DataFrame, column: str, kind: str) -> pd.Series:
    if kind == "numerical":
        return pd.to_numeric(frame[column], errors="coerce")
    return frame[column].astype(str)


def _target_stype(spec: Scenario) -> str:
    if spec.task == "classification":
        return "categorical"
    return "numerical"


def _target_values(frame: pd.DataFrame, spec: Scenario) -> pd.Series:
    if spec.task == "classification":
        return frame[spec.target].astype(int)
    return pd.to_numeric(frame[spec.target], errors="coerce")


def _flat(
    frame: pd.DataFrame, columns: list[str], spec: Scenario, *, with_target: bool
) -> pd.DataFrame:
    data = {col: _values(frame, col, _kind(spec, col)) for col in columns}
    if with_target:
        data[spec.target] = _target_values(frame, spec)
    return pd.DataFrame(data)


def _flat_stypes(spec: Scenario, columns: list[str]) -> dict[str, str]:
    stypes = {col: _kind(spec, col) for col in columns}
    stypes[spec.target] = _target_stype(spec)
    return stypes


def _task_columns(spec: Scenario) -> list[str]:
    return [*spec.task_ids, *spec.task_numeric, *spec.task_categorical]


def _task_frame(frame: pd.DataFrame, spec: Scenario, *, with_target: bool) -> pd.DataFrame:
    columns = _task_columns(spec)
    data: dict[str, pd.Series] = {}
    for col in columns:
        if col in spec.task_ids:
            data[col] = frame[col]
        else:
            data[col] = _values(frame, col, _kind(spec, col))
    if with_target:
        data[spec.target] = _target_values(frame, spec)
    return pd.DataFrame(data)


def _task_stypes(spec: Scenario) -> dict[str, str]:
    stypes = dict.fromkeys(spec.task_ids, "id")
    for col in spec.task_numeric:
        stypes[col] = "numerical"
    for col in spec.task_categorical:
        stypes[col] = "categorical"
    stypes[spec.target] = _target_stype(spec)
    return stypes


def _related_frame(source: pd.DataFrame, related: Related) -> pd.DataFrame:
    data = {related.key: source[related.key]}
    for col in related.numeric:
        data[col] = _values(source, col, "numerical")
    for col in related.categorical:
        data[col] = _values(source, col, "categorical")
    # One row per key. The source frame is time-ordered, so the first row is the earliest.
    deduped = pd.DataFrame(data).drop_duplicates(subset=[related.key], keep="first")
    return deduped.reset_index(drop=True)


def _related_stypes(related: Related) -> dict[str, str]:
    stypes = {related.key: "id"}
    for col in related.numeric:
        stypes[col] = "numerical"
    for col in related.categorical:
        stypes[col] = "categorical"
    return stypes


def _task_links(spec: Scenario) -> list[Link]:
    # Plural keys, as in the KumoRelational example on the sdm docs.
    return [
        {
            "task_columns": related.key,
            "table": related.name,
            "table_columns": related.key,
        }
        for related in spec.related
    ]


def prepare(
    spec: Scenario,
    frame: pd.DataFrame,
    *,
    max_context: int = MAX_CONTEXT_ROWS,
    max_columns: int = MAX_COLUMNS,
) -> Prepared:
    """Derive the label, split out of time, cap the flat table, and build related tables."""
    derived = spec.derive(frame)
    train, test = out_of_time_split(derived, spec.time_col)
    context = sample_context(train, max_context)
    features = capped_features(spec, max_columns)
    y_train = _target_values(train, spec).to_numpy()
    y_test = _target_values(test, spec).to_numpy()
    return Prepared(
        spec=spec,
        train=train,
        test=test,
        context=context,
        y_train=np.asarray(y_train),
        y_test=np.asarray(y_test),
        flat_context=_flat(context, features, spec, with_target=True),
        flat_query=_flat(test, features, spec, with_target=False),
        flat_stypes=_flat_stypes(spec, features),
        task_context=_task_frame(context, spec, with_target=True),
        task_query=_task_frame(test, spec, with_target=False),
        task_stypes=_task_stypes(spec),
        related_context={rel.name: _related_frame(context, rel) for rel in spec.related},
        related_query={rel.name: _related_frame(test, rel) for rel in spec.related},
        related_stypes={rel.name: _related_stypes(rel) for rel in spec.related},
        relationships=[],
        task_links=_task_links(spec),
    )


def load_frame(star: object, spec: Scenario) -> pd.DataFrame:
    """Run the scenario SQL on a `granularity.Star` and derive the target."""
    raw = star.q(spec.sql)  # type: ignore[attr-defined]
    return spec.derive(raw)
