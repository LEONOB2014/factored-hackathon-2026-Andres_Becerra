"""Client for the append-only, hash-chained audit store (pg-audit).

The database computes every hash (see platform/docker/postgres-audit/sql/02_audit_schema.sql); this
client only inserts, verifies and anchors. Personal fields inside payloads are encrypted with a per-subject
data key (AES-256-GCM) so an erasure request can be honoured by destroying the key (crypto-shredding)
while every chain stays verifiable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CHAINED_TABLES = [
    "ledger.event",
    "ledger.anchor",
    "genai.model_version",
    "genai.prompt_version",
    "genai.request",
    "genai.retrieval",
    "genai.generation",
    "genai.human_override",
    "genai.feedback",
    "compliance.trigger_event",
    "privacy.budget_ledger",
    "dsar.request",
]


def dsn(
    user: str = "audit_writer", password_env: str = "AUDIT_WRITER_PASSWORD", db: str = "audit"
) -> str:
    host = os.environ.get("LATAM_PG_AUDIT_HOST", "pg-audit")
    port = os.environ.get("LATAM_PG_AUDIT_PORT", "5432")
    return f"postgresql://{user}:{os.environ[password_env]}@{host}:{port}/{db}"


# ------------------------------------------------------------------------------ crypto-shredding keys


def _master_key() -> bytes:
    """Key-encryption key. Locally from env; in production a KMS/HSM key that never leaves the HSM."""
    raw = os.environ.get("LATAM_AUDIT_MASTER_KEY") or os.environ.get(
        "LATAM_PII_SALT", "local-dev-master-key"
    )
    return hashlib.sha256(raw.encode()).digest()


def _subject_key(
    conn: psycopg.Connection, subject_token: str, create: bool = True
) -> tuple[str, bytes] | None:
    row = conn.execute(
        "SELECT key_id, wrapped_key FROM keys.subject_key WHERE subject_token = %s",
        (subject_token,),
    ).fetchone()
    if row:
        if row[1] is None:
            return None  # shredded
        nonce, ct = bytes(row[1][:12]), bytes(row[1][12:])
        return row[0], AESGCM(_master_key()).decrypt(nonce, ct, subject_token.encode())
    if not create:
        return None
    key, nonce = AESGCM.generate_key(256), os.urandom(12)
    wrapped = nonce + AESGCM(_master_key()).encrypt(nonce, key, subject_token.encode())
    key_id = f"sk-{uuid.uuid4()}"
    conn.execute(
        "INSERT INTO keys.subject_key (key_id, subject_token, wrapped_key) VALUES (%s, %s, %s)",
        (key_id, subject_token, wrapped),
    )
    return key_id, key


def encrypt_for_subject(conn, subject_token: str, value: str) -> tuple[str, str]:
    key_id, key = _subject_key(conn, subject_token)
    nonce = os.urandom(12)
    return key_id, base64.b64encode(
        nonce + AESGCM(key).encrypt(nonce, value.encode(), key_id.encode())
    ).decode()


def decrypt_for_subject(conn, subject_token: str, blob: str) -> str | None:
    k = _subject_key(conn, subject_token, create=False)
    if k is None:
        return None  # shredded or never existed
    key_id, key = k
    raw = base64.b64decode(blob)
    return AESGCM(key).decrypt(raw[:12], raw[12:], key_id.encode()).decode()


def shred_subject(conn, subject_token: str, actor: str, dsar_id: str | None = None) -> bool:
    cur = conn.execute(
        "UPDATE keys.subject_key SET wrapped_key = NULL, shredded_at = now() "
        "WHERE subject_token = %s AND wrapped_key IS NOT NULL RETURNING key_id",
        (subject_token,),
    )
    row = cur.fetchone()
    append_event(
        conn,
        actor,
        "privacy.subject_key_shredded",
        subject_token,
        {"key_id": row[0] if row else None, "dsar_id": dsar_id, "already_shredded": row is None},
    )
    return row is not None


# ----------------------------------------------------------------------------------------- events


def append_event(
    conn,
    actor: str,
    event_type: str,
    subject_ref: str | None,
    payload: dict,
    lineage_run_id: str | None = None,
    pii_fields: dict | None = None,
    subject_token: str | None = None,
) -> str:
    """Append one event. `pii_fields` are encrypted with the subject's key before they reach the payload."""
    body, key_id = dict(payload), None
    if pii_fields:
        if not subject_token:
            raise ValueError("pii_fields require subject_token (needed for crypto-shredding)")
        enc = {}
        for k, v in pii_fields.items():
            key_id, enc[k] = encrypt_for_subject(conn, subject_token, str(v))
        body["encrypted"] = enc
    row = conn.execute(
        "INSERT INTO ledger.event (event_time, actor, event_type, subject_ref, lineage_run_id, payload, pii_key_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING event_id",
        (
            datetime.now(UTC),
            actor,
            event_type,
            subject_ref,
            lineage_run_id,
            json.dumps(body, default=str),
            key_id,
        ),
    ).fetchone()
    return str(row[0])


# ---------------------------------------------------------------------------- verification + anchoring


def verify_all(conn) -> dict[str, list[tuple[int, str]]]:
    return {
        t: [
            tuple(r)
            for r in conn.execute(
                "SELECT * FROM ledger.verify_chain(%s::regclass)", (t,)
            ).fetchall()
        ]
        for t in CHAINED_TABLES
    }


def merkle_root(leaves: list[str]) -> str:
    level = [hashlib.sha256(x.encode()).hexdigest() for x in sorted(leaves)] or [
        hashlib.sha256(b"").hexdigest()
    ]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256((a + b).encode()).hexdigest() for a, b in zip(level[::2], level[1::2])
        ]
    return level[0]


def anchor(conn, s3_client, bucket: str = "audit-anchors") -> dict:
    """Verify every chain, then write the heads + Merkle root to object-locked storage and record it."""
    heads = {
        c: {"seq": s, "row_hash": h}
        for c, s, h in conn.execute(
            "SELECT chain, seq, row_hash FROM ledger.chain_head ORDER BY chain"
        ).fetchall()
    }
    problems = {t: p for t, p in verify_all(conn).items() if p}
    root = merkle_root([f"{c}:{v['seq']}:{v['row_hash']}" for c, v in heads.items()])
    now = datetime.now(UTC)
    key = f"anchors/{now:%Y/%m/%d}/{now:%H%M%S}-{root[:16]}.json"
    doc = {
        "anchored_at": now.isoformat(),
        "heads": heads,
        "merkle_root": root,
        "verified_ok": not problems,
        "problems": problems,
    }
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(doc, indent=1).encode(),
        ContentType="application/json",
    )  # bucket default retention = COMPLIANCE
    conn.execute(
        "INSERT INTO ledger.anchor (anchored_at, heads, merkle_root, object_uri, verified_ok, problems) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            now,
            json.dumps(heads),
            root,
            f"s3://{bucket}/{key}",
            not problems,
            json.dumps(problems) or None,
        ),
    )
    return doc
