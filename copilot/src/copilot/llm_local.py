"""A local open-weight model (served by Ollama) in the language model's two bounded jobs, for evaluation.

Same contract as `copilot.llm.LLM`: classify an intent the fast model is unsure of, rephrase a template reply, answer
from cited passages. Same prompts, same grounding checks in the engine, same circuit breaker. Every call is streamed so
the time to first token is measured. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import time
import urllib.request

from copilot.llm import (
    ANSWER_SYSTEM,
    CLASSIFY_SYSTEM,
    INTENT_DESCRIPTIONS,
    REPHRASE_SYSTEM,
    Breaker,
    Usage,
)

OLLAMA = "http://127.0.0.1:11434"


def chat(
    model: str,
    system: str,
    user: str,
    *,
    fmt: dict | None = None,
    max_tokens: int = 300,
    timeout_s: float = 60.0,
) -> tuple[str, dict]:
    """One streamed chat call. Returns the text and timings: ttft_ms, total_ms, tokens in and out."""
    body = {
        "model": model,
        "stream": True,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    if fmt is not None:
        body["format"] = fmt
    req = urllib.request.Request(  # noqa: S310 (fixed local http URL)
        f"{OLLAMA}/api/chat",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )
    t0, ttft, parts, last = time.perf_counter(), None, [], {}
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (local server)
        for line in resp:
            if not line.strip():
                continue
            chunk = json.loads(line)
            piece = chunk.get("message", {}).get("content", "")
            if piece and ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            parts.append(piece)
            last = chunk
    total = (time.perf_counter() - t0) * 1000
    return "".join(parts), {
        "ttft_ms": ttft if ttft is not None else total,
        "total_ms": total,
        "tokens_in": last.get("prompt_eval_count", 0),
        "tokens_out": last.get("eval_count", 0),
    }


class LocalLLM:
    """Drop-in for `copilot.llm.LLM`, backed by a local model; records every call's timings."""

    def __init__(self, model: str, timeout_s: float = 60.0):
        self.model, self.timeout_s = model, timeout_s
        self.breaker = Breaker()
        self.calls: list[dict] = []

    def _call(self, job: str, system: str, user: str, **kw) -> tuple[str, Usage]:
        self.breaker.check()
        try:
            text, t = chat(self.model, system, user, timeout_s=self.timeout_s, **kw)
        except OSError:
            self.breaker.fail()
            raise
        self.breaker.ok()
        self.calls.append({"job": job, **t})
        return text, Usage(self.model, t["tokens_in"], t["tokens_out"], 1, t["total_ms"])

    def classify(self, text: str) -> tuple[str, Usage]:
        schema = {
            "type": "object",
            "properties": {"intent": {"type": "string", "enum": list(INTENT_DESCRIPTIONS)}},
            "required": ["intent"],
        }
        raw, u = self._call(
            "classify", CLASSIFY_SYSTEM, f"<message>{text}</message>", fmt=schema, max_tokens=64
        )
        try:
            intent = json.loads(raw).get("intent", "out_of_scope")
        except ValueError:
            intent = "out_of_scope"
        return (intent if intent in INTENT_DESCRIPTIONS else "out_of_scope"), u

    def rephrase(self, reply: str, lang: str) -> tuple[str, Usage]:
        system = REPHRASE_SYSTEM.format(
            lang_name="Spanish" if lang == "es" else "Brazilian Portuguese"
        )
        text, u = self._call("rephrase", system, reply)
        return (text.strip() or reply), u

    def answer(self, question: str, passages: list[dict], lang: str) -> tuple[str | None, Usage]:
        docs = "\n\n".join(
            f'<passage cite="{p["cite"]}" title="{p["title"]}">\n{p["content"]}\n</passage>'
            for p in passages
        )
        system = ANSWER_SYSTEM.format(
            lang_name="Spanish" if lang == "es" else "Brazilian Portuguese"
        )
        text, u = self._call(
            "answer", system, f"{docs}\n\n<question>{question}</question>", max_tokens=400
        )
        text = text.strip()
        if not text or "NO_ANSWER" in text:
            return None, u
        return text, u
