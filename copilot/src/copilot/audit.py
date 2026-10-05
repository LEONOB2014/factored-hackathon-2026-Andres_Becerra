"""An append-only, SHA-256 hash-chained audit log: each record carries the previous record's hash, so any edit or
deletion breaks verification from that point on. Records hold masked text and decisions, never model reasoning."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

GENESIS = "0" * 64


def _digest(prev: str, body: dict) -> str:
    return hashlib.sha256(
        (prev + json.dumps(body, sort_keys=True, default=str)).encode()
    ).hexdigest()


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.head, self.seq = GENESIS, 0
        if path.is_file():
            for line in path.read_text().splitlines():
                rec = json.loads(line)
                self.head, self.seq = rec["hash"], rec["seq"]

    def append(self, kind: str, **fields) -> dict:
        with self._lock:
            body = {
                "seq": self.seq + 1,
                "ts": datetime.now(UTC).isoformat(),
                "kind": kind,
                "prev": self.head,
                **fields,
            }
            rec = {**body, "hash": _digest(self.head, body)}
            with self.path.open("a") as f:
                f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
            self.head, self.seq = rec["hash"], rec["seq"]
            return rec

    def verify(self) -> dict:
        prev, n = GENESIS, 0
        if not self.path.is_file():
            return {"ok": True, "records": 0, "head": prev}
        for line in self.path.read_text().splitlines():
            rec = json.loads(line)
            body = {k: v for k, v in rec.items() if k != "hash"}
            if rec["prev"] != prev or _digest(prev, body) != rec["hash"]:
                return {"ok": False, "records": n, "broken_at": rec.get("seq"), "head": prev}
            prev, n = rec["hash"], n + 1
        return {"ok": True, "records": n, "head": prev}
