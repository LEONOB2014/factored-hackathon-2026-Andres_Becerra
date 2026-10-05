"""Runtime settings, from the environment (the root .env is read when present, never printed)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
PROJECT = PACKAGE.parents[1]  # copilot/
REPO = PROJECT.parent


def _load_dotenv(path: Path) -> None:
    """Fill unset variables from a KEY=VALUE file (the repository's git-ignored .env)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


_load_dotenv(REPO / ".env")


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    snapshot: Path = Path(
        os.environ.get("COPILOT_SNAPSHOT", REPO / "data" / "copilot" / "snapshot.duckdb")
    )
    store: Path = Path(
        os.environ.get("COPILOT_STORE", REPO / "data" / "copilot" / "operations.sqlite")
    )
    audit_log: Path = Path(
        os.environ.get("COPILOT_AUDIT", REPO / "data" / "copilot" / "audit.jsonl")
    )
    # HMAC key for session and confirmation tokens; a fresh random key per process when unset
    secret: bytes = field(
        default_factory=lambda: (os.environ.get("COPILOT_SECRET") or secrets.token_hex(32)).encode()
    )
    session_ttl_s: int = int(os.environ.get("COPILOT_SESSION_TTL", "900"))
    confirm_ttl_s: int = int(os.environ.get("COPILOT_CONFIRM_TTL", "300"))
    stepup_ttl_s: int = int(os.environ.get("COPILOT_STEPUP_TTL", "300"))
    # test identity fixtures: demo customers sign in with these one-time codes (test mode only)
    otp_fixture: str = os.environ.get("COPILOT_TEST_OTP", "246810")
    stepup_fixture: str = os.environ.get("COPILOT_TEST_STEPUP", "135790")
    use_llm: bool = _flag("COPILOT_USE_LLM", True)
    rephrase: bool = _flag("COPILOT_REPHRASE", True)
    llm_model: str = os.environ.get("COPILOT_LLM_MODEL", "claude-haiku-4-5")
    llm_timeout_s: float = float(os.environ.get("COPILOT_LLM_TIMEOUT", "6"))
    intent_threshold: float = float(os.environ.get("COPILOT_INTENT_THRESHOLD", "0.55"))

    @property
    def llm_available(self) -> bool:
        # a real key, not the .env.example placeholder
        return self.use_llm and os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-")
