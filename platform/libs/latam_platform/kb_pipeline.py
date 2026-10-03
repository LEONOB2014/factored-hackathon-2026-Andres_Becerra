"""Governed knowledge base sync: knowledge/*.md -> Postgres registry + pgvector chunks + Neo4j graph.

Guarantees (platform/policies/kb_governance.yaml):
  * only `approved` versions inside their effective window are ever indexed or retrievable;
  * versions are immutable: changing content requires a new version (same version + new hash = error);
  * status changes are appended as events, never edits; pruning removes chunks from both indexes and
    marks the Neo4j version inactive, while the registry keeps the full history;
  * documents with personal data are rejected before anything is stored;
  * after every run the active set must be identical in the registry, pgvector and Neo4j (reconcile),
    and a hash of that active set is snapshotted for point-in-time evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from latam_platform import pii_guard

POLICY = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "policies" / "kb_governance.yaml").read_text()
)

REGULATORS = [
    "BCB",
    "CNBV",
    "SFC",
    "BCRA",
    "CONDUSEF",
    "UIF",
    "UIAF",
    "COAF",
    "ANPD",
    "SIC",
    "AAIP",
    "INAI",
    "CMN",
]
REGULATIONS = {
    r"\bLGPD\b": "LGPD",
    r"\bLFPDPPP\b": "LFPDPPP",
    r"\bMED 2\.0\b": "MED 2.0",
    r"\bPL 2338": "PL 2338/2023",
    r"Resolution 493/2025": "BCB Res. 493/2025",
    r"\bLey 1581\b": "Ley 1581/2012",
    r"\bLey 25\.326\b": "Ley 25.326",
    r"\bSR 11-7\b": "SR 11-7",
    r"\bBCBS 239\b": "BCBS 239",
    r"\bPCI DSS\b": "PCI DSS",
}
CONTROL_TO_MODELS = {  # controls of docs/strategy/02 -> dbt models that implement them
    "C1": ["audit_backup_reconciliation"],
    "C2": ["audit_partition_manifest"],
    "C3": ["audit_scd2_change_log", "dim_customer", "dim_product"],
    "C4": ["mart_campaign_compliance_uplift"],
    "C5": ["dq_integrity_findings", "mart_transaction_disputes"],
    "C6": ["feat_fraud_realtime_pit"],
    "C7": ["int_customer_fairness_attributes"],
    "C8": ["mart_credit_eligibility", "mart_card_support"],
    "C9": ["int_customer_profile"],
    "C10": ["dq_rule_summary"],
}


@dataclass
class Doc:
    meta: dict
    body: str
    path: str

    @property
    def key(self) -> tuple[str, str]:
        return self.meta["doc_id"], str(self.meta["version"])

    @property
    def content_hash(self) -> str:
        """Hash of everything that defines a version. `status` is excluded: it is lifecycle, recorded as events."""
        fixed = {k: v for k, v in self.meta.items() if k != "status"}
        return hashlib.sha256(
            (json.dumps(fixed, sort_keys=True, default=str) + self.body).encode()
        ).hexdigest()

    def servable(self, today: date) -> bool:
        m = self.meta
        start, end = m["effective_from"], m.get("effective_to")
        return (
            m["status"] in POLICY["servable_statuses"]
            and start <= today
            and (end is None or today < end)
        )


def _norm(v):
    return None if v in ("null", "None", "") else v


def parse(path: Path) -> Doc:
    text = path.read_text()
    _, front, body = text.split("---", 2)
    meta = {k: _norm(v) for k, v in yaml.safe_load(front).items()}
    for k in ("effective_from", "effective_to"):
        if isinstance(meta.get(k), str):
            meta[k] = date.fromisoformat(meta[k])
    meta["version"] = str(meta["version"])
    return Doc(meta, body.strip(), str(path))


def validate(doc: Doc) -> list[str]:
    # a draft has no approver yet: the approver is only required once a version can be served
    required = [
        k
        for k in POLICY["required_front_matter"]
        if k != "approver" or doc.meta.get("status") in POLICY["servable_statuses"]
    ]
    errs = [f"missing front matter: {k}" for k in required if doc.meta.get(k) in (None, "")]
    if doc.meta.get("classification") not in POLICY["allowed_classifications"]:
        errs.append(
            f"classification {doc.meta.get('classification')} not allowed in the knowledge base"
        )
    scan = pii_guard.scan(doc.body, use_ner=False)
    if scan.has_pii:
        errs.append(f"personal data detected: {scan.entities}")
    return errs


def chunk(doc: Doc) -> list[dict]:
    """Split on level-2 headings; each chunk carries the document title and heading as context."""
    parts = re.split(r"(?m)^## ", doc.body)
    out = []
    for i, part in enumerate(parts):
        lines = part.strip().splitlines()
        if not lines:
            continue
        heading = lines[0].lstrip("# ").strip() if i else "Overview"
        content = "\n".join(lines[1:] if i else lines).strip()
        if not content:
            continue
        text = f"{doc.meta['title']} — {heading}\n{content}"
        cid = hashlib.sha256(f"{doc.meta['doc_id']}|{doc.meta['version']}|{i}".encode()).hexdigest()
        out.append(
            {
                "chunk_id": cid,
                "ordinal": i,
                "heading": heading,
                "content": text,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    return out


def extract_entities(text: str, known_models: set[str]) -> list[tuple[str, str]]:
    ents = set()
    for r in REGULATORS:
        if re.search(rf"\b{r}\b", text):
            ents.add(("Regulator", r))
    for pat, name in REGULATIONS.items():
        if re.search(pat, text):
            ents.add(("Regulation", name))
    ents |= {("Rule", m) for m in re.findall(r"\b(R\d{2})\b", text)}
    ents |= {("Control", m) for m in re.findall(r"\b(C(?:10|[1-9]))\b", text)}
    ents |= {
        ("DbtModel", m) for m in re.findall(r"\b([a-z]+_[a-z0-9_]+)\b", text) if m in known_models
    }
    return sorted(ents)


def local_embedder(model_name: str | None = None) -> Callable[[list[str]], list[list[float]]]:
    """Multilingual E5 run locally (no text leaves the environment). 'passage: ' prefix per E5 convention."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name or POLICY["embedding_model"]["name"])
    return lambda texts: model.encode(
        [f"passage: {t}" for t in texts], normalize_embeddings=True
    ).tolist()


# ------------------------------------------------------------------------------------------------ sync


def sync(
    pg,
    neo,
    docs: list[Doc],
    run_id: str,
    embed: Callable,
    embedding_model: str,
    known_models: set[str],
    today: date | None = None,
) -> dict:
    """Idempotent sync. `pg` is a psycopg connection to the knowledge DB, `neo` a neo4j driver (or None)."""
    today = today or date.today()
    report = {"registered": [], "status_changes": [], "indexed": [], "pruned": [], "rejected": {}}
    current = {
        (d, v): (h, s)
        for d, v, h, s in pg.execute(
            "SELECT d.doc_id, d.version, d.content_hash, s.status FROM kb.document_version d "
            "JOIN kb.current_status s USING (doc_id, version)"
        ).fetchall()
    }
    for doc in docs:
        errs = validate(doc)
        if errs:
            report["rejected"][doc.path] = errs
            continue
        m, key = doc.meta, doc.key
        if key in current and current[key][0] != doc.content_hash:
            report["rejected"][doc.path] = [
                "content changed without a new version (versions are immutable)"
            ]
            continue
        if key not in current:
            pg.execute(
                "INSERT INTO kb.document_version (doc_id, version, status, title, country, language, classification, owner,"
                " approver, effective_from, effective_to, supersedes, source, source_url, content_hash, lineage_run_id)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'knowledge_repo',%s,%s,%s)",
                (
                    *key,
                    m["status"],
                    m["title"],
                    m["country"],
                    m["language"],
                    m["classification"],
                    m["owner"],
                    m.get("approver"),
                    m["effective_from"],
                    m.get("effective_to"),
                    m.get("supersedes"),
                    m.get("source_url"),
                    doc.content_hash,
                    run_id,
                ),
            )
            pg.execute(
                "INSERT INTO kb.document_status_event (doc_id, version, status, reason, lineage_run_id) "
                "VALUES (%s,%s,%s,'registered',%s)",
                (*key, m["status"], run_id),
            )
            report["registered"].append(key)
        elif current[key][1] != m["status"]:
            pg.execute(
                "INSERT INTO kb.document_status_event (doc_id, version, status, reason, lineage_run_id) "
                "VALUES (%s,%s,%s,'status changed in knowledge repo',%s)",
                (*key, m["status"], run_id),
            )
            report["status_changes"].append((*key, current[key][1], m["status"]))
        # index servable versions that have no chunks yet
        has_chunks = pg.execute(
            "SELECT count(*) FROM kb.chunk WHERE doc_id=%s AND version=%s", key
        ).fetchone()[0]
        if doc.servable(today) and not has_chunks:
            chunks = chunk(doc)
            vecs = embed([c["content"] for c in chunks])
            for c, v in zip(chunks, vecs):
                pg.execute(
                    "INSERT INTO kb.chunk (chunk_id, doc_id, version, ordinal, heading, content, content_hash,"
                    " embedding, embedding_model) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)",
                    (
                        c["chunk_id"],
                        *key,
                        c["ordinal"],
                        c["heading"],
                        c["content"],
                        c["content_hash"],
                        str(v),
                        embedding_model,
                    ),
                )
            if neo:
                _neo_upsert_version(neo, doc, chunks, vecs, known_models)
            report["indexed"].append(key)

    # prune: anything with chunks that is no longer servable (status or effective window)
    active = {
        tuple(r)
        for r in pg.execute("SELECT DISTINCT doc_id, version FROM kb.active_chunk").fetchall()
    }
    with_chunks = {
        tuple(r) for r in pg.execute("SELECT DISTINCT doc_id, version FROM kb.chunk").fetchall()
    }
    for key in sorted(with_chunks - active):
        pg.execute("DELETE FROM kb.chunk WHERE doc_id=%s AND version=%s", key)
        if neo:
            neo.execute_query(
                "MATCH (v:DocVersion {doc_id: $d, version: $v}) SET v.active = false, v.pruned_run = $r "
                "WITH v OPTIONAL MATCH (v)-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE c",
                d=key[0],
                v=key[1],
                r=run_id,
            )
        report["pruned"].append(key)

    rec = reconcile(pg, neo)
    snap = sorted(
        [{"doc_id": d, "version": v} for d, v in rec["registry"]],
        key=lambda x: (x["doc_id"], x["version"]),
    )
    digest = hashlib.sha256(json.dumps(snap).encode()).hexdigest()
    pg.execute(
        "INSERT INTO kb.active_set_snapshot (lineage_run_id, active_versions, digest) VALUES (%s,%s,%s)",
        (run_id, json.dumps(snap), digest),
    )
    report["active"] = len(snap)
    report["reconciled"] = rec["ok"]
    report["active_set_digest"] = digest
    return report


def reconcile(pg, neo) -> dict:
    """Active set must match across the registry (servable by status+window), pgvector chunks and Neo4j."""
    registry = {
        tuple(r)
        for r in pg.execute(
            "SELECT d.doc_id, d.version FROM kb.document_version d JOIN kb.current_status s USING (doc_id, version) "
            "WHERE s.status = 'approved' AND d.effective_from <= current_date "
            "AND (d.effective_to IS NULL OR current_date < d.effective_to)"
        ).fetchall()
    }
    vectors = {
        tuple(r)
        for r in pg.execute("SELECT DISTINCT doc_id, version FROM kb.active_chunk").fetchall()
    }
    graph = registry
    if neo:
        recs, _, _ = neo.execute_query(
            "MATCH (v:DocVersion {active: true}) RETURN v.doc_id AS d, v.version AS v"
        )
        graph = {(r["d"], r["v"]) for r in recs}
    return {
        "ok": registry == vectors == graph,
        "registry": registry,
        "missing_in_vectors": registry - vectors,
        "missing_in_graph": registry - graph,
        "extra_in_graph": graph - registry,
    }


def _neo_upsert_version(
    neo, doc: Doc, chunks: list[dict], vecs: list[list[float]], known_models: set[str]
) -> None:
    m = doc.meta
    neo.execute_query(
        """MERGE (d:Document {doc_id: $doc_id}) SET d.title = $title, d.country = $country
           MERGE (v:DocVersion {doc_id: $doc_id, version: $version})
           SET v.status = $status, v.active = true, v.effective_from = date($ef), v.effective_to = $et,
               v.content_hash = $hash, v.classification = $cls
           MERGE (d)-[:HAS_VERSION]->(v)
           WITH v
           OPTIONAL MATCH (prev:DocVersion {doc_id: $doc_id, version: $supersedes})
           FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | MERGE (v)-[:SUPERSEDES]->(prev))""",
        doc_id=m["doc_id"],
        version=m["version"],
        title=m["title"],
        country=m["country"],
        status=m["status"],
        ef=str(m["effective_from"]),
        et=str(m["effective_to"]) if m.get("effective_to") else None,
        hash=doc.content_hash,
        cls=m["classification"],
        supersedes=m.get("supersedes"),
    )
    rows = [
        {
            "chunk_id": c["chunk_id"],
            "ordinal": c["ordinal"],
            "heading": c["heading"],
            "content": c["content"],
            "embedding": v,
            "entities": [
                {"type": t, "name": n} for t, n in extract_entities(c["content"], known_models)
            ],
        }
        for c, v in zip(chunks, vecs)
    ]
    neo.execute_query(
        """UNWIND $rows AS r
           MATCH (v:DocVersion {doc_id: $doc_id, version: $version})
           MERGE (c:Chunk {chunk_id: r.chunk_id})
           SET c.ordinal = r.ordinal, c.heading = r.heading, c.text = r.content, c.embedding = r.embedding
           MERGE (v)-[:HAS_CHUNK]->(c)
           WITH c, r UNWIND r.entities AS e
           MERGE (n:Entity {type: e.type, name: e.name})
           MERGE (c)-[:MENTIONS]->(n)""",
        rows=rows,
        doc_id=m["doc_id"],
        version=m["version"],
    )


def ensure_neo4j_schema(neo, dimension: int = 384) -> None:
    for q in [
        "CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
        "CREATE CONSTRAINT docversion_key IF NOT EXISTS FOR (v:DocVersion) REQUIRE (v.doc_id, v.version) IS UNIQUE",
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
        "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE (e.type, e.name) IS UNIQUE",
        f"CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON c.embedding "
        f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dimension}, `vector.similarity_function`: 'cosine'}}}}",
    ]:
        neo.execute_query(q)
    rows = [{"control": c, "model": mdl} for c, ms in CONTROL_TO_MODELS.items() for mdl in ms]
    neo.execute_query(
        """UNWIND $rows AS r
                         MERGE (c:Entity {type: 'Control', name: r.control})
                         MERGE (m:Entity {type: 'DbtModel', name: r.model})
                         MERGE (c)-[:IMPLEMENTED_BY]->(m)""",
        rows=rows,
    )
