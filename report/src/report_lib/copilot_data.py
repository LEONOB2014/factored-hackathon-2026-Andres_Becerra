"""The copilot's stored evaluation results, as the copilot report's claims and figure scripts read them.

Every file lives under copilot/eval/reports/ (or copilot/eval/, copilot/corpus/) and is committed; the report never
re-runs an evaluation. Model runs are listed in one fixed order with short ids for claim names and labels for print.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from report_lib.paths import BUILD, COPILOT_REPORTS, REPO

COPILOT = REPO / "copilot"
EVAL = COPILOT / "eval"
OPEN = COPILOT_REPORTS / "open_models"
SCREENING = COPILOT_REPORTS / "screening"
DETAILS = COPILOT_REPORTS / "details"
CHALLENGE = COPILOT_REPORTS / "challenge.json"
CHALLENGE_AFTER = COPILOT_REPORTS / "challenge_after_fix.json"
INTENT = COPILOT_REPORTS / "intent_model.json"
KB = COPILOT_REPORTS / "kb_retrieval.json"
CASES = EVAL / "cases.yaml"
ATTACKS = EVAL / "attacks" / "attacks.json"
PARAMS = COPILOT / "corpus" / "intent_params.json"
POLICY = COPILOT / "src" / "copilot" / "policy.yaml"
CONFIG = COPILOT / "src" / "copilot" / "config.py"
SOURCES = BUILD / "sources"

# Figure palette: ink for text, a teal for the production configuration and for "inside BETA AID", a brick red for
# the raw model and the baseline it is compared with, a grey for references.
INK, LEARNED, RAW, MUTED = "#1f2a37", "#0f766e", "#b45309", "#9ca3af"


@dataclass(frozen=True)
class Run:
    key: str  # short id used in claim names
    file: str  # file name under open_models/
    label: str  # printed name
    model: str  # model family as printed in the model table
    where: str  # how it was served


RUNS = (
    Run("qwen30-tf", "Qwen_Qwen3-30B-A3B-Instruct-2507__tokenfactory.json", "Qwen3-30B-A3B, Token Factory",
        "Qwen3-30B-A3B-Instruct-2507", "hosted (Nebius Token Factory)"),
    Run("qwen30-fl", "Qwen_Qwen3-30B-A3B-Instruct-2507__featherless.json", "Qwen3-30B-A3B, Featherless",
        "Qwen3-30B-A3B-Instruct-2507", "hosted (Featherless)"),
    Run("gemma27-tf", "google_gemma-3-27b-it__tokenfactory.json", "Gemma-3-27B, Token Factory",
        "Gemma-3-27B-it", "hosted (Nebius Token Factory)"),
    Run("gpt4omini", "blaxel_sandbox-openai.json", "GPT-4o-mini, gateway", "GPT-4o-mini",
        "hosted (OpenAI-compatible gateway)"),
    Run("nemotron4b", "nemotron-mini.json", "Nemotron-Mini 4B, local", "Nemotron-Mini 4B", "local (Ollama, laptop)"),
    Run("qwen3b", "qwen2.5_3b.json", "Qwen2.5 3B, local", "Qwen2.5 3B", "local (Ollama, laptop)"),
)  # fmt: skip
ATTACK_KINDS = ("secret_extraction", "prompt_injection", "pii_echo_and_unconfirmed_action")
# printed names: the kind with spaces, except the probes of card numbers and of claimed actions
KIND_LABEL = {k: k.replace("_", " ") for k in ATTACK_KINDS} | {
    "pii_echo_and_unconfirmed_action": "card number and action claims"
}


def load(path: Path):
    return json.loads(path.read_text())


def run(r: Run) -> dict:
    return load(OPEN / r.file)


def cases() -> list[dict]:
    return yaml.safe_load(CASES.read_text())["cases"]


def challenge_pass(path: Path, variant: str) -> dict[str, bool]:
    """Case id -> passed, for one variant of a challenge report."""
    return {r["id"]: bool(r["pass"]) for r in load(path)["variants"][variant]["rows"]}


def model_challenge_pass(r: Run) -> dict[str, bool]:
    """Case id -> passed for a model run inside BETA AID: the run stores its failed case ids."""
    failed = set(run(r)["challenge"]["fails"]) if isinstance(run(r)["challenge"]["fails"][0], str) else {
        f["id"] for f in run(r)["challenge"]["fails"]}  # fmt: skip
    return {c["id"]: c["id"] not in failed for c in cases()}


def screening() -> list[dict]:
    return [load(p) for p in sorted(SCREENING.glob("*.json"))]


def out(name: str) -> Path:
    SOURCES.mkdir(parents=True, exist_ok=True)
    return SOURCES / name
