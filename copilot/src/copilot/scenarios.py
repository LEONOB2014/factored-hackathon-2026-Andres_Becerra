"""Demo scenarios: which snapshot customer plays each role, chosen by rule so the evaluation set never names a
customer and the UI offers one sign-in per situation. This reads the snapshot directly because it is the test
identity directory (customer id and role only); card facts are only ever read through the session-scoped tools."""

from __future__ import annotations

from pathlib import Path

import duckdb

# role -> (label es, label pt, rule over one customer's cards)
SCENARIOS: dict[str, tuple[str, str, str]] = {
    "single_active": (
        "Una tarjeta activa, sin alertas",
        "Um cartão ativo, sem alertas",
        "count(*) = 1 and bool_and(product_status = 'Active' and next_best_action = 'NONE')",
    ),
    "multi_card": (
        "Varias tarjetas (crédito y débito)",
        "Vários cartões (crédito e débito)",
        "count(*) >= 3 and count(distinct product_type) = 2 and bool_and(product_status = 'Active') "
        "and bool_and(next_best_action <> 'FRAUD_REVIEW_AND_BLOCK')",
    ),
    "blocked": (
        "Tarjeta bloqueada, desbloqueable",
        "Cartão bloqueado, desbloqueável",
        "count(*) = 1 and bool_and(product_status = 'Blocked' and confirmed_fraud_365d = 0 "
        "and declines_do_not_honor_30d < 3 and days_to_expiry > 30)",
    ),
    "reissue": (
        "Tarjeta vencida o con rechazos por vencimiento",
        "Cartão vencido ou com recusas por vencimento",
        "count(*) = 1 and bool_and(next_best_action = 'REISSUE_CARD' and product_status = 'Active')",
    ),
    "renewal": (
        "Tarjeta próxima a vencer",
        "Cartão perto de vencer",
        "count(*) = 1 and bool_and(next_best_action = 'PROACTIVE_RENEWAL' and product_status = 'Active')",
    ),
    "high_utilization": (
        "Cupo casi agotado",
        "Limite quase esgotado",
        "count(*) = 1 and bool_and(next_best_action = 'EXPLAIN_LIMIT_OR_OFFER_INCREASE_REVIEW' "
        "and product_status = 'Active')",
    ),
    "fraud_flag": (
        "Tarjeta con alerta de fraude",
        "Cartão com alerta de fraude",
        "count(*) = 1 and bool_and(next_best_action = 'FRAUD_REVIEW_AND_BLOCK')",
    ),
    "closed": (
        "Tarjeta cancelada",
        "Cartão cancelado",
        "count(*) = 1 and bool_and(product_status = 'Closed')",
    ),
}


def resolve(snapshot: Path) -> dict[str, dict]:
    con = duckdb.connect(str(snapshot), read_only=True)
    out = {}
    for role, (es, pt, rule) in SCENARIOS.items():
        row = con.execute(
            f"select customer_id, count(*) from cards group by customer_id having {rule} order by customer_id limit 1"
        ).fetchone()
        if row:
            out[role] = {
                "role": role,
                "customer_id": row[0],
                "cards": row[1],
                "label_es": es,
                "label_pt": pt,
            }
    con.close()
    return out
