"""One conversation turn, end to end:

identity -> gateway -> intent (fast model; Claude when unsure) -> card resolution -> policy -> tools -> reply
(template; Claude may rephrase, grounding-checked) -> trace and audit; handoff packet when a person must decide.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from copilot import templates as tpl
from copilot.audit import AuditLog
from copilot.config import Settings
from copilot.gateway import fold, screen
from copilot.identity import AuthError, Identity, Session
from copilot.intent import IntentModel, Prediction
from copilot.llm import LLM, PROMPT_VERSION, CircuitOpen, Usage, grounded
from copilot.policy import Decision, Policy
from copilot.tools import Card, ToolError, Tools

YES = {
    "si",
    "sí",
    "sim",
    "confirmo",
    "confirmar",
    "dale",
    "ok",
    "de acuerdo",
    "claro",
    "pode",
    "pode ser",
    "isso",
    "correcto",
    "correto",
    "hazlo",
    "faz",
}
NO = {
    "no",
    "nao",
    "não",
    "cancelar",
    "cancela",
    "mejor no",
    "melhor nao",
    "melhor não",
    "dejalo",
    "deixa",
}
OPEN_QUESTIONS = {
    "es": {
        "fraud": [
            "Confirmar con el cliente las transacciones que no reconoce.",
            "Decidir bloqueo y reposición.",
        ],
        "risk": ["Revisar los rechazos «no honrar» y decidir si se levanta la restricción."],
        "credit_limits": ["Evaluar capacidad de pago y decidir el nuevo cupo."],
        "disputes": ["Identificar el cargo, el comercio y la fecha; abrir la disputa."],
        "complaints": ["Registrar el reclamo formal y acordar tiempos de respuesta."],
        "general": ["Entender la necesidad del cliente; el copiloto no pudo resolverla."],
    },
    "pt": {
        "fraud": [
            "Confirmar com o cliente as transações que não reconhece.",
            "Decidir bloqueio e segunda via.",
        ],
        "risk": ["Revisar as recusas «não honrar» e decidir se a restrição é retirada."],
        "credit_limits": ["Avaliar capacidade de pagamento e decidir o novo limite."],
        "disputes": ["Identificar a cobrança, a loja e a data; abrir a contestação."],
        "complaints": ["Registrar a reclamação formal e combinar prazos de resposta."],
        "general": ["Entender a necessidade do cliente; o copiloto não conseguiu resolver."],
    },
}


@dataclass
class Conversation:
    session_id: str
    customer_id: str
    lang: str = "es"
    pending_intent: str | None = None
    pending_confirm: dict | None = None
    pending_stepup: dict | None = None
    misses: int = 0
    transcript: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    handoff: dict | None = None


@dataclass
class Reply:
    text: str
    outcome: str  # answered | clarify | confirm_requested | stepup_required | action_done | cancelled | handoff
    #               | deny | refused | auth_required | tool_failure
    lang: str
    buttons: list[dict] = field(default_factory=list)
    handoff: dict | None = None
    trace: dict = field(default_factory=dict)


class Engine:
    def __init__(
        self,
        settings: Settings,
        tools: Tools,
        intent=None,
        llm: LLM | None = None,
        policy=None,
        audit=None,
    ):
        self.s = settings
        self.tools = tools
        self.policy = policy or Policy()
        self.intent = intent or IntentModel()
        self.llm = llm
        self.audit = audit or AuditLog(settings.audit_log)
        self.identity = Identity(
            settings.secret, settings.otp_fixture, settings.stepup_fixture, settings.session_ttl_s,
            settings.stepup_ttl_s, tools.known_customer,
        )  # fmt: skip
        self.convs: dict[str, Conversation] = {}

    # --- session ---------------------------------------------------------------------------------------------------
    def login(self, customer_id: str, otp: str) -> str:
        token = self.identity.login(customer_id, otp)
        sess = self.identity.session(token)
        self.convs[sess.session_id] = Conversation(sess.session_id, sess.customer_id)
        self.audit.append("login", session=sess.session_id, customer=customer_id)
        return token

    def _conv(self, sess: Session) -> Conversation:
        return self.convs.setdefault(
            sess.session_id, Conversation(sess.session_id, sess.customer_id)
        )

    # --- a turn ----------------------------------------------------------------------------------------------------
    def message(self, token: str | None, text: str) -> Reply:
        tr = Trace()
        with tr.stage("gateway"):
            scr = screen(text)
        try:
            with tr.stage("auth"):
                sess = self.identity.session(token)
        except AuthError as e:
            tr.note(auth=e.code)
            return self._finish(
                None,
                None,
                Reply(tpl.render("auth_required", scr.language), "auth_required", scr.language),
                tr,
                scr.text,
            )
        conv = self._conv(sess)
        scr = screen(text, conv.lang)
        lang = scr.language if scr.language_confidence > 0.5 else conv.lang
        conv.lang = lang
        conv.transcript.append({"role": "customer", "text": scr.text})
        tr.note(
            language=lang,
            language_confidence=round(scr.language_confidence, 2),
            pans_masked=len(scr.pan_suffixes),
        )

        if scr.injection:
            tr.note(guard="injection")
            return self._finish(
                sess,
                conv,
                Reply(tpl.render("refused_injection", lang), "refused", lang),
                tr,
                scr.text,
            )
        if scr.cross_customer:
            tr.note(guard="cross_customer")
            return self._finish(
                sess,
                conv,
                Reply(tpl.render("deny_other_customer", lang), "deny", lang),
                tr,
                scr.text,
            )

        folded = fold(scr.text).strip(" .!¡?¿")
        if conv.pending_confirm and (folded in YES or folded in NO):
            return self.confirm(token, folded in YES, _trace=tr)

        if folded in YES or folded in NO:  # a bare yes or no with nothing to confirm
            return self._finish(
                sess,
                conv,
                Reply(tpl.render("nothing_pending", lang), "clarify", lang),
                tr,
                scr.text,
            )
        conv.pending_confirm = None  # anything else drops an unconfirmed action
        mention = self._mention(scr.text, scr.pan_suffixes)
        pred = self._classify(scr.text, tr)
        # a card choice answers the pending question unless the message confidently asks for something else
        resumable = (
            pred.intent in (conv.pending_intent, "unclear")
            or pred.confidence < self.s.intent_threshold
        )
        if conv.pending_intent and (mention["last4"] or mention["kind"]) and resumable:
            pred = Prediction(conv.pending_intent, 1.0, "resume", 0.0)
        conv.pending_intent = None
        tr.note(
            intent=pred.intent,
            intent_confidence=round(pred.confidence, 3),
            intent_source=pred.source,
        )

        if pred.intent == "smalltalk":
            conv.misses = 0
            return self._finish(
                sess, conv, Reply(tpl.render("smalltalk", lang), "answered", lang), tr, scr.text
            )

        card = None
        if self.policy.needs_card(pred.intent):
            try:
                with tr.stage("tools.read"):
                    cards = self.tools.cards(sess)
            except ToolError:
                return self._handoff(
                    sess,
                    conv,
                    "general",
                    "normal",
                    "T01_tool_failure",
                    pred,
                    None,
                    tr,
                    scr.text,
                    reason="tool_failure",
                    outcome="tool_failure",
                )
            card, reply = self._resolve_card(cards, mention, pred.intent, conv, lang)
            if reply:
                return self._finish(sess, conv, reply, tr, scr.text)

        with tr.stage("policy"):
            d = self.policy.decide(pred.intent, card, conv.misses)
        tr.note(policy_rule=d.rule, autonomy=d.autonomy, policy_version=self.policy.version)
        return self._act(sess, conv, d, pred, card, tr, scr.text)

    def _classify(self, text: str, tr: Trace) -> Prediction:
        with tr.stage("intent.model"):
            pred = self.intent.predict(text)
        if pred.confidence >= self.s.intent_threshold or pred.source == "keyword":
            return pred
        if self.llm is not None and self.s.llm_available:
            try:
                with tr.stage("intent.llm"):
                    label, usage = self.llm.classify(text)
                tr.usage.add(usage)
                return Prediction(label, 1.0, "llm", usage.ms, pred.top)
            except (CircuitOpen, Exception) as e:  # any failure: the deterministic path decides
                tr.note(llm_error=type(e).__name__)
        return Prediction("unclear", pred.confidence, "model_low_confidence", pred.ms, pred.top)

    @staticmethod
    def _mention(text: str, pan_suffixes: list[str]) -> dict:
        t = fold(text)
        digits = pan_suffixes or re.findall(r"(?<![\d/.,])(\d{4})(?![\d/.,])", text)
        kind = "credit" if "credit" in t else "debit" if "debit" in t else None
        return {"last4": digits[-1] if digits else None, "kind": kind}

    def _resolve_card(
        self, cards: list[Card], mention: dict, intent: str, conv: Conversation, lang: str
    ):
        if not cards:
            return None, Reply(tpl.render("no_cards", lang), "answered", lang)
        if mention["last4"]:
            hit = [c for c in cards if c.last4 == mention["last4"]]
            if not hit:  # not one of the session's cards: never looked up anywhere else
                return None, Reply(
                    tpl.render("card_not_found", lang, last4=mention["last4"]), "deny", lang
                )
            return hit[0], None
        pool = [c for c in cards if c.kind == mention["kind"]] if mention["kind"] else cards
        if len(pool) == 1:
            return pool[0], None
        pool = pool or cards
        if len(pool) == 1:
            return pool[0], None
        conv.pending_intent = intent
        options = "; ".join(tpl.card_option(c, lang) for c in pool)
        buttons = [
            {"label": tpl.card_option(c, lang), "action": "message", "value": f"****{c.last4}"}
            for c in pool
        ]
        return None, Reply(
            tpl.render("ask_card", lang, n=len(pool), options=options), "clarify", lang, buttons
        )

    def _act(self, sess, conv, d: Decision, pred, card, tr, text) -> Reply:
        lang = conv.lang
        if d.kind == "clarify" or pred.intent == "unclear":
            conv.misses += 1
            if conv.misses >= 2:
                return self._handoff(
                    sess, conv, "general", "normal", "P03_repeated_unclear", pred, card, tr, text
                )
            return self._finish(
                sess, conv, Reply(tpl.render("clarify", lang), "clarify", lang), tr, text
            )
        if d.kind == "handoff":
            return self._handoff(sess, conv, d.queue, d.priority, d.rule, pred, card, tr, text)
        if pred.intent == "out_of_scope":
            conv.misses += 1
            return self._finish(
                sess, conv, Reply(tpl.render("out_of_scope", lang), "clarify", lang), tr, text
            )
        conv.misses = 0
        if d.kind == "answer":
            if d.template in tpl.T:
                body = (
                    tpl.render(d.template, lang, **tpl.card_vars(card, lang))
                    if card
                    else tpl.render(d.template, lang)
                )
            else:
                body = tpl.answer(pred.intent, card, lang)
            body = self._rephrase(body, lang, tr)
            return self._finish(sess, conv, Reply(body, "answered", lang), tr, text, card)
        # confirm (A2)
        if d.step_up and not sess.stepped_up:
            conv.pending_stepup = {
                "intent": pred.intent,
                "action": d.action,
                "product_id": card.product_id,
            }
            return self._finish(
                sess,
                conv,
                Reply(
                    tpl.render("stepup_needed", lang),
                    "stepup_required",
                    lang,
                    [{"label": "OTP", "action": "stepup"}],
                ),
                tr,
                text,
                card,
            )
        return self._ask_confirm(sess, conv, d.action, card, tr, text)

    def _ask_confirm(self, sess, conv, action, card, tr, text) -> Reply:
        lang = conv.lang
        with tr.stage("tools.prepare"):
            token = self.tools.prepare(sess, action, card.product_id)
        conv.pending_confirm = {
            "token": token,
            "action": action,
            "product_id": card.product_id,
            "last4": card.last4,
        }
        yes, no = ("Confirmar", "Cancelar") if lang == "es" else ("Confirmar", "Cancelar")
        buttons = [{"label": yes, "action": "confirm"}, {"label": no, "action": "cancel"}]
        body = tpl.render(f"confirm_{action}", lang, **tpl.card_vars(card, lang))
        return self._finish(
            sess, conv, Reply(body, "confirm_requested", lang, buttons), tr, text, card
        )

    def confirm(self, token: str | None, yes: bool, _trace: Trace | None = None) -> Reply:
        tr = _trace or Trace()
        try:
            sess = self.identity.session(token)
        except AuthError:
            return self._finish(
                None,
                None,
                Reply(tpl.render("auth_required", "es"), "auth_required", "es"),
                tr,
                "[confirm]",
            )
        conv = self._conv(sess)
        lang, pc = conv.lang, conv.pending_confirm
        conv.pending_confirm = None
        label = "[confirmar]" if yes else "[cancelar]"
        if not pc:
            return self._finish(
                sess, conv, Reply(tpl.render("nothing_pending", lang), "clarify", lang), tr, label
            )
        if not yes:
            return self._finish(
                sess, conv, Reply(tpl.render("cancelled", lang), "cancelled", lang), tr, label
            )
        pred = Prediction(f"{pc['action']}_card", 1.0, "confirmation", 0.0)
        try:
            with tr.stage("tools.execute"):
                res = self.tools.execute(sess, pc["token"])
        except AuthError as e:
            tr.note(auth=e.code)
            if e.code == "expired":
                return self._finish(
                    sess,
                    conv,
                    Reply(tpl.render("confirm_expired", lang), "cancelled", lang),
                    tr,
                    label,
                )
            if e.code == "stepup_required":
                conv.pending_stepup = {
                    "intent": pred.intent,
                    "action": pc["action"],
                    "product_id": pc["product_id"],
                }
                return self._finish(
                    sess,
                    conv,
                    Reply(
                        tpl.render("stepup_needed", lang),
                        "stepup_required",
                        lang,
                        [{"label": "OTP", "action": "stepup"}],
                    ),
                    tr,
                    label,
                )
            return self._finish(
                sess, conv, Reply(tpl.render("deny_other_customer", lang), "deny", lang), tr, label
            )
        except ToolError:
            return self._handoff(
                sess,
                conv,
                "general",
                "normal",
                "T01_tool_failure",
                pred,
                None,
                tr,
                label,
                reason="tool_failure",
                outcome="tool_failure",
            )
        with tr.stage("tools.read_back"):
            try:
                ok = self.tools.read_back(sess, res)
            except ToolError:
                ok = False
        conv.actions.append({**res, "read_back": ok, "at": datetime.now(UTC).isoformat()})
        tr.note(
            action=res["action"], action_id=res["action_id"], read_back=ok, replayed=res["replayed"]
        )
        self.audit.append(
            "action", session=sess.session_id, customer=sess.customer_id, read_back=ok, **res
        )
        if not ok:
            return self._handoff(
                sess,
                conv,
                "general",
                "normal",
                "T02_read_back_failed",
                pred,
                None,
                tr,
                label,
                reason="readback_failed",
                outcome="tool_failure",
            )
        body = tpl.render(
            f"done_{res['action']}", lang, last4=pc["last4"], action_id=res["action_id"]
        )
        return self._finish(sess, conv, Reply(body, "action_done", lang), tr, label)

    def step_up(self, token: str | None, otp: str) -> tuple[str | None, Reply]:
        tr = Trace()
        try:
            sess = self.identity.session(token)
        except AuthError:
            return None, self._finish(
                None,
                None,
                Reply(tpl.render("auth_required", "es"), "auth_required", "es"),
                tr,
                "[step-up]",
            )
        conv = self._conv(sess)
        lang = conv.lang
        try:
            new = self.identity.step_up(token, otp)
        except AuthError:
            return token, self._finish(
                sess, conv, Reply(tpl.render("stepup_failed", lang), "deny", lang), tr, "[step-up]"
            )
        sess = self.identity.session(new)
        self.audit.append("step_up", session=sess.session_id, customer=sess.customer_id)
        ps, conv.pending_stepup = conv.pending_stepup, None
        if not ps:
            return new, self._finish(
                sess,
                conv,
                Reply(tpl.render("nothing_pending", lang), "clarify", lang),
                tr,
                "[step-up]",
            )
        card = self.tools.card(sess, ps["product_id"])
        return new, self._ask_confirm(sess, conv, ps["action"], card, tr, "[step-up]")

    # --- outputs ---------------------------------------------------------------------------------------------------
    def _rephrase(self, body: str, lang: str, tr: Trace) -> str:
        if not (self.llm is not None and self.s.llm_available and self.s.rephrase):
            return body
        try:
            with tr.stage("reply.llm"):
                out, usage = self.llm.rephrase(body, lang)
            tr.usage.add(usage)
        except Exception as e:  # noqa: BLE001 - any failure keeps the template
            tr.note(llm_error=type(e).__name__, grounding="skipped")
            return body
        ok = grounded(body, out)
        tr.note(grounding="pass" if ok else "fail_fallback_template")
        return out if ok else body

    def _handoff(
        self,
        sess,
        conv,
        queue,
        priority,
        rule,
        pred,
        card,
        tr,
        text,
        reason=None,
        outcome="handoff",
    ) -> Reply:
        lang = conv.lang
        packet = {
            "handoff_id": "HO-" + secrets.token_hex(5).upper(),
            "created_at": datetime.now(UTC).isoformat(),
            "queue": queue,
            "priority": priority,
            "language": lang,
            "customer_id": sess.customer_id,
            "authentication": "otp+step-up" if sess.stepped_up else "otp",
            "request": text,
            "intent": {
                "label": pred.intent,
                "confidence": round(pred.confidence, 3),
                "source": pred.source,
            },
            "policy": {"rule": rule, "version": self.policy.version},
            "verified_facts": _facts(card) if card else None,
            "actions_taken": conv.actions,
            "open_questions": OPEN_QUESTIONS[lang].get(queue, OPEN_QUESTIONS[lang]["general"]),
            "transcript": conv.transcript[-12:],
        }
        conv.handoff = packet
        why = tpl.HANDOFF_REASON[lang].get(reason or queue, tpl.HANDOFF_REASON[lang]["general"])
        body = tpl.render(
            "handoff",
            lang,
            reason=why,
            queue=tpl.QUEUE[lang].get(queue, tpl.QUEUE[lang]["general"]),
        )
        tr.note(handoff_queue=queue, handoff_rule=rule)
        self.audit.append(
            "handoff",
            session=sess.session_id,
            customer=sess.customer_id,
            queue=queue,
            rule=rule,
            handoff_id=packet["handoff_id"],
        )
        return self._finish(sess, conv, Reply(body, outcome, lang, handoff=packet), tr, text, card)

    def _finish(
        self, sess, conv, reply: Reply, tr: Trace, text: str, card: Card | None = None
    ) -> Reply:
        reply.trace = tr.done(
            outcome=reply.outcome,
            model=self.s.llm_model if tr.usage.calls else None,
            prompt_version=PROMPT_VERSION if tr.usage.calls else None,
            card=card.last4 if card else None,
        )
        if conv is not None:
            conv.transcript.append({"role": "copilot", "text": reply.text})
        self.audit.append(
            "turn",
            session=sess.session_id if sess else None,
            customer=sess.customer_id if sess else None,
            text=text,
            outcome=reply.outcome,
            intent=reply.trace.get("intent"),
            rule=reply.trace.get("policy_rule"),
            latency_ms=reply.trace["latency_ms"],
        )
        return reply


def _facts(card: Card) -> dict:
    keep = (
        "last4", "kind", "status", "expiration_date", "days_to_expiry", "credit_limit", "current_balance",
        "current_decline_streak", "declines_do_not_honor_30d", "declines_insufficient_funds_30d",
        "declines_expired_30d", "declines_invalid_card_30d", "foreign_tx_90d", "open_cases", "contacts_30d",
        "next_best_action", "confirmed_fraud_365d", "reissue_requested", "currency", "as_of",
    )  # fmt: skip
    d = asdict(card)
    return {
        k: (str(d[k]) if d[k] is not None and not isinstance(d[k], bool | int) else d[k])
        for k in keep
    }


class Trace:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.stages: list[dict] = []
        self.fields: dict = {}
        self.usage = Usage()

    def stage(self, name: str):
        trace = self

        class _S:
            def __enter__(self):
                self.t = time.perf_counter()

            def __exit__(self, *exc):
                trace.stages.append(
                    {"stage": name, "ms": round((time.perf_counter() - self.t) * 1000, 2)}
                )
                return False

        return _S()

    def note(self, **kw) -> None:
        self.fields.update(kw)

    def done(self, **kw) -> dict:
        return {
            "turn_id": "TR-" + secrets.token_hex(4),
            **self.fields,
            **{k: v for k, v in kw.items() if v is not None},
            "stages": self.stages,
            "latency_ms": round((time.perf_counter() - self.t0) * 1000, 2),
            "llm_calls": self.usage.calls,
            "tokens_in": self.usage.input_tokens,
            "tokens_out": self.usage.output_tokens,
            "cost_usd": round(self.usage.cost_usd, 6),
        }
