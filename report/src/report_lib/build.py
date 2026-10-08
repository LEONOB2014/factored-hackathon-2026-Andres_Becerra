"""Helpers for chapter scripts: claims tied to a hashed source, with the right kind and status."""

from __future__ import annotations

from pathlib import Path

from report_lib import sources
from report_lib.manifest import Claim, expected_status

CENSUS = "census of the full table: every row is observed, so there is no sampling error"
CONSTANT = "a constant set in the source (threshold or parameter), not an estimate"


class Chapter:
    """Collects one chapter's claims; `write()` replaces build/claims/NN.parquet."""

    def __init__(self, number: int, prefix: str):
        self.number, self.prefix, self.claims = number, prefix, []
        self.status: str | None = (
            None  # set to "positive-control" while recording claims on planted data
        )
        self._hash: dict[Path, str] = {}

    def _src(self, path: Path, source_type: str) -> dict:
        if path not in self._hash:
            self._hash[path] = sources.sha256(path)
        rel = sources.rel(path)
        status = expected_status(source_type, rel) or self.status or "exploratory"
        extra = {"protocol_commit": self.protocol_commit} if status == "registered" else {}
        return {"source_type": source_type, "source_path": rel, "source_sha256": self._hash[path],
                "status": status, "chapter": self.number, **extra}  # fmt: skip

    def count(
        self, topic: str, value: float, source: Path, source_type: str = "scripted", **kw
    ) -> None:
        self.claims.append(
            Claim(
                id=f"{self.prefix}.{topic}",
                kind="count",
                value=float(value),
                **self._src(source, source_type),
                **kw,
            )
        )

    def census(self, topic: str, value: float, source: Path, source_type: str = "scripted", unit: str | None = None,
               digits: int | None = None) -> None:  # fmt: skip
        """A share or ratio of the whole table: descriptive, no interval (CENSUS)."""
        self.claims.append(
            Claim(
                id=f"{self.prefix}.{topic}",
                kind="descriptive",
                value=float(value),
                reason=CENSUS,
                unit=unit,
                digits=digits,
                **self._src(source, source_type),
            )  # fmt: skip
        )

    def proportion(self, topic: str, num: float, den: float, interval, source: Path, source_type: str = "scripted",
                   cluster_unit: str = "none", digits: int | None = None) -> None:  # fmt: skip
        """num / den with the interval an estimator of report_lib.estimators.intervals returned."""
        self.claims.append(
            Claim(
                id=f"{self.prefix}.{topic}",
                kind="proportion",
                num=float(num),
                den=float(den),
                lo=float(interval.lo),
                hi=float(interval.hi),
                interval_method=interval.method,
                cluster_unit=cluster_unit,
                digits=digits,
                **self._src(source, source_type),
            )
        )

    def constant(self, topic: str, value: float, source: Path, source_type: str = "scripted", unit: str | None = None,
                 digits: int | None = None) -> None:  # fmt: skip
        """A threshold or parameter read from its source: descriptive, no interval (CONSTANT)."""
        self.claims.append(
            Claim(
                id=f"{self.prefix}.{topic}",
                kind="descriptive",
                value=float(value),
                reason=CONSTANT,
                unit=unit,
                digits=digits,
                **self._src(source, source_type),
            )  # fmt: skip
        )

    def metric(self, topic: str, interval, n: float, source: Path, source_type: str = "scripted",
               digits: int | None = None) -> None:  # fmt: skip
        """A model metric (AUC, average precision) with its interval and the rows it was computed on."""
        self.claims.append(
            Claim(
                id=f"{self.prefix}.{topic}",
                kind="metric",
                estimate=float(interval.estimate),
                n=float(n),
                lo=float(interval.lo),
                hi=float(interval.hi),
                interval_method=interval.method,
                digits=digits,
                **self._src(source, source_type),
            )
        )

    def difference(self, topic: str, interval, source: Path, cluster_unit: str, source_type: str = "scripted",
                   unit: str | None = None, digits: int | None = None) -> None:  # fmt: skip
        """A difference of two estimates (B minus A) with its interval."""
        self.claims.append(
            Claim(
                id=f"{self.prefix}.{topic}",
                kind="difference",
                estimate=float(interval.estimate),
                lo=float(interval.lo),
                hi=float(interval.hi),
                interval_method=interval.method,
                cluster_unit=cluster_unit,
                unit=unit,
                digits=digits,
                **self._src(source, source_type),
            )
        )

    def test(self, topic: str, statistic: float, p: float, q: float, family_id: str, family_size: int,
             source: Path, null: str, method: str, source_type: str = "scripted") -> None:  # fmt: skip
        """A hypothesis test with its p-value and its false-discovery adjusted value within its family."""
        self.claims.append(
            Claim(
                id=f"{self.prefix}.{topic}",
                kind="test",
                statistic=float(statistic),
                p=float(p),
                q=float(q),
                family_id=family_id,
                family_size=int(family_size),
                null=null,
                method=method,
                **self._src(source, source_type),
            )
        )

    def write(self) -> Path:
        from report_lib.claims import write_chapter

        return write_chapter(self.number, self.claims)
