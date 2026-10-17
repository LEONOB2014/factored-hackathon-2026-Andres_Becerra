"""In-context Kumo calls. Imported only when a GPU run asks for predictions.

API checked against https://nvidia.github.io/structured-data-models/ on 2026-10-05:

* `KumoTabular(task, size, pretrained=True, device)` then `fit(x=, y=)` and `predict(x)`.
  Regression outputs quantiles `q001`–`q999`; the point score is `q500`.
  Classification outputs class probabilities (the default recipe ends in Softmax).
* `KumoRelational(task, pretrained=True, device)` then
  `fit(x_context, y_context, related_context, num_hops=1)` and
  `predict(x_query, related_query)`.
* `RelatedTables(tables, relationships, task_links)` with the plural link keys from the
  KumoRelational example (`task_columns`, `table_columns`, `left_columns`).
* `TableTensor.from_pandas(df, stypes=, device=)`.

No `train()` call. `KUMO_SIZE` selects small, medium, or large (default large).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from kumo_probe.loaders import Prepared

_DEFAULT_BATCH = 8192


def scores_from_output(out: object, task: str) -> np.ndarray:
    """Point scores from a model output: positive-class probability, or the median quantile."""
    frame = out.to_pandas() if hasattr(out, "to_pandas") else pd.DataFrame(out)  # type: ignore[arg-type]
    if task == "regression":
        if "q500" in frame.columns:
            return frame["q500"].to_numpy(dtype=float)
        return frame.mean(axis=1).to_numpy(dtype=float)
    for name in ("1", "True", "true"):
        if name in frame.columns:
            return frame[name].to_numpy(dtype=float)
    return frame.iloc[:, -1].to_numpy(dtype=float)


def _batches(frame: pd.DataFrame, batch_size: int):
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    for start in range(0, len(frame), batch_size):
        yield frame.iloc[start : start + batch_size].reset_index(drop=True)


def _batch_size(batch_size: int | None) -> int:
    if batch_size is not None:
        return batch_size
    return int(os.environ.get("KUMO_QUERY_BATCH", str(_DEFAULT_BATCH)))


def _feature_frame(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    if target in frame.columns:
        return frame.drop(columns=[target])
    return frame


def _tensor(sdm: object, frame: pd.DataFrame, stypes: dict[str, str], device: str):
    return sdm.TableTensor.from_pandas(frame, stypes=stypes, device=device)  # type: ignore[attr-defined]


def _related(sdm: object, tables: dict[str, pd.DataFrame], prepared: Prepared, device: str):
    tensors = {
        name: _tensor(sdm, frame, prepared.related_stypes[name], device)
        for name, frame in tables.items()
    }
    return sdm.RelatedTables(  # type: ignore[attr-defined]
        tables=tensors,
        relationships=prepared.relationships,
        task_links=prepared.task_links,
    )


def _filter_related(prepared: Prepared, batch: pd.DataFrame) -> dict[str, pd.DataFrame]:
    kept: dict[str, pd.DataFrame] = {}
    for link in prepared.task_links:
        table = link["table"]
        key = link["table_columns"]
        task_col = link["task_columns"]
        keys = set(batch[task_col])
        frame = prepared.related_query[table]
        kept[table] = frame.loc[frame[key].isin(keys)].reset_index(drop=True)
    return kept


def predict_tabular(
    prepared: Prepared, *, device: str = "cuda", batch_size: int | None = None
) -> np.ndarray:
    """KumoTabular in-context scores for the full test split."""
    import sdm
    from sdm.models import KumoTabular

    spec = prepared.spec
    step = _batch_size(batch_size)
    size = os.environ.get("KUMO_SIZE", "large")
    model = KumoTabular(task=spec.task, size=size, pretrained=True, device=device)
    features = _feature_frame(prepared.flat_context, spec.target)
    stypes = {col: prepared.flat_stypes[col] for col in features.columns}
    try:
        x_context = _tensor(sdm, features, stypes, device)
        y_context = _tensor(
            sdm,
            prepared.flat_context[[spec.target]],
            {spec.target: prepared.flat_stypes[spec.target]},
            device,
        )
        model.fit(x=x_context, y=y_context)
        parts = [
            scores_from_output(
                model.predict(_tensor(sdm, batch, stypes, device)),
                spec.task,
            )
            for batch in _batches(prepared.flat_query, step)
        ]
        return np.concatenate(parts)
    finally:
        model.clear()


def predict_relational(
    prepared: Prepared, *, device: str = "cuda", batch_size: int | None = None
) -> np.ndarray:
    """KumoRelational in-context scores. Related tables are filtered to each query batch."""
    import sdm
    from sdm.models import KumoRelational

    spec = prepared.spec
    step = _batch_size(batch_size)
    model = KumoRelational(task=spec.task, pretrained=True, device=device)
    x_columns = _feature_frame(prepared.task_context, spec.target).columns
    x_stypes = {col: prepared.task_stypes[col] for col in x_columns}
    try:
        x_context = _tensor(sdm, prepared.task_context[list(x_columns)], x_stypes, device)
        y_context = _tensor(
            sdm,
            prepared.task_context[[spec.target]],
            {spec.target: prepared.task_stypes[spec.target]},
            device,
        )
        related_context = _related(sdm, prepared.related_context, prepared, device)
        model.fit(x_context, y_context, related_context, num_hops=1)
        parts: list[np.ndarray] = []
        for batch in _batches(prepared.task_query, step):
            x_query = _tensor(sdm, batch[list(x_columns)], x_stypes, device)
            related_query = _related(sdm, _filter_related(prepared, batch), prepared, device)
            parts.append(scores_from_output(model.predict(x_query, related_query), spec.task))
        return np.concatenate(parts)
    finally:
        model.clear()
