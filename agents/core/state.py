"""
Agent State Definition
Factored AI & Data Hackathon 2026

Defines the TypedDict state schema that flows through the LangGraph agent graph.
All nodes read and write to this shared state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, TypedDict

# NOTE: these stay runtime imports — LangGraph resolves AgentStateDict's
# annotations at runtime via get_type_hints(include_extras=True) to discover
# the add_messages reducer, so a TYPE_CHECKING block would break graph build.
from langchain_core.messages import BaseMessage  # noqa: TCH002
from langgraph.graph.message import add_messages  # noqa: TCH002


class Language(str, Enum):
    """Supported languages for customer interactions."""

    ES_MX = "es-mx"  # Spanish (Mexico)
    ES_CO = "es-co"  # Spanish (Colombia)
    ES_AR = "es-ar"  # Spanish (Argentina)
    PT_BR = "pt-br"  # Portuguese (Brazil)
    ES = "es"  # Spanish (generic)


class Intent(str, Enum):
    """Customer intent categories."""

    TRANSACTION_DISPUTE = "transaction_dispute"
    CARD_SUPPORT = "card_support"
    ACCOUNT_INQUIRY = "account_inquiry"
    CREDIT_INFO = "credit_info"
    COMPLAINT = "complaint"
    GENERAL = "general"
    UNKNOWN = "unknown"


class EscalationReason(str, Enum):
    """Reasons for escalating to a human agent."""

    HIGH_VALUE_DISPUTE = "high_value_dispute"
    FRAUD_DETECTED = "fraud_detected"
    REGULATORY_COMPLAINT = "regulatory_complaint"
    CUSTOMER_REQUEST = "customer_request"
    POLICY_EDGE_CASE = "policy_edge_case"
    REPEATED_CLARIFICATION = "repeated_clarification"
    SYSTEM_ERROR = "system_error"
    UNAUTHORIZED_ACCESS = "unauthorized_access"


@dataclass
class ActionRecord:
    """Record of an action taken by the agent."""

    action_type: str
    tool_name: str
    input_params: dict[str, Any]
    output: Any
    success: bool
    timestamp: str
    verified: bool = False


@dataclass
class SafetyFlag:
    """Safety flag raised during processing."""

    flag_type: str  # 'pii_detected', 'injection_attempt', 'policy_violation'
    severity: str  # 'low', 'medium', 'high', 'critical'
    details: str
    action_taken: str


class AgentState:
    """
    Complete state for the AI banking agent.

    This TypedDict is passed through every node in the LangGraph graph.
    Nodes read what they need and write their outputs back.
    """

    # === Conversation ===
    messages: Annotated[list[BaseMessage], add_messages]

    # === Customer Identity ===
    customer_id: str | None
    session_id: str
    is_verified: bool
    verification_method: str | None

    # === Intent ===
    current_intent: Intent | None
    intent_confidence: float
    clarification_count: int

    # === Verified Facts ===
    verified_facts: dict[str, Any]  # Confirmed customer data from tools

    # === Actions ===
    actions_taken: list[ActionRecord]
    pending_confirmations: list[dict[str, Any]]

    # === Escalation ===
    escalation_required: bool
    escalation_reason: EscalationReason | None
    escalation_context: dict[str, Any] | None

    # === Language ===
    language: Language
    detected_accent: str | None

    # === Tool Results ===
    tool_results: list[dict[str, Any]]

    # === Safety ===
    safety_flags: list[SafetyFlag]
    is_blocked: bool

    # === Metadata ===
    turn_count: int
    total_tokens: int
    total_cost_usd: float


class AgentStateDict(TypedDict, total=False):
    """TypedDict version of AgentState for LangGraph graph definition."""

    messages: Annotated[list[BaseMessage], add_messages]
    customer_id: str | None
    session_id: str
    is_verified: bool
    verification_method: str | None
    current_intent: str | None
    intent_confidence: float
    clarification_count: int
    verified_facts: dict[str, Any]
    actions_taken: list[dict[str, Any]]
    pending_confirmations: list[dict[str, Any]]
    escalation_required: bool
    escalation_reason: str | None
    escalation_context: dict[str, Any] | None
    language: str
    detected_accent: str | None
    tool_results: list[dict[str, Any]]
    safety_flags: list[dict[str, Any]]
    is_blocked: bool
    turn_count: int
    total_tokens: int
    total_cost_usd: float
