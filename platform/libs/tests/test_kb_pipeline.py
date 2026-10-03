"""Knowledge base governance: drafts/superseded/expired never served, PII blocked, versions immutable, reconciled."""

import hashlib
import shutil
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest

from latam_platform import kb_pipeline

ROOT = Path(__file__).resolve().parents[3]
KB_SQL = (
    (ROOT / "platform" / "docker" / "postgres-core" / "03_knowledge.sql")
    .read_text()
    .replace("\\connect knowledge", "")
)


def fake_embed(texts):
    out = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        v = [(h[i % 32] - 128) / 128 for i in range(384)]
        n = sum(x * x for x in v) ** 0.5
        out.append([x / n for x in v])
    return out


@pytest.fixture
def kb(audit_db):
    base = audit_db["superuser"].rsplit("/", 1)[0]
    db = f"kb_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(f"{base}/postgres", autocommit=True) as a:
        a.execute(f"CREATE DATABASE {db} OWNER publisher")
    with psycopg.connect(f"{base}/{db}", autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute(KB_SQL)
    conn = psycopg.connect(f"{base}/{db}", autocommit=True)
    yield conn
    conn.close()
    with psycopg.connect(f"{base}/postgres", autocommit=True) as a:
        a.execute(f"DROP DATABASE {db} WITH (FORCE)")


def _docs(folder):
    return [kb_pipeline.parse(p) for p in sorted(Path(folder).glob("*_v*.md"))]


def test_only_approved_effective_versions_are_served(kb):
    rep = kb_pipeline.sync(
        kb,
        None,
        _docs(ROOT / "knowledge"),
        "run-1",
        fake_embed,
        "fake",
        set(),
        today=date(2026, 10, 2),
    )
    active = {
        tuple(r)
        for r in kb.execute("SELECT DISTINCT doc_id, version FROM kb.active_chunk").fetchall()
    }
    assert ("pol-card-dispute", "2.0") in active
    assert ("pol-card-dispute", "1.0") not in active  # superseded
    assert ("pol-aml-monitoring-thresholds", "0.3") not in active  # draft
    assert ("std-card-reissue-sla", "1.0") not in active  # retired
    assert ("reg-br-pl2338-status", "1.0") not in active  # expired window
    assert rep["reconciled"] and not rep["rejected"]
    assert (
        kb.execute("SELECT count(*) FROM kb.document_version").fetchone()[0] == 13
    )  # history kept


def test_supersede_prunes_old_version_and_keeps_history(kb, tmp_path):
    shutil.copytree(ROOT / "knowledge", tmp_path / "kb")
    kb_pipeline.sync(
        kb,
        None,
        _docs(tmp_path / "kb"),
        "run-1",
        fake_embed,
        "fake",
        set(),
        today=date(2026, 10, 2),
    )
    # publish consent policy v1.1 and supersede v1.0
    old = tmp_path / "kb" / "pol-marketing-consent_v1.0.md"
    new = tmp_path / "kb" / "pol-marketing-consent_v1.1.md"
    new.write_text(
        old.read_text()
        .replace("version: 1.0", "version: 1.1")
        .replace("supersedes: null", "supersedes: 1.0")
        + "\n## Channels\nWhatsApp consent is collected separately from SMS consent.\n"
    )
    old.write_text(old.read_text().replace("status: approved", "status: superseded"))
    rep = kb_pipeline.sync(
        kb,
        None,
        _docs(tmp_path / "kb"),
        "run-2",
        fake_embed,
        "fake",
        set(),
        today=date(2026, 10, 2),
    )
    assert ("pol-marketing-consent", "1.0") in rep["pruned"]
    assert ("pol-marketing-consent", "1.1") in rep["indexed"]
    events = kb.execute(
        "SELECT status FROM kb.document_status_event WHERE doc_id='pol-marketing-consent' AND version='1.0' "
        "ORDER BY event_id"
    ).fetchall()
    assert [e[0] for e in events] == ["approved", "superseded"]
    assert kb.execute("SELECT count(*) FROM kb.active_set_snapshot").fetchone()[0] == 2


def test_pii_and_silent_edits_are_rejected(kb, tmp_path):
    shutil.copytree(ROOT / "knowledge", tmp_path / "kb")
    kb_pipeline.sync(
        kb,
        None,
        _docs(tmp_path / "kb"),
        "run-1",
        fake_embed,
        "fake",
        set(),
        today=date(2026, 10, 2),
    )
    leak = tmp_path / "kb" / "pol-leak_v1.0.md"
    leak.write_text(
        (tmp_path / "kb" / "pol-genai-use_v1.0.md").read_text().replace("pol-genai-use", "pol-leak")
        + "\n## Example\nCustomer CPF 529.982.247-25 called about a refund.\n"
    )
    edited = tmp_path / "kb" / "pol-genai-use_v1.0.md"
    edited.write_text(edited.read_text().replace("never compute amounts", "may compute amounts"))
    rep = kb_pipeline.sync(
        kb,
        None,
        _docs(tmp_path / "kb"),
        "run-2",
        fake_embed,
        "fake",
        set(),
        today=date(2026, 10, 2),
    )
    assert any("personal data" in e for e in rep["rejected"][str(leak)])
    assert any("immutable" in e for e in rep["rejected"][str(edited)])
