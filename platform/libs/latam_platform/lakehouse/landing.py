"""Landing zone manifest: proves what was received, byte for byte.

The landing zone (data/raw) holds files exactly as delivered by the source. Each ingestion run writes a
manifest with size, line count and SHA-256 per file plus a root digest. Comparing two manifests detects
new files (expected), and modified or deleted files (an integrity incident: landing is write-once).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from latam_platform import config


@dataclass
class FileEntry:
    path: str  # relative to the landing root
    size: int
    lines: int
    sha256: str


def _hash_file(p: Path) -> tuple[str, int]:
    h, lines = hashlib.sha256(), 0
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            lines += chunk.count(b"\n")
    return h.hexdigest(), lines


def build_manifest(root: Path = config.LANDING, run_id: str | None = None) -> dict:
    files = []
    for p in sorted(root.rglob("*.csv")):
        digest, lines = _hash_file(p)
        files.append(FileEntry(str(p.relative_to(root)), p.stat().st_size, lines, digest))
    root_digest = hashlib.sha256(
        "\n".join(f"{f.path}:{f.sha256}" for f in files).encode()
    ).hexdigest()
    return {
        "run_id": run_id or datetime.now(UTC).strftime("landing-%Y%m%dT%H%M%SZ"),
        "created_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "n_files": len(files),
        "bytes": sum(f.size for f in files),
        "root_digest": root_digest,
        "files": [asdict(f) for f in files],
    }


def diff_manifests(previous: dict, current: dict) -> dict:
    prev = {f["path"]: f["sha256"] for f in previous["files"]}
    cur = {f["path"]: f["sha256"] for f in current["files"]}
    return {
        "new": sorted(set(cur) - set(prev)),
        "deleted": sorted(set(prev) - set(cur)),  # incident: landing is write-once
        "modified": sorted(p for p in set(cur) & set(prev) if cur[p] != prev[p]),  # incident
    }


def write_manifest(manifest: dict, out_dir: Path = config.MANIFESTS / "landing") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{manifest['run_id']}.json"
    out.write_text(json.dumps(manifest, indent=1))
    (out_dir / "latest.json").write_text(json.dumps(manifest, indent=1))
    return out


def latest_manifest(out_dir: Path = config.MANIFESTS / "landing") -> dict | None:
    p = out_dir / "latest.json"
    return json.loads(p.read_text()) if p.exists() else None
