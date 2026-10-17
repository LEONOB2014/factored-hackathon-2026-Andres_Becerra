"""The privacy guard for every generated table and figure.

No identifier column, and no cell or plotted group built from fewer than `privacy.min_cell` customers
(conf/protocol.toml), may reach the PDF.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

import pandas as pd

IDENTIFIER = re.compile(
    r"(^|_)(customer|client|account|card|agent|employee|user|person|party|transaction|complaint|interaction|"
    r"transcript|session|device|branch_staff)_?(id|number|no|key)$|^(id|uuid)$|_uuid$|"
    r"(^|_)(full_?name|first_?name|last_?name|surname|customer_?name|email|e_?mail|phone|mobile|"
    r"document_?(id|number)|national_?id|iban|address|free_?text|transcript|comment|notes?)$",
    re.I,
)
COUNT_COLUMNS = re.compile(
    r"^(n|n_customers|customers|customer_count|count|n_obs|contributors)$", re.I
)


class PrivacyError(ValueError):
    pass


def check_frame(frame: pd.DataFrame, min_cell: int, count_cols: Iterable[str] = ()) -> None:
    ids = [c for c in frame.columns if IDENTIFIER.search(str(c))]
    if ids:
        raise PrivacyError(f"identifier columns may not be published: {', '.join(map(str, ids))}")
    cols = set(count_cols) | {c for c in frame.columns if COUNT_COLUMNS.match(str(c))}
    for c in sorted(cols):
        if c not in frame.columns:
            raise PrivacyError(f"declared count column {c!r} is missing")
        v = pd.to_numeric(frame[c], errors="coerce")
        small = frame[(v > 0) & (v < min_cell)]
        if len(small):
            raise PrivacyError(
                f"{len(small)} row(s) of {c!r} count fewer than {min_cell} contributors; aggregate them"
            )


def check_groups(sizes: Mapping[str, float], min_cell: int) -> None:
    small = {k: v for k, v in sizes.items() if 0 < v < min_cell}
    if small:
        raise PrivacyError(
            f"plotted groups below {min_cell} contributors: {', '.join(map(str, small))}"
        )
