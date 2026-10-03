"""GenAI audit trail: every LLM interaction is reconstructable after the fact.

For each request the audit store keeps (all append-only, hash-chained, see genai.* tables):
  model layer     exact model version (provider, model, revision/weights hash, quantization)
  prompt layer    exact system instructions + template (content-hashed, approved, effective-dated)
  retrieval layer every document/chunk pulled by RAG/GraphRAG with version, hash, score and KB snapshot
  output layer    redacted input/output, hash of the exact output shown, guardrail verdicts, tool calls
  human layer     any reviewer approval, edit, rejection or escalation (overrides)
MLflow Tracing captures the span tree; `trace_id` links both worlds. Text is passed through pii_guard
before storage; the unredacted output survives only as a SHA-256 so a disputed answer can be proven.

The Agentic module (pending) calls `AuditedLLM.call(...)`; the platform never logs prompts elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime

from latam_platform import pii_guard


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class ModelVersion:
    provider: str
    model_name: str
    revision: str
    weights_sha256: str | None = None
    quantization: str | None = None
    serving_runtime: str | None = None

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.model_name}@{self.revision}"


@dataclass(frozen=True)
class PromptVersion:
    name: str
    semver: str
    system_instructions: str
    template: str

    @property
    def id(self) -> str:
        return f"{self.name}@{self.semver}"

    @property
    def content_sha256(self) -> str:
        return sha256(self.system_instructions + "\x00" + self.template)


@dataclass
class RetrievedItem:
    source: str  # pgvector | neo4j | sql_tool
    doc_id: str | None
    doc_version: str | None
    chunk_id: str | None
    content: str
    score: float | None = None


@dataclass
class LLMResult:
    output: str
    tool_calls: list[dict] = field(default_factory=list)
    tokens_in: int | None = None
    tokens_out: int | None = None


def register_model_version(
    conn,
    mv: ModelVersion,
    registered_by: str,
    approved_by: str | None = None,
    approval_ref: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO genai.model_version (model_version_id, provider, model_name, revision, weights_sha256, quantization,"
        " serving_runtime, approved_by, approval_ref, registered_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (model_version_id) DO NOTHING",
        (
            mv.id,
            mv.provider,
            mv.model_name,
            mv.revision,
            mv.weights_sha256,
            mv.quantization,
            mv.serving_runtime,
            approved_by,
            approval_ref,
            registered_by,
        ),
    )


def register_prompt_version(
    conn,
    pv: PromptVersion,
    registered_by: str,
    approved_by: str | None = None,
    effective_from: datetime | None = None,
) -> None:
    conn.execute(
        "INSERT INTO genai.prompt_version (prompt_version_id, prompt_name, system_instructions, template, content_sha256,"
        " effective_from, approved_by, registered_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (prompt_version_id) DO NOTHING",
        (
            pv.id,
            pv.name,
            pv.system_instructions,
            pv.template,
            pv.content_sha256,
            effective_from or datetime.now(UTC),
            approved_by,
            registered_by,
        ),
    )


class AuditedLLM:
    """Wraps any `llm_fn(system, user, context) -> LLMResult` with guardrails and the audit trail."""

    def __init__(
        self,
        conn,
        model: ModelVersion,
        prompt: PromptVersion,
        llm_fn: Callable[..., LLMResult],
        output_guards: list[Callable[[str, list[RetrievedItem]], dict]] | None = None,
        use_mlflow: bool = True,
    ):
        self.conn, self.model, self.prompt, self.llm_fn = conn, model, prompt, llm_fn
        self.output_guards = output_guards or []
        self.use_mlflow = use_mlflow

    def _span(self, name: str):
        if not self.use_mlflow:
            return nullcontext(None)
        try:
            import mlflow

            return mlflow.start_span(name=name)
        except Exception:  # tracing must never break the request
            return nullcontext(None)

    def call(
        self,
        *,
        user_input: str,
        caller: str,
        purpose: str,
        retrieved: list[RetrievedItem],
        country: str | None = None,
        channel: str | None = None,
        subject_token: str | None = None,
        kb_snapshot_id: int | None = None,
        parameters: dict | None = None,
    ) -> dict:
        request_id = uuid.uuid4()
        parameters = parameters or {}
        input_red, input_scan = pii_guard.redact(user_input, use_ner=False)
        with self._span(f"genai.{purpose}") as span:
            trace_id = getattr(span, "trace_id", None) or getattr(span, "request_id", None)
            self.conn.execute(
                "INSERT INTO genai.request (request_id, trace_id, caller, purpose, country, channel, subject_token, received_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    request_id,
                    trace_id,
                    caller,
                    purpose,
                    country,
                    channel,
                    subject_token,
                    datetime.now(UTC),
                ),
            )
            for rank, item in enumerate(retrieved, start=1):
                self.conn.execute(
                    "INSERT INTO genai.retrieval (request_id, rank, source, doc_id, doc_version, chunk_id, chunk_sha256, score,"
                    " kb_snapshot_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        request_id,
                        rank,
                        item.source,
                        item.doc_id,
                        item.doc_version,
                        item.chunk_id,
                        sha256(item.content),
                        item.score,
                        kb_snapshot_id,
                    ),
                )
            context = "\n\n".join(f"[{i.doc_id}@{i.doc_version}] {i.content}" for i in retrieved)
            t0 = time.perf_counter()
            result = self.llm_fn(
                self.prompt.system_instructions,
                self.prompt.template.format(input=input_red),
                context,
            )
            latency = (time.perf_counter() - t0) * 1000
            output_red, output_scan = pii_guard.redact(result.output, use_ner=False)
            verdicts = {
                "input_pii_entities": input_scan.entities,
                "output_pii_entities": output_scan.entities,
            }
            for guard in self.output_guards:
                verdicts.update(guard(result.output, retrieved))
            blocked = any(v is False for k, v in verdicts.items() if k.endswith("_ok"))
            self.conn.execute(
                "INSERT INTO genai.generation (request_id, model_version_id, prompt_version_id, parameters, input_redacted,"
                " output_redacted, output_sha256, guardrail_verdicts, tool_calls, tokens_in, tokens_out, latency_ms, generated_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    request_id,
                    self.model.id,
                    self.prompt.id,
                    json.dumps(parameters),
                    input_red,
                    output_red,
                    sha256(result.output),
                    json.dumps(verdicts),
                    json.dumps(result.tool_calls),
                    result.tokens_in,
                    result.tokens_out,
                    latency,
                    datetime.now(UTC),
                ),
            )
        return {
            "request_id": str(request_id),
            "trace_id": trace_id,
            "output": None if blocked else output_red,
            "blocked": blocked,
            "verdicts": verdicts,
        }


def record_override(
    conn,
    request_id: str,
    reviewer: str,
    action: str,
    original_output: str,
    reason: str,
    final_output: str | None = None,
) -> None:
    final_red = pii_guard.redact(final_output, use_ner=False)[0] if final_output else None
    conn.execute(
        "INSERT INTO genai.human_override (request_id, reviewer, action, original_sha256, final_redacted, final_sha256,"
        " reason, overridden_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            request_id,
            reviewer,
            action,
            sha256(original_output),
            final_red,
            sha256(final_output) if final_output else None,
            reason,
            datetime.now(UTC),
        ),
    )


def numbers_grounded_guard(output: str, retrieved: list[RetrievedItem]) -> dict:
    """Output guard: every number the model states must appear in retrieved/tool content (no invented amounts)."""
    import re

    nums = set(re.findall(r"\d+(?:[.,]\d+)?", output))
    source = " ".join(i.content for i in retrieved)
    missing = sorted(n for n in nums if n not in source)
    return {"numbers_grounded_ok": not missing, "ungrounded_numbers": missing}
