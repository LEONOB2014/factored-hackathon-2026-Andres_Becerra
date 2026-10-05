"""The policy engine: it agrees with the recommended intent or vetoes it. Rules live in policy.yaml, versioned.

Conditions are named predicates over the card, never expressions evaluated from the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from copilot.tools import Card

POLICY_FILE = Path(__file__).with_name("policy.yaml")

CONDITIONS = {
    "card_fraud_flag": lambda c: c.next_best_action == "FRAUD_REVIEW_AND_BLOCK",
    "confirmed_fraud": lambda c: c.confirmed_fraud_365d > 0,
    "card_closed": lambda c: c.status == "Closed",
    "card_suspended": lambda c: c.status == "Suspended",
    "card_blocked": lambda c: c.status == "Blocked",
    "card_not_blocked": lambda c: c.status != "Blocked",
    "reissue_requested": lambda c: c.reissue_requested,
    "card_expired": lambda c: (
        (c.days_to_expiry is not None and c.days_to_expiry < 0) or c.is_active_but_expired
    ),
    "risk_declines": lambda c: c.declines_do_not_honor_30d >= 3,
}


@dataclass(frozen=True)
class Decision:
    kind: str  # answer | confirm | handoff | clarify
    rule: str
    autonomy: str
    template: str | None = None
    action: str | None = None
    step_up: bool = False
    queue: str | None = None
    priority: str = "normal"


class Policy:
    def __init__(self, path: Path = POLICY_FILE):
        spec = yaml.safe_load(path.read_text())
        self.version: str = spec["version"]
        self.intents: dict[str, dict] = spec["intents"]
        self.vetoes: list[dict] = spec["vetoes"]
        unknown = {v["when"] for v in self.vetoes} - CONDITIONS.keys()
        if unknown:
            raise ValueError(f"policy names unknown conditions: {sorted(unknown)}")

    def needs_card(self, intent: str) -> bool:
        return bool(self.intents.get(intent, {}).get("needs_card"))

    def decide(self, intent: str, card: Card | None, misses: int = 0) -> Decision:
        spec = self.intents.get(intent)
        if spec is None:
            return Decision("clarify", "P00_unknown_intent", "A0", template="clarify")
        level = spec["autonomy"]
        if intent == "out_of_scope":
            if misses + 1 >= spec.get("escalate_after", 2):
                return Decision("handoff", "P01_repeated_out_of_scope", "A3", queue=spec["queue"])
            return Decision("answer", "P02_out_of_scope", "A0", template="out_of_scope")
        if card is not None:
            for v in self.vetoes:
                if v.get("intents") and intent not in v["intents"]:
                    continue
                if intent in v.get("except_intents", ()):
                    continue
                if CONDITIONS[v["when"]](card):
                    then = v["then"]
                    if "handoff" in then:
                        return Decision(
                            "handoff",
                            v["id"],
                            "A3",
                            queue=then["handoff"],
                            priority=then.get("priority", "normal"),
                        )
                    return Decision("answer", v["id"], level, template=then["answer"])
        if level == "A3":
            return Decision(
                "handoff",
                f"P10_{intent}",
                "A3",
                queue=spec["queue"],
                priority=spec.get("priority", "normal"),
            )
        if level == "A2":
            return Decision(
                "confirm",
                f"P20_{intent}",
                "A2",
                action=spec["action"],
                step_up=bool(spec.get("step_up")),
            )
        return Decision("answer", f"P30_{intent}", "A0", template=intent)
