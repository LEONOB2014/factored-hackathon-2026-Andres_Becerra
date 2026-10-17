"""The claim schema: one row per number cited in the report, validated by kind.

A claim id is `<chapter>.<topic>` and names one row; `\\est{id}{field}` picks a field of that row.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Kind = Literal[
    "count",
    "proportion",
    "rate",
    "difference",
    "ratio",
    "test",
    "metric",
    "location",
    "descriptive",
]
Status = Literal["exploratory", "registered", "positive-control"]
SourceType = Literal["notebook", "table", "scripted"]
IntervalMethod = Literal[
    "naive-iid",
    "wilson-iid",
    "bootstrap-iid",
    "poisson-exact",
    "cluster-bootstrap",
    "block-bootstrap",
    "wild-cluster-bootstrap",
    "cr2",
    "delong",
    "model-robust",
]

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9.-]*[a-z0-9]$")
IID_METHODS = {"naive-iid", "wilson-iid", "bootstrap-iid", "poisson-exact"}

# Fields each kind must carry (besides the common ones). An interval, when required, means lo, hi and
# interval_method together.
REQUIRED: dict[str, tuple[str, ...]] = {
    "count": ("value",),
    "proportion": ("num", "den", "lo", "hi", "interval_method", "cluster_unit"),
    "rate": ("events", "exposure", "lo", "hi", "interval_method", "cluster_unit"),
    "difference": ("estimate", "lo", "hi", "interval_method", "cluster_unit"),
    "ratio": ("estimate", "lo", "hi", "interval_method", "cluster_unit"),
    "test": ("statistic", "p", "family_id", "q", "family_size"),
    "metric": ("estimate", "n", "lo", "hi", "interval_method"),
    "location": ("value", "method"),
    "descriptive": ("value", "reason"),
}
NUMERIC = (
    "value", "estimate", "num", "den", "events", "exposure", "lo", "hi", "se", "statistic", "df", "p",
    "q", "family_size", "n",
)  # fmt: skip


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Kind
    status: Status
    source_type: SourceType
    source_path: str
    source_sha256: str
    chapter: int
    value: float | None = None
    estimate: float | None = None
    num: float | None = None
    den: float | None = None
    events: float | None = None
    exposure: float | None = None
    lo: float | None = None
    hi: float | None = None
    se: float | None = None
    interval_method: IntervalMethod | None = None
    cluster_unit: str | None = None
    statistic: float | None = None
    df: float | None = None
    null: str | None = None
    p: float | None = None
    q: float | None = None
    family_id: str | None = None
    family_size: int | None = None
    n: float | None = None
    method: str | None = None
    reason: str | None = None
    unit: str | None = None
    digits: int | None = None
    protocol_commit: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Claim:
        if not ID_RE.match(self.id):
            raise ValueError(f"claim id {self.id!r} is not '<chapter>.<topic>' in lowercase")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError(f"{self.id}: source_sha256 is not a SHA-256 hex digest")
        for f in NUMERIC:
            v = getattr(self, f)
            if v is not None and not math.isfinite(v):
                raise ValueError(f"{self.id}: {f} is not finite")
        missing = [f for f in REQUIRED[self.kind] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.id}: kind {self.kind} needs {', '.join(missing)}")
        if self.den is not None and self.den <= 0:
            raise ValueError(f"{self.id}: denominator must be positive")
        if self.lo is not None and self.hi is not None and self.lo > self.hi:
            raise ValueError(f"{self.id}: interval lower bound above upper bound")
        if self.cluster_unit == "none" and self.interval_method not in IID_METHODS:
            raise ValueError(f"{self.id}: cluster_unit none is only allowed with an iid interval")
        for f in ("p", "q"):
            v = getattr(self, f)
            if v is not None and not 0 <= v <= 1:
                raise ValueError(f"{self.id}: {f} outside [0, 1]")
        if self.status == "registered" and not self.protocol_commit:
            raise ValueError(f"{self.id}: registered claims must cite the protocol commit")
        expected = expected_status(self.source_type, self.source_path)
        if expected is not None and self.status != expected:
            raise ValueError(
                f"{self.id}: a {self.source_type} claim from {self.source_path} must be {expected}"
            )
        return self


POSITIVE_CONTROL_SOURCES = ("eda/notebooks/08_anomaly_detection_ml",)


def expected_status(source_type: str, source_path: str) -> str | None:
    """The status a claim must have, derived from where it comes from (None: scripted, decided by the run)."""
    if source_type == "scripted":
        return None
    if any(source_path.startswith(s) for s in POSITIVE_CONTROL_SOURCES):
        return "positive-control"
    return "exploratory"
