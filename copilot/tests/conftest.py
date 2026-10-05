"""A synthetic snapshot (no dataset rows) with one customer per situation the tests need."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from copilot.audit import AuditLog
from copilot.config import Settings
from copilot.engine import Engine
from copilot.intent import IntentModel
from copilot.tools import COLUMNS, Tools

AS_OF = date(2026, 5, 17)


def card(
    pid,
    cid,
    ptype="Tarjeta Crédito",
    status="Active",
    days=400,
    nba="NONE",
    fraud=0,
    dnh=0,
    expired_d=0,
    last4="0000",
):
    exp = AS_OF + timedelta(days=days)
    return {
        "product_id": pid, "customer_id": cid, "country_code": "MX", "product_type": ptype,
        "product_status": status, "is_blocked": status == "Blocked", "expiration_date": exp,
        "days_to_expiry": days, "is_active_but_expired": status == "Active" and days < 0,
        "credit_limit": 5000.0 if "Cr" in ptype else None, "current_balance": 1234.5 if "Cr" in ptype else None,
        "utilization": 0.2469 if "Cr" in ptype else None, "current_decline_streak": 0,
        "declines_do_not_honor_30d": dnh, "declines_invalid_card_30d": 0, "declines_insufficient_funds_30d": 0,
        "declines_expired_30d": expired_d, "foreign_tx_90d": 0, "foreign_countries_90d": None, "open_cases": 0,
        "contacts_30d": 0, "next_best_action": nba, "confirmed_fraud_365d": fraud, "card_last4": last4,
        "currency": "MXN", "as_of_ts": f"{AS_OF} 23:59:59",
    }  # fmt: skip


CARDS = [
    card("P-1", "C-SINGLE", last4="1111"),
    card("P-2", "C-MULTI", last4="2222"),
    card("P-3", "C-MULTI", ptype="Tarjeta Débito", last4="3333"),
    card("P-4", "C-MULTI", last4="4444"),
    card("P-5", "C-BLOCKED", status="Blocked", nba="UNBLOCK_AFTER_STRONG_AUTH", last4="5555"),
    card("P-6", "C-FRAUD", nba="FRAUD_REVIEW_AND_BLOCK", fraud=1, last4="6666"),
    card("P-7", "C-CLOSED", status="Closed", last4="7777"),
    card("P-8", "C-EXPIRED", days=-30, nba="REISSUE_CARD", expired_d=2, last4="8888"),
    card("P-9", "C-RISK", dnh=4, last4="9999"),
]


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "snapshot.duckdb"
    con = duckdb.connect(str(path))
    cols = ", ".join(
        f"{c} {'DATE' if c == 'expiration_date' else 'BOOLEAN' if c.startswith('is_') else 'DOUBLE' if c in ('credit_limit', 'current_balance', 'utilization') else 'BIGINT' if c in ('days_to_expiry',) or c.endswith(('_30d', '_90d', '_365d', 'streak', 'cases')) and c != 'foreign_countries_90d' else 'VARCHAR'}"
        for c in COLUMNS
    )  # noqa: E501
    con.sql(f"create table cards ({cols}, stratum varchar)")
    for c in CARDS:
        con.execute(
            f"insert into cards values ({', '.join('?' for _ in COLUMNS)}, 'test')",
            [c[k] for k in COLUMNS],
        )
    con.close()
    return path


@pytest.fixture
def settings(tmp_path: Path, snapshot: Path) -> Settings:
    return replace(
        Settings(),
        snapshot=snapshot,
        store=tmp_path / "ops.sqlite",
        audit_log=tmp_path / "audit.jsonl",
        secret=b"test-key",
        use_llm=False,
    )


@pytest.fixture(scope="session")
def intent_model() -> IntentModel:
    return IntentModel()


@pytest.fixture
def tools(settings: Settings) -> Tools:
    return Tools(settings.snapshot, settings.store, settings.secret, settings.confirm_ttl_s)


@pytest.fixture
def engine(settings: Settings, tools: Tools, intent_model: IntentModel) -> Engine:
    return Engine(settings, tools, intent=intent_model, audit=AuditLog(settings.audit_log))
