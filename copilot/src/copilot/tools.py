"""The tools: read card facts, and perform card actions only through a confirmed, verified two-step flow.

Reads come from a read-only DuckDB snapshot of ``serving.serving_card_support``; every read is filtered by the
customer of the verified session, here, not in a prompt. Writes go to a separate SQLite operational store:

1. ``prepare`` returns a confirmation token (HMAC over action, customer, card, expiry and a nonce);
2. ``execute`` checks the token, its expiry, that it belongs to this session's customer, that it was not used before
   (the nonce is the idempotency key), and the step-up when the action needs it; then it writes;
3. ``read_back`` reads the effective state again, and only a matching read-back lets the copilot say it is done.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb

from copilot.identity import AuthError, Session, sign, verify

COLUMNS = (
    "product_id", "customer_id", "country_code", "product_type", "product_status", "is_blocked",
    "expiration_date", "days_to_expiry", "is_active_but_expired", "credit_limit", "current_balance",
    "utilization", "current_decline_streak", "declines_do_not_honor_30d", "declines_invalid_card_30d",
    "declines_insufficient_funds_30d", "declines_expired_30d", "foreign_tx_90d", "foreign_countries_90d",
    "open_cases", "contacts_30d", "next_best_action", "confirmed_fraud_365d", "card_last4", "currency", "as_of_ts",
)  # fmt: skip

ACTIONS = {"block": "Blocked", "unblock": "Active", "reissue": None}
NEEDS_STEPUP = {"unblock"}


def money(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Card:
    product_id: str
    customer_id: str
    country_code: str
    kind: str  # "credit" | "debit"
    status: str  # Active | Blocked | Closed | Suspended (after any confirmed action)
    is_blocked: bool
    expiration_date: date | None
    days_to_expiry: int | None
    is_active_but_expired: bool
    credit_limit: Decimal | None
    current_balance: Decimal | None
    utilization: float | None
    current_decline_streak: int
    declines_do_not_honor_30d: int
    declines_invalid_card_30d: int
    declines_insufficient_funds_30d: int
    declines_expired_30d: int
    foreign_tx_90d: int
    foreign_countries_90d: str | None
    open_cases: int
    contacts_30d: int
    next_best_action: str
    confirmed_fraud_365d: int
    last4: str
    currency: str
    as_of: str
    reissue_requested: bool = False

    @property
    def available(self) -> Decimal | None:
        if self.credit_limit is None or self.current_balance is None:
            return None
        return max(self.credit_limit - self.current_balance, Decimal("0.00"))

    def facts(self) -> dict:
        d = asdict(self)
        d["available"] = self.available
        return d


class ToolError(Exception):
    """A tool failed (store down, snapshot unreadable): the copilot must not claim any outcome."""


class Tools:
    def __init__(self, snapshot: Path, store: Path, key: bytes, confirm_ttl_s: int = 300):
        self.snapshot_path, self.key, self.confirm_ttl_s = snapshot, key, confirm_ttl_s
        self._db = duckdb.connect(str(snapshot), read_only=True)
        self._lock = threading.Lock()
        store.parent.mkdir(parents=True, exist_ok=True)
        self._store = sqlite3.connect(str(store), check_same_thread=False, isolation_level=None)
        self._store.executescript("""
            create table if not exists card_overrides(
                product_id text primary key, status text not null, action_id text not null, updated_at text not null);
            create table if not exists reissue_requests(
                product_id text primary key, action_id text not null, created_at text not null);
            create table if not exists actions(
                action_id text primary key, nonce text unique not null, action text not null, customer_id text not null,
                product_id text not null, created_at text not null);
        """)
        self.fail_next: str | None = None  # fault injection for the evaluation ("read" | "write")

    # --- reads ---------------------------------------------------------------------------------------------------
    def known_customer(self, customer_id: str) -> bool:
        with self._lock:
            return bool(
                self._db.execute(
                    "select 1 from cards where customer_id = ? limit 1", [customer_id]
                ).fetchone()
            )

    def cards(self, session: Session) -> list[Card]:
        """Every card of the session's customer, with confirmed actions applied."""
        if self.fail_next == "read":
            self.fail_next = None
            raise ToolError("snapshot read failed")
        with self._lock:
            rows = self._db.execute(
                f"select {', '.join(COLUMNS)} from cards where customer_id = ? order by product_type, product_id",
                [session.customer_id],
            ).fetchall()
        out = []
        for r in rows:
            d = dict(zip(COLUMNS, r, strict=True))
            ov = self._store.execute(
                "select status from card_overrides where product_id = ?", [d["product_id"]]
            ).fetchone()
            status = ov[0] if ov else d["product_status"]
            reissued = bool(
                self._store.execute(
                    "select 1 from reissue_requests where product_id = ?", [d["product_id"]]
                ).fetchone()
            )
            out.append(
                Card(
                    product_id=d["product_id"],
                    customer_id=d["customer_id"],
                    country_code=d["country_code"],
                    kind="credit" if "Cr" in (d["product_type"] or "") else "debit",
                    status=status,
                    is_blocked=status == "Blocked",
                    expiration_date=d["expiration_date"].date()
                    if isinstance(d["expiration_date"], datetime)
                    else d["expiration_date"],
                    days_to_expiry=d["days_to_expiry"],
                    is_active_but_expired=bool(d["is_active_but_expired"]),
                    credit_limit=money(d["credit_limit"]),
                    current_balance=money(d["current_balance"]),
                    utilization=d["utilization"],
                    current_decline_streak=int(d["current_decline_streak"] or 0),
                    declines_do_not_honor_30d=int(d["declines_do_not_honor_30d"] or 0),
                    declines_invalid_card_30d=int(d["declines_invalid_card_30d"] or 0),
                    declines_insufficient_funds_30d=int(d["declines_insufficient_funds_30d"] or 0),
                    declines_expired_30d=int(d["declines_expired_30d"] or 0),
                    foreign_tx_90d=int(d["foreign_tx_90d"] or 0),
                    foreign_countries_90d=d["foreign_countries_90d"],
                    open_cases=int(d["open_cases"] or 0),
                    contacts_30d=int(d["contacts_30d"] or 0),
                    next_best_action=d["next_best_action"] or "NONE",
                    confirmed_fraud_365d=int(d["confirmed_fraud_365d"] or 0),
                    last4=d["card_last4"],
                    currency=d["currency"],
                    as_of=str(d["as_of_ts"])[:10],
                    reissue_requested=reissued,
                )
            )
        return out

    def card(self, session: Session, product_id: str) -> Card | None:
        return next((c for c in self.cards(session) if c.product_id == product_id), None)

    # --- writes --------------------------------------------------------------------------------------------------
    def prepare(self, session: Session, action: str, product_id: str) -> str:
        if action not in ACTIONS:
            raise ValueError(action)
        if self.card(session, product_id) is None:  # ownership: only the session's own cards
            raise AuthError("not_owner")
        return sign(
            {
                "act": action,
                "cid": session.customer_id,
                "sid": session.session_id,
                "pid": product_id,
                "nonce": secrets.token_hex(8),
                "exp": time.time() + self.confirm_ttl_s,
            },
            self.key,
        )

    def execute(self, session: Session, token: str) -> dict:
        p = verify(token, self.key)
        if p["cid"] != session.customer_id or p["sid"] != session.session_id:
            raise AuthError("not_owner")
        if p["act"] in NEEDS_STEPUP and not session.stepped_up:
            raise AuthError("stepup_required")
        if self.fail_next == "write":
            self.fail_next = None
            raise ToolError("operational store unavailable")
        now = datetime.now(UTC).isoformat()
        action_id = "ACT-" + secrets.token_hex(6).upper()
        try:
            self._store.execute("begin")
            self._store.execute(
                "insert into actions values (?, ?, ?, ?, ?, ?)",
                [action_id, p["nonce"], p["act"], p["cid"], p["pid"], now],
            )
            if p["act"] == "reissue":
                self._store.execute(
                    "insert or replace into reissue_requests values (?, ?, ?)",
                    [p["pid"], action_id, now],
                )
            else:
                self._store.execute(
                    "insert or replace into card_overrides values (?, ?, ?, ?)",
                    [p["pid"], ACTIONS[p["act"]], action_id, now],
                )
            self._store.execute("commit")
        except (
            sqlite3.IntegrityError
        ):  # the nonce was used: an idempotent replay, nothing is written twice
            self._store.execute("rollback")
            prior = self._store.execute(
                "select action_id from actions where nonce = ?", [p["nonce"]]
            ).fetchone()
            return {
                "action_id": prior[0],
                "action": p["act"],
                "product_id": p["pid"],
                "replayed": True,
            }
        return {
            "action_id": action_id,
            "action": p["act"],
            "product_id": p["pid"],
            "replayed": False,
        }

    def read_back(self, session: Session, result: dict) -> bool:
        card = self.card(session, result["product_id"])
        if card is None:
            return False
        if result["action"] == "reissue":
            return card.reissue_requested
        return card.status == ACTIONS[result["action"]]

    @staticmethod
    def token_claims(token: str, key: bytes) -> dict:
        return verify(token, key)
