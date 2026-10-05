"""Retrieval over the governed knowledge base (knowledge/*.md), for two audiences:

* customers get answers only from **public**, **approved**, in-window documents, cited by document and version;
* human agents get the matching **internal** procedures attached to the handoff packet.

Three retrievers read the same active set the platform's kb_sync pipeline indexes (same chunking, same chunk ids,
same multilingual-e5-small embeddings), so they can be compared on one question set:

* ``PgVectorRetriever``: cosine search in Postgres pgvector through ``kb.active_chunk`` (the governed view the
  read-only role is granted), dev stack;
* ``GraphRetriever``: GraphRAG on Neo4j: vector seeds from the ``chunk_embedding`` index, expanded through the
  entities (controls, rules, regulators, regulations) the seed chunks mention, restricted to active versions;
* ``BundledRetriever``: an in-process index built from the same files, for the deployed app, which cannot reach the
  dev stack. Its active-set hash must equal the registry's (``scripts/build_kb_index.py --verify``).

``HybridRetriever`` fuses any two by reciprocal rank.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from copilot.config import REPO

KNOWLEDGE = Path(os.environ.get("COPILOT_KNOWLEDGE", REPO / "knowledge"))
INDEX = Path(os.environ.get("COPILOT_KB_INDEX", REPO / "data" / "copilot" / "kb_index"))
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
SERVABLE = {"approved"}


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    version: str
    title: str
    heading: str
    content: str
    classification: str
    country: str
    score: float = 0.0
    via: list[str] = field(default_factory=list)  # how it was found: vector, graph:<entity>, ...

    @property
    def cite(self) -> str:
        return f"{self.doc_id} v{self.version}"


def parse(path: Path) -> tuple[dict, str]:
    _, front, body = path.read_text().split("---", 2)
    meta = yaml.safe_load(front)
    meta["version"] = str(meta["version"])
    for k in ("effective_from", "effective_to"):
        if isinstance(meta.get(k), str):
            meta[k] = date.fromisoformat(meta[k])
    return meta, body.strip()


def servable(meta: dict, today: date | None = None) -> bool:
    today = today or datetime.now(UTC).date()
    start, end = meta.get("effective_from"), meta.get("effective_to")
    return (
        meta.get("status") in SERVABLE
        and (start is None or start <= today)
        and (end is None or today < end)
    )


def chunk(meta: dict, body: str) -> list[dict]:
    """Identical to latam_platform.kb_pipeline.chunk: level-2 headings, title and heading as context."""
    out = []
    for i, part in enumerate(re.split(r"(?m)^## ", body)):
        lines = part.strip().splitlines()
        if not lines:
            continue
        heading = lines[0].lstrip("# ").strip() if i else "Overview"
        content = "\n".join(lines[1:] if i else lines).strip()
        if not content:
            continue
        text = f"{meta['title']} — {heading}\n{content}"
        out.append(
            {
                "chunk_id": hashlib.sha256(
                    f"{meta['doc_id']}|{meta['version']}|{i}".encode()
                ).hexdigest(),
                "heading": heading,
                "content": text,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    return out


def active_chunks(knowledge: Path = KNOWLEDGE, today: date | None = None) -> list[Chunk]:
    out = []
    for path in sorted(knowledge.glob("*.md")):
        if path.name == "README.md":
            continue
        meta, body = parse(path)
        if not servable(meta, today):
            continue
        for c in chunk(meta, body):
            out.append(
                Chunk(
                    c["chunk_id"],
                    meta["doc_id"],
                    meta["version"],
                    meta["title"],
                    c["heading"],
                    c["content"],
                    meta["classification"],
                    meta.get("country", "ALL"),
                )  # fmt: skip
            )
    return out


def active_set_hash(chunk_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(chunk_ids)).encode()).hexdigest()


class Embedder:
    _model = None

    @classmethod
    def get(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer

            cls._model = SentenceTransformer(EMBEDDING_MODEL)
        return cls._model

    @classmethod
    def query(cls, text: str) -> list[float]:
        return cls.get().encode([f"query: {text}"], normalize_embeddings=True)[0].tolist()

    @classmethod
    def passages(cls, texts: list[str]):
        return cls.get().encode([f"passage: {t}" for t in texts], normalize_embeddings=True)


@dataclass
class Retrieval:
    retriever: str
    chunks: list[Chunk]
    ms: float

    def public(self) -> list[Chunk]:
        return [c for c in self.chunks if c.classification == "public"]

    def internal(self) -> list[Chunk]:
        return [c for c in self.chunks if c.classification != "public"]

    def to_dict(self) -> dict:
        return {
            "retriever": self.retriever,
            "ms": round(self.ms, 2),
            "chunks": [asdict(c) for c in self.chunks],
        }


class BundledRetriever:
    name = "bundled"

    def __init__(self, index: Path = INDEX):
        import numpy as np

        meta = json.loads((index / "chunks.json").read_text())
        self.active_set_hash = meta["active_set_hash"]
        self.chunks = [Chunk(**c) for c in meta["chunks"]]
        self.vectors = np.load(index / "embeddings.npy")

    def search(self, question: str, k: int = 4) -> Retrieval:
        import numpy as np

        t0 = time.perf_counter()
        q = np.asarray(Embedder.query(question))
        scores = self.vectors @ q
        top = np.argsort(-scores)[:k]
        out = [
            Chunk(**{**asdict(self.chunks[i]), "score": float(scores[i]), "via": ["vector"]})
            for i in top
        ]
        return Retrieval(self.name, out, (time.perf_counter() - t0) * 1000)


def build_index(index: Path = INDEX, knowledge: Path = KNOWLEDGE) -> dict:
    import numpy as np

    chunks = active_chunks(knowledge)
    vecs = Embedder.passages([c.content for c in chunks])
    index.mkdir(parents=True, exist_ok=True)
    np.save(index / "embeddings.npy", vecs)
    meta = {
        "embedding_model": EMBEDDING_MODEL,
        "active_set_hash": active_set_hash([c.chunk_id for c in chunks]),
        "built_on": datetime.now(UTC).date().isoformat(),
        "chunks": [asdict(c) for c in chunks],
    }
    (index / "chunks.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return meta


def _dotenv(path: Path) -> dict:
    env = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                env[k] = v.strip().strip('"')
    return env


def _stack_env(key: str) -> str | None:
    """A dev-stack credential: COPILOT_<KEY>, else the stack's own git-ignored platform/docker/.env (the root .env
    may carry an unrelated value under the same name), else the environment."""
    stack = _dotenv(
        Path(os.environ.get("COPILOT_STACK_ENV", REPO / "platform" / "docker" / ".env"))
    )
    return os.environ.get(f"COPILOT_{key}") or stack.get(key) or os.environ.get(key)


class PgVectorRetriever:
    name = "pgvector"

    def __init__(self, dsn: str | None = None):
        import psycopg

        dsn = (
            dsn
            or os.environ.get("COPILOT_KB_PG_DSN")
            or (
                f"postgresql://app_reader:{_stack_env('APP_READER_DB_PASSWORD')}@127.0.0.1:"
                f"{os.environ.get('LATAM_PG_CORE_PORT', '5433')}/knowledge"
            )
        )
        self.con = psycopg.connect(dsn, autocommit=True)

    def chunk_ids(self) -> list[str]:
        return [r[0] for r in self.con.execute("select chunk_id from kb.active_chunk").fetchall()]

    def search(self, question: str, k: int = 4) -> Retrieval:
        t0 = time.perf_counter()
        q = "[" + ",".join(f"{x:.6f}" for x in Embedder.query(question)) + "]"
        rows = self.con.execute(
            # kb.active_chunk is the only relation the read role may see: approved, in-window versions only
            """select chunk_id, doc_id, version, title, heading, content, classification, country,
                      1 - (embedding <=> %s::vector) as score
               from kb.active_chunk
               order by embedding <=> %s::vector limit %s""",
            [q, q, k],
        ).fetchall()
        out = [Chunk(*r[:8], score=float(r[8]), via=["vector"]) for r in rows]
        return Retrieval(self.name, out, (time.perf_counter() - t0) * 1000)


class GraphRetriever:
    """Vector seeds, then one hop through shared entities; only chunks of active versions are ever returned."""

    name = "graph"

    def __init__(
        self,
        uri: str | None = None,
        password: str | None = None,
        seeds: int = 3,
        hop_decay: float = 0.85,
    ):
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(
            uri or os.environ.get("COPILOT_NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=("neo4j", password or _stack_env("NEO4J_PASSWORD")),
        )
        self.seeds, self.decay = seeds, hop_decay

    def search(self, question: str, k: int = 4) -> Retrieval:
        t0 = time.perf_counter()
        records, _, _ = self.driver.execute_query(
            """CALL db.index.vector.queryNodes('chunk_embedding', $n, $q) YIELD node AS seed, score
               MATCH (sv:DocVersion {active: true})-[:HAS_CHUNK]->(seed)
               WITH seed, sv, score ORDER BY score DESC LIMIT $seeds
               OPTIONAL MATCH (seed)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(nb:Chunk)<-[:HAS_CHUNK]-(nv:DocVersion {active: true})
               WHERE nb <> seed
               WITH seed, sv, score, collect({chunk: nb, version: nv, entity: e.type + ':' + e.name}) AS hops
               RETURN seed, sv, score, hops""",
            q=Embedder.query(question),
            n=max(self.seeds * 4, 12),
            seeds=self.seeds,
        )
        found: dict[str, Chunk] = {}
        meta = self._doc_meta()

        def add(node, version, score, via):
            cid = node["chunk_id"]
            m = meta.get((version["doc_id"], version["version"]), {})
            if cid in found:
                found[cid].score = max(found[cid].score, score)
                found[cid].via.append(via)
                return
            found[cid] = Chunk(
                cid, version["doc_id"], version["version"], m.get("title", ""), node["heading"], node["text"],
                m.get("classification", "internal"), m.get("country", "ALL"), score, [via],
            )  # fmt: skip

        for r in records:
            add(r["seed"], r["sv"], float(r["score"]), "vector")
            for h in r["hops"]:
                if h["chunk"] is not None:
                    add(
                        h["chunk"],
                        h["version"],
                        float(r["score"]) * self.decay,
                        f"graph:{h['entity']}",
                    )
        out = sorted(found.values(), key=lambda c: -c.score)[:k]
        return Retrieval(self.name, out, (time.perf_counter() - t0) * 1000)

    def _doc_meta(self) -> dict:
        if not hasattr(self, "_meta"):
            # classification and title are not stored on the graph nodes; read them from the governed files
            self._meta = {}
            for path in KNOWLEDGE.glob("*.md"):
                if path.name != "README.md":
                    m, _ = parse(path)
                    self._meta[(m["doc_id"], m["version"])] = m
        return self._meta


class HybridRetriever:
    def __init__(self, a, b, k_rrf: int = 60):
        self.a, self.b, self.k_rrf = a, b, k_rrf
        self.name = f"hybrid({a.name}+{b.name})"

    def search(self, question: str, k: int = 4) -> Retrieval:
        t0 = time.perf_counter()
        ra, rb = self.a.search(question, k * 2), self.b.search(question, k * 2)
        fused: dict[str, Chunk] = {}
        for r in (ra, rb):
            for rank, c in enumerate(r.chunks):
                cur = fused.setdefault(c.chunk_id, Chunk(**{**asdict(c), "score": 0.0, "via": []}))
                cur.score += 1 / (self.k_rrf + rank + 1)
                cur.via += [f"{r.retriever}:{v}" for v in c.via]
        out = sorted(fused.values(), key=lambda c: -c.score)[:k]
        return Retrieval(self.name, out, (time.perf_counter() - t0) * 1000)
