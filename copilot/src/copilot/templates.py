"""Deterministic replies, Spanish and Portuguese. Every fact a reply states comes from a template filled with tool
facts; the language model may only rephrase the result, and the grounding check holds it to the same facts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from copilot.tools import Card

STATUS = {
    "es": {
        "Active": "activa",
        "Blocked": "bloqueada",
        "Closed": "cancelada",
        "Suspended": "suspendida",
    },
    "pt": {
        "Active": "ativo",
        "Blocked": "bloqueado",
        "Closed": "cancelado",
        "Suspended": "suspenso",
    },
}
KIND = {
    "es": {"credit": "crédito", "debit": "débito"},
    "pt": {"credit": "crédito", "debit": "débito"},
}

T: dict[str, dict[str, str]] = {
    "menu": {
        "es": "Puedo ayudarte con tus tarjetas: estado, saldo y cupo disponible, compras rechazadas, vencimiento, "
        "bloqueo, reposición y desbloqueo. ¿Qué necesitas?",
        "pt": "Posso ajudar com seus cartões: situação, saldo e limite disponível, compras recusadas, vencimento, "
        "bloqueio, segunda via e desbloqueio. Do que você precisa?",
    },
    "smalltalk": {
        "es": "Con gusto. Puedo ayudarte con el estado, saldo, vencimiento, bloqueo, reposición o desbloqueo de tus "
        "tarjetas. ¿Qué necesitas?",
        "pt": "Com prazer. Posso ajudar com situação, saldo, vencimento, bloqueio, segunda via ou desbloqueio dos seus "
        "cartões. Do que você precisa?",
    },
    "ask_card": {
        "es": "Tienes {n} tarjetas. ¿Sobre cuál me preguntas? {options}",
        "pt": "Você tem {n} cartões. Sobre qual deles? {options}",
    },
    "card_not_found": {
        "es": "No encuentro una tarjeta terminada en {last4} entre las tuyas. Solo puedo consultar las tarjetas de "
        "tu perfil.",
        "pt": "Não encontro um cartão final {last4} entre os seus. Só posso consultar os cartões do seu perfil.",
    },
    "no_cards": {
        "es": "No encuentro tarjetas activas en tu perfil.",
        "pt": "Não encontro cartões no seu perfil.",
    },
    "card_status": {
        "es": "Tu tarjeta de {kind} terminada en {last4} está {status}. Vence el {expiry}.",
        "pt": "Seu cartão de {kind} final {last4} está {status}. Vence em {expiry}.",
    },
    "card_status_noexp": {
        "es": "Tu tarjeta de {kind} terminada en {last4} está {status}. No tengo registrada su fecha de vencimiento.",
        "pt": "Seu cartão de {kind} final {last4} está {status}. Não tenho registrada a data de vencimento.",
    },
    "expiry_ok_noexp": {
        "es": "No tengo registrada la fecha de vencimiento de tu tarjeta terminada en {last4}. Si la necesitas, puedo "
        "pasarte con un asesor.",
        "pt": "Não tenho registrada a data de vencimento do seu cartão final {last4}. Se precisar, posso passar para um "
        "atendente.",
    },
    "balance_credit": {
        "es": "Tu tarjeta de crédito terminada en {last4} tiene un saldo de {balance} y un cupo de {limit}; "
        "disponible: {available}. Datos al {as_of}.",
        "pt": "Seu cartão de crédito final {last4} tem saldo de {balance} e limite de {limit}; disponível: "
        "{available}. Dados de {as_of}.",
    },
    "balance_missing": {
        "es": "Tu tarjeta de {kind} terminada en {last4} no tiene un cupo de crédito registrado; el saldo de una "
        "tarjeta de débito es el de su cuenta, que no puedo consultar aquí.",
        "pt": "Seu cartão de {kind} final {last4} não tem limite de crédito registrado; o saldo de um cartão de "
        "débito é o da conta, que não consigo consultar aqui.",
    },
    "decline_none": {
        "es": "No veo compras rechazadas en los últimos 30 días en tu tarjeta terminada en {last4}. Está {status}.",
        "pt": "Não vejo compras recusadas nos últimos 30 dias no seu cartão final {last4}. Está {status}.",
    },
    "decline_summary": {
        "es": "En los últimos 30 días tu tarjeta terminada en {last4} tuvo rechazos: {reasons}. {advice}",
        "pt": "Nos últimos 30 dias seu cartão final {last4} teve recusas: {reasons}. {advice}",
    },
    "expiry_ok": {
        "es": "Tu tarjeta terminada en {last4} vence el {expiry}, en {days} días.",
        "pt": "Seu cartão final {last4} vence em {expiry}, daqui a {days} dias.",
    },
    "expiry_soon": {
        "es": "Tu tarjeta terminada en {last4} vence el {expiry}, en {days} días. Si quieres, puedo solicitar la "
        "reposición.",
        "pt": "Seu cartão final {last4} vence em {expiry}, daqui a {days} dias. Se quiser, posso pedir a segunda via.",
    },
    "expired": {
        "es": "Tu tarjeta terminada en {last4} venció el {expiry}. Puedo solicitar la reposición si me lo pides.",
        "pt": "Seu cartão final {last4} venceu em {expiry}. Posso pedir a segunda via se você quiser.",
    },
    "confirm_block": {
        "es": "Voy a bloquear tu tarjeta de {kind} terminada en {last4}. No podrás usarla hasta desbloquearla. "
        "¿Confirmas?",
        "pt": "Vou bloquear seu cartão de {kind} final {last4}. Você não poderá usá-lo até desbloquear. Confirma?",
    },
    "confirm_reissue": {
        "es": "Voy a solicitar la reposición de tu tarjeta de {kind} terminada en {last4}. ¿Confirmas?",
        "pt": "Vou pedir a segunda via do seu cartão de {kind} final {last4}. Confirma?",
    },
    "confirm_unblock": {
        "es": "Voy a desbloquear tu tarjeta de {kind} terminada en {last4}. ¿Confirmas?",
        "pt": "Vou desbloquear seu cartão de {kind} final {last4}. Confirma?",
    },
    "stepup_needed": {
        "es": "Para desbloquear una tarjeta necesito verificar tu identidad con un segundo código. Ingresa el código "
        "que te enviamos.",
        "pt": "Para desbloquear um cartão preciso confirmar sua identidade com um segundo código. Digite o código que "
        "enviamos.",
    },
    "done_block": {
        "es": "Listo: tu tarjeta terminada en {last4} quedó bloqueada (operación {action_id}).",
        "pt": "Pronto: seu cartão final {last4} foi bloqueado (operação {action_id}).",
    },
    "done_unblock": {
        "es": "Listo: tu tarjeta terminada en {last4} quedó activa (operación {action_id}).",
        "pt": "Pronto: seu cartão final {last4} está ativo (operação {action_id}).",
    },
    "done_reissue": {
        "es": "Listo: solicitamos la reposición de tu tarjeta terminada en {last4} (operación {action_id}).",
        "pt": "Pronto: pedimos a segunda via do seu cartão final {last4} (operação {action_id}).",
    },
    "cancelled": {
        "es": "De acuerdo, no hice ningún cambio. ¿Te ayudo con algo más?",
        "pt": "Tudo bem, não fiz nenhuma alteração. Posso ajudar com mais alguma coisa?",
    },
    "nothing_pending": {
        "es": "No hay ninguna operación pendiente de confirmar. ¿Qué necesitas?",
        "pt": "Não há nenhuma operação pendente de confirmação. Do que você precisa?",
    },
    "confirm_expired": {
        "es": "La confirmación venció y no hice ningún cambio. Si aún lo necesitas, pídemelo de nuevo.",
        "pt": "A confirmação expirou e não fiz nenhuma alteração. Se ainda precisar, peça de novo.",
    },
    "already_blocked": {
        "es": "Tu tarjeta terminada en {last4} ya está bloqueada; no hice cambios.",
        "pt": "Seu cartão final {last4} já está bloqueado; não fiz alterações.",
    },
    "already_active": {
        "es": "Tu tarjeta terminada en {last4} no está bloqueada (está {status}); no hay nada que desbloquear.",
        "pt": "Seu cartão final {last4} não está bloqueado (está {status}); não há o que desbloquear.",
    },
    "already_reissued": {
        "es": "Ya hay una reposición solicitada para tu tarjeta terminada en {last4}; no la dupliqué.",
        "pt": "Já existe uma segunda via pedida para o seu cartão final {last4}; não dupliquei o pedido.",
    },
    "out_of_scope": {
        "es": "Eso no lo puedo resolver aquí: solo atiendo temas de tarjetas (estado, saldo, rechazos, vencimiento, "
        "bloqueo, reposición y desbloqueo). Si necesitas otra cosa, puedo pasarte con un asesor.",
        "pt": "Isso eu não consigo resolver aqui: só atendo assuntos de cartões (situação, saldo, recusas, "
        "vencimento, bloqueio, segunda via e desbloqueio). Se precisar de outra coisa, posso passar para um atendente.",
    },
    "clarify": {
        "es": "No estoy seguro de haber entendido. ¿Me lo dices de otra forma? Por ejemplo: «¿por qué rechazaron mi "
        "tarjeta?» o «quiero bloquear mi tarjeta».",
        "pt": "Não tenho certeza se entendi. Pode dizer de outro jeito? Por exemplo: «por que meu cartão foi "
        "recusado?» ou «quero bloquear meu cartão».",
    },
    "auth_required": {
        "es": "Para consultar tus tarjetas primero necesito verificar tu identidad. Inicia sesión con tu código.",
        "pt": "Para consultar seus cartões preciso primeiro verificar sua identidade. Entre com o seu código.",
    },
    "refused_injection": {
        "es": "No puedo seguir esa instrucción. Puedo ayudarte con tus tarjetas: estado, saldo, rechazos, "
        "vencimiento, bloqueo, reposición o desbloqueo.",
        "pt": "Não posso seguir essa instrução. Posso ajudar com seus cartões: situação, saldo, recusas, vencimento, "
        "bloqueio, segunda via ou desbloqueio.",
    },
    "deny_other_customer": {
        "es": "Solo puedo darte información de tus propias tarjetas. Por seguridad no consulto datos de otras "
        "personas.",
        "pt": "Só posso dar informações dos seus próprios cartões. Por segurança não consulto dados de outras "
        "pessoas.",
    },
    "tool_failure": {
        "es": "Tuve un problema técnico al consultar el sistema y no hice ningún cambio. Te paso con un asesor para "
        "que lo revise.",
        "pt": "Tive um problema técnico ao consultar o sistema e não fiz nenhuma alteração. Vou passar para um "
        "atendente revisar.",
    },
    "readback_failed": {
        "es": "No pude verificar que la operación quedara aplicada, así que no la doy por hecha. Te paso con un "
        "asesor.",
        "pt": "Não consegui verificar se a operação foi aplicada, então não a considero concluída. Vou passar para um "
        "atendente.",
    },
    "stepup_failed": {
        "es": "El segundo código no es correcto; no hice cambios.",
        "pt": "O segundo código não está correto; não fiz alterações.",
    },
    "kb_pointer": {
        "es": "Eso está descrito en nuestro documento público «{title}» ({cite}). Si quieres que alguien te lo "
        "explique en detalle, puedo pasarte con un asesor.",
        "pt": "Isso está descrito no nosso documento público «{title}» ({cite}). Se quiser que alguém explique em "
        "detalhe, posso passar para um atendente.",
    },
    "handoff": {
        "es": "{reason} Te paso con {queue}; ya le comparto el resumen para que no tengas que repetir nada.",
        "pt": "{reason} Vou passar para {queue}; já envio o resumo para você não precisar repetir nada.",
    },
}

QUEUE = {
    "es": {
        "fraud": "el equipo de fraude",
        "risk": "el equipo de riesgo",
        "credit_limits": "el equipo de cupos",
        "disputes": "el equipo de disputas",
        "complaints": "el equipo de reclamos",
        "general": "un asesor",
    },
    "pt": {
        "fraud": "a equipe de fraude",
        "risk": "a equipe de risco",
        "credit_limits": "a equipe de limites",
        "disputes": "a equipe de contestações",
        "complaints": "a equipe de reclamações",
        "general": "um atendente",
    },
}
HANDOFF_REASON = {
    "es": {
        "fraud": "Por tu seguridad, este caso lo revisa un especialista.",
        "risk": "Tus rechazos recientes requieren una revisión de riesgo que hace una persona.",
        "credit_limits": "Los cambios de cupo los aprueba una persona.",
        "disputes": "Las disputas de compras las gestiona un especialista.",
        "complaints": "Quiero que tu reclamo lo atienda una persona.",
        "general": "Esto lo resuelve mejor una persona.",
        "tool_failure": "Tuve un problema técnico y no hice cambios.",
        "readback_failed": "No pude verificar la operación y no la doy por hecha.",
    },
    "pt": {
        "fraud": "Para sua segurança, este caso é revisado por um especialista.",
        "risk": "Suas recusas recentes exigem uma análise de risco feita por uma pessoa.",
        "credit_limits": "Mudanças de limite são aprovadas por uma pessoa.",
        "disputes": "Contestações de compras são tratadas por um especialista.",
        "complaints": "Quero que sua reclamação seja atendida por uma pessoa.",
        "general": "Isso é melhor resolvido por uma pessoa.",
        "tool_failure": "Tive um problema técnico e não fiz alterações.",
        "readback_failed": "Não consegui verificar a operação e não a considero concluída.",
    },
}


def fmt_money(x: Decimal | None, currency: str) -> str:
    if x is None:
        return "—"
    s = f"{x:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{s} {currency}"


def fmt_date(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def card_vars(card: Card, lang: str) -> dict:
    return {
        "last4": card.last4,
        "kind": KIND[lang][card.kind],
        "status": STATUS[lang].get(card.status, card.status),
        "expiry": fmt_date(card.expiration_date),
        "days": card.days_to_expiry,
        "balance": fmt_money(card.current_balance, card.currency),
        "limit": fmt_money(card.credit_limit, card.currency),
        "available": fmt_money(card.available, card.currency),
        "as_of": fmt_date(date.fromisoformat(card.as_of)) if card.as_of else "—",
    }


def render(key: str, lang: str, **kw) -> str:
    # a missing expiry date is said in words, never shown as a dash
    if kw.get("expiry") == "—" and f"{key}_noexp" in T:
        key = f"{key}_noexp"
    return T[key][lang].format(**kw)


def card_option(card: Card, lang: str) -> str:
    return (
        f"{KIND[lang][card.kind]} ****{card.last4} ({STATUS[lang].get(card.status, card.status)})"
    )


DECLINE = {
    "es": {
        "insufficient": "{n} por fondos o cupo insuficiente",
        "expired": "{n} por tarjeta vencida",
        "invalid": "{n} por datos de tarjeta inválidos",
        "dnh": "{n} rechazadas por el emisor",
    },
    "pt": {
        "insufficient": "{n} por saldo ou limite insuficiente",
        "expired": "{n} por cartão vencido",
        "invalid": "{n} por dados do cartão inválidos",
        "dnh": "{n} recusadas pelo emissor",
    },
}
DECLINE_ADVICE = {
    "es": {
        "expired": "La causa principal es el vencimiento: puedo solicitar la reposición.",
        "insufficient": "Revisa tu cupo disponible antes de comprar.",
        "invalid": "Verifica número, fecha y código al comprar en línea.",
        "none": "",
    },
    "pt": {
        "expired": "A causa principal é o vencimento: posso pedir a segunda via.",
        "insufficient": "Confira o limite disponível antes de comprar.",
        "invalid": "Confira número, validade e código ao comprar online.",
        "none": "",
    },
}


def answer(intent: str, card: Card, lang: str) -> str:
    """The A0 reply for a card-scoped intent."""
    v = card_vars(card, lang)
    if intent == "card_status":
        return render("card_status", lang, **v)
    if intent == "balance_limit":
        if card.kind == "credit" and card.credit_limit is not None:
            return render("balance_credit", lang, **v)
        return render("balance_missing", lang, **v)
    if intent == "expiry_renewal":
        if card.days_to_expiry is not None and (
            card.days_to_expiry < 0 or card.is_active_but_expired
        ):
            return render("expired", lang, **v)
        if card.days_to_expiry is not None and card.days_to_expiry <= 45:
            return render("expiry_soon", lang, **v)
        return render("expiry_ok", lang, **v)
    if intent == "decline_reason":
        parts = {
            "insufficient": card.declines_insufficient_funds_30d,
            "expired": card.declines_expired_30d,
            "invalid": card.declines_invalid_card_30d,
            "dnh": card.declines_do_not_honor_30d,
        }
        seen = {k: n for k, n in parts.items() if n}
        if not seen:
            return render("decline_none", lang, **v)
        reasons = ", ".join(DECLINE[lang][k].format(n=n) for k, n in seen.items())
        top = max(seen, key=lambda k: seen[k])
        advice = DECLINE_ADVICE[lang].get(top, "")
        return render("decline_summary", lang, reasons=reasons, advice=advice, **v).strip()
    raise KeyError(intent)
