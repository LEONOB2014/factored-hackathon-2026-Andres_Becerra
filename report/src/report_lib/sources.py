"""Hashing and reading the artefacts claims are drawn from."""

from __future__ import annotations

import hashlib
from pathlib import Path

from report_lib.paths import REPO


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    """Path relative to the repository root, as claims record it (absolute for files outside the repository).

    A worktree's data/ is a symlink to the main checkout's, so a file reached through it (or through its target)
    is recorded as data/..., never as the machine's own path.
    """
    resolved = path.resolve()
    for root, prefix in ((REPO.resolve(), ""), ((REPO / "data").resolve(), "data/")):
        try:
            return prefix + resolved.relative_to(root).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()
