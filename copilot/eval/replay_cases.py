"""Replay chosen cases of the frozen challenge set with a model inside BETA AID, keeping each turn's trace.

The model runs of eval/open_models.py store only the ids of failed cases. This replays a few of them through the
same harness and stores, per turn, the outcome, the policy rule, the intent and its source, the grounding verdict and
any model error, so a failure can be traced to the stage that produced it. Same engine, settings and knowledge base
as the model runs; the hosted endpoint comes from COPILOT_LLM_BASE_URL and COPILOT_LLM_API_KEY (never written).

    cd copilot && set -a && . ~/.config/beta-aid/tokenfactory.env && set +a && COPILOT_LLM_BACKEND=openai \
      COPILOT_LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1 uv run python eval/replay_cases.py \
      --model Qwen/Qwen3-30B-A3B-Instruct-2507 --provider tokenfactory --cases N01,N02,N03,N04
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "reports" / "details"
TRACE_KEYS = (
    "policy_rule",
    "intent",
    "intent_source",
    "grounding",
    "llm_error",
    "kb_error",
    "llm_calls",
)


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def replay(h, case: dict) -> dict:
    e = h.engine(case["id"])
    token = e.login(h.roles[case["role"]]["customer_id"], h.s.otp_fixture)
    turns = []
    for t in case["turns"]:
        r = e.message(token, h.fill(t, e, token)) if isinstance(t, str) else None
        if r is None:
            continue
        turns.append({"input": t, "outcome": r.outcome, "reply": r.text[:300],
                      "handoff_queue": (r.handoff or {}).get("queue"),
                      **{k: r.trace.get(k) for k in TRACE_KEYS if r.trace.get(k) is not None}})  # fmt: skip
    return {"id": case["id"], "expect": case["expect"], "turns": turns}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--cases", required=True, help="comma-separated case ids")
    a = ap.parse_args()
    run, om = load("run"), load("open_models")
    h, _ = om.wrapped_harness(run, a.model)
    want = a.cases.split(",")
    cases = [c for c in run.yaml.safe_load(run.CASES.read_text())["cases"] if c["id"] in want]
    rows = [replay(h, c) for c in cases]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"replay_{a.provider}__{re.sub(r'[^A-Za-z0-9.-]+', '_', a.model)}.json"
    path.write_text(json.dumps({"model": a.model, "provider": a.provider,
                                "at": datetime.now(UTC).isoformat(timespec="seconds"), "cases": rows},
                               indent=1, ensure_ascii=False) + "\n")  # fmt: skip
    for r in rows:
        last = r["turns"][-1]
        print(r["id"], r["expect"], "->", last["outcome"], last.get("policy_rule"), last.get("grounding"),
              last.get("llm_error"))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
