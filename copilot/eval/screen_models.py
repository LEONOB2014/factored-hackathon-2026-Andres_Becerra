"""Speed screening of hosted models in the copilot's most frequent model job: labelling a message the fast intent
model is unsure of.

For each model it sends one warm-up call and then `--n` timed calls, cycling through five informal customer messages,
with the same system prompt, JSON format and token budget the copilot uses. Every call is stored: time to first token,
total time, tokens, whether the reply is valid JSON with a known intent, and the error if the call failed (a model the
provider does not serve, or serves only behind a gate, is stored with its HTTP status). The API key comes from the
environment and is never written.

    cd copilot && set -a && . ~/.config/beta-aid/tokenfactory.env && set +a && uv run python eval/screen_models.py \
        --provider tokenfactory --base-url https://api.tokenfactory.nebius.com/v1 \
        --models Qwen/Qwen3-30B-A3B-Instruct-2507,google/gemma-3-27b-it
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from copilot.llm import CLASSIFY_SYSTEM, INTENT_DESCRIPTIONS
from copilot.llm_local import chat_openai

OUT = Path(__file__).resolve().parent / "reports" / "screening"
TIMEOUT_S = (
    30.0  # well past the copilot's own model timeout, so slow tails are measured instead of cut
)
MESSAGES = [
    ("es", "oye y lo del plástico ese que no me llegó"),
    ("pt", "quero saber quanto devo no cartão"),
    ("es", "¿me pueden subir el cupo?"),
    ("pt", "não reconheço essa compra"),
    ("es", "mi tarjeta no pasa en el súper"),
]

Send = Callable[[str, str], tuple[str, dict]]


def judge(text: str) -> tuple[bool, bool]:
    """(valid JSON object, known intent label)."""
    try:
        obj = json.loads(text)
    except ValueError:
        return False, False
    return isinstance(obj, dict), isinstance(obj, dict) and obj.get("intent") in INTENT_DESCRIPTIONS


def one(send: Send, model: str, i: int) -> dict:
    lang, msg = MESSAGES[i % len(MESSAGES)]
    row: dict = {"i": i, "lang": lang, "message": msg}
    try:
        text, t = send(model, f"<message>{msg}</message>")
    except urllib.error.HTTPError as e:
        return {**row, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 - a failed call is a result
        return {**row, "error": type(e).__name__}
    valid_json, valid_label = judge(text)
    return {**row, **{k: round(v, 1) if isinstance(v, float) else v for k, v in t.items()},
            "valid_json": valid_json, "valid_label": valid_label}  # fmt: skip


def screen(send: Send, provider: str, model: str, n: int) -> dict:
    warmup = one(send, model, 0)
    calls = [one(send, model, i) for i in range(n)] if "error" not in warmup else []
    return {"provider": provider, "model": model, "n": n, "timeout_s": TIMEOUT_S,
            "at": datetime.now(UTC).isoformat(timespec="seconds"), "warmup": warmup, "calls": calls}  # fmt: skip


def slug(provider: str, model: str) -> str:
    return f"{provider}__{re.sub(r'[^A-Za-z0-9.-]+', '_', model)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--provider", required=True, help="label stored with the results, e.g. tokenfactory"
    )
    ap.add_argument("--base-url", required=True, help="OpenAI-compatible base URL ending in /v1")
    ap.add_argument("--models", required=True, help="comma-separated model ids")
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    key = os.environ.get("COPILOT_LLM_API_KEY")
    if not key:
        sys.exit("COPILOT_LLM_API_KEY is not set")
    url = a.base_url.rstrip("/") + "/chat/completions"

    def send(model: str, user: str) -> tuple[str, dict]:
        return chat_openai(url, key, model, CLASSIFY_SYSTEM, user, fmt={"type": "object"}, max_tokens=64,
                           timeout_s=TIMEOUT_S)  # fmt: skip

    OUT.mkdir(parents=True, exist_ok=True)
    for model in a.models.split(","):
        r = screen(send, a.provider, model, a.n)
        (OUT / f"{slug(a.provider, model)}.json").write_text(
            json.dumps(r, indent=1, ensure_ascii=False) + "\n"
        )
        ok = [c for c in r["calls"] if "error" not in c]
        print(
            f"{a.provider} {model}: warm-up {r['warmup'].get('error') or 'ok'}, {len(ok)}/{len(r['calls'])} calls ok"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
