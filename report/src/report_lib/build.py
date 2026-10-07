"""Helpers for chapter scripts: claims tied to a hashed source, with the right kind and status."""

from __future__ import annotations

from pathlib import Path

from report_lib import sources
from report_lib.manifest import Claim, expected_status

CENSUS = "census of the full table: every row is observed, so there is no sampling error"


class Chapter:
    """Collects one chapter's claims; `write()` replaces build/claims/NN.parquet."""

    def __init__(self, number: int, prefix: str):
        self.number, self.prefix, self.claims = number, prefix, []
        self._hash: dict[Path, str] = {}

    def _src(self, path: Path, source_type: str) -> dict:
        if path not in self._hash:
            self._hash[path] = sources.sha256(path)
        rel = sources.rel(path)
        status = expected_status(source_type, rel) or "exploratory"
        return {"source_type": source_type, "source_path": rel, "source_sha256": self._hash[path],
                "status": status, "chapter": self.number}  # fmt: skip

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

    def write(self) -> Path:
        from report_lib.claims import write_chapter

        return write_chapter(self.number, self.claims)
