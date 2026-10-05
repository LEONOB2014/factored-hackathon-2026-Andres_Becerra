// Mock of the BETA AID conversational backend.
// Real endpoints: POST /api/session, /api/message, /api/confirm, /api/stepup.
import type { Card, ChatResponse, HandoffPacket, Outcome, Persona, Queue, Trace } from "./types";
import { formatMoney } from "@/lib/format";

type Lang = "es" | "pt";
type Pending = { action: "block" | "unblock" | "reissue"; card?: Card } | null;

let seq = 4100;
const rid = (p: string) => `${p}-${(++seq).toString(16).toUpperCase()}${Math.random().toString(16).slice(2, 4).toUpperCase()}`;
const L = (lang: Lang, es: string, pt: string) => (lang === "pt" ? pt : es);
const mask = (c: Card) => `•••• ${c.suffix}`;

export class ChatBackend {
  persona: Persona;
  token: string | null = null;
  stepped = false;
  pending: Pending = null;
  awaitingCard: Pending = null;
  history: { role: "customer" | "copilot"; text: string }[] = [];

  constructor(persona: Persona) {
    this.persona = structuredClone(persona);
  }

  async session(customer_id: string, otp: string): Promise<{ token: string } | { error: string }> {
    await wait(300);
    if (customer_id !== this.persona.customer_id || otp !== "123456") return { error: "invalid_otp" };
    this.token = rid("tok");
    return { token: this.token };
  }

  async stepup(otp: string): Promise<{ token: string; response: ChatResponse } | { error: string }> {
    await wait(300);
    if (otp !== "654321") return { error: "invalid_otp" };
    this.stepped = true;
    const lang = this.persona.lang;
    const card = this.pending?.card;
    return {
      token: this.token ?? "",
      response: this.reply({
        text: L(lang, `Segundo factor verificado. ¿Confirmas desbloquear la tarjeta ${card ? mask(card) : ""}?`, `Segundo fator verificado. Confirma o desbloqueio do cartão ${card ? mask(card) : ""}?`),
        outcome: "confirm_requested", lang,
        buttons: [{ label: L(lang, "Confirmar", "Confirmar"), action: "confirm" }, { label: L(lang, "Cancelar", "Cancelar"), action: "cancel" }],
        trace: { intent: "card_unblock", intent_source: "resume", policy_rule: "R-UBK-01", autonomy: "A2", card: card ? mask(card) : undefined },
      }),
    };
  }

  async confirm(yes: boolean): Promise<ChatResponse> {
    await wait(200);
    const lang = this.persona.lang;
    const p = this.pending;
    this.pending = null;
    if (!p || !p.card) return this.reply({ text: L(lang, "No hay ninguna acción pendiente.", "Não há nenhuma ação pendente."), outcome: "clarify", lang, trace: { intent_source: "confirmation" } });
    if (!yes) return this.reply({ text: L(lang, "Listo, cancelé la operación. No se hizo ningún cambio.", "Pronto, cancelei a operação. Nenhuma alteração foi feita."), outcome: "cancelled", lang, trace: { intent_source: "confirmation", autonomy: "A2" } });
    const action_id = rid("ACT");
    const intentMap = { block: "card_block", unblock: "card_unblock", reissue: "card_reissue" } as const;
    if (p.action === "block") p.card.status = "blocked";
    if (p.action === "unblock") p.card.status = "active";
    const verb = {
      block: L(lang, "bloqueada", "bloqueado"),
      unblock: L(lang, "desbloqueada", "desbloqueado"),
      reissue: L(lang, "en reposición (llega en 5 días hábiles)", "em reemissão (chega em 5 dias úteis)"),
    }[p.action];
    return this.reply({
      text: L(lang, `Hecho. Tu tarjeta ${mask(p.card)} quedó ${verb}. Comprobante ${action_id} (verificado en el sistema).`, `Feito. Seu cartão ${mask(p.card)} está ${verb}. Comprovante ${action_id} (verificado no sistema).`),
      outcome: "action_done", lang,
      trace: { intent: intentMap[p.action], intent_source: "confirmation", policy_rule: { block: "R-BLK-01", unblock: "R-UBK-01", reissue: "R-RSS-01" }[p.action], autonomy: "A2", card: mask(p.card), action: p.action, action_id, read_back: true, tool: true },
    });
  }

  async message(text: string): Promise<ChatResponse> {
    await wait(350);
    this.history.push({ role: "customer", text });
    const t = text.toLowerCase();
    const lang: Lang = /\b(não|nao|meu|cartão|cartao|você|olá|ola|quero|qual|reconheço|limite do)\b/.test(t) ? "pt" : /\b(mi|quiero|tarjeta|hola|cuál|cual|reponer)\b/.test(t) ? "es" : this.persona.lang;
    const cards = this.persona.cards;

    if (!this.token)
      return this.reply({ text: L(lang, "Para ayudarte necesito verificar tu identidad. Ingresa con tu código de un solo uso.", "Para ajudar preciso verificar sua identidade. Entre com seu código de uso único."), outcome: "auth_required", lang, trace: { intent_source: "keyword", autonomy: "A0" } });

    if (/(ignora|ignore|instrucciones|instruções|system prompt|prompt del sistema|eres ahora|you are now|jailbreak)/.test(t))
      return this.reply({ text: L(lang, "No puedo seguir esa instrucción. Puedo ayudarte con tus tarjetas: bloqueo, desbloqueo, cupo o reposición.", "Não posso seguir essa instrução. Posso ajudar com seus cartões: bloqueio, desbloqueio, limite ou reemissão."), outcome: "refused", lang, trace: { intent: "prompt_injection", intent_source: "keyword", guard: "injection", policy_rule: "V-03", autonomy: "A0" } });

    if (/(error|falla|falha|simular falla)/.test(t))
      return this.reply({ text: L(lang, "El sistema de tarjetas no respondió a tiempo. No se realizó ningún cambio; intenta de nuevo en unos minutos.", "O sistema de cartões não respondeu a tempo. Nenhuma alteração foi feita; tente novamente em alguns minutos."), outcome: "tool_failure", lang, trace: { intent: "card_status", intent_source: "model", policy_rule: "R-STS-01", autonomy: "A0", tool: true, slow: true } });

    // card selection from clarify
    const chosen = cards.find((c) => t.includes(c.suffix));
    if (this.awaitingCard && chosen) {
      const a = this.awaitingCard.action;
      this.awaitingCard = null;
      return this.startAction(a, chosen, lang, "resume");
    }

    if (/(fraude|no reconozco|não reconheço|nao reconheco|robo|roubo|fraud)/.test(t))
      return this.handoff("fraud", "fraud_report", "R-FRAUD-01", lang, text, L(lang, "Entiendo, es una posible transacción no reconocida. Te transfiero con un especialista de fraude (prioridad alta).", "Entendo, pode ser uma transação não reconhecida. Vou transferir para um especialista em fraude (prioridade alta)."));
    if (/(disputa|cobraron dos veces|doble cobro|cobrança|contestar|cargo no|duplicad)/.test(t))
      return this.handoff("disputes", "card_dispute", "R-DISP-02", lang, text, L(lang, "Según el procedimiento pol-card-dispute v2.0, un especialista debe registrar la disputa. Te transfiero con los datos verificados.", "Segundo o procedimento pol-card-dispute v2.0, um especialista deve registrar a contestação. Vou transferir com os dados verificados."), true);
    if (/(queja|reclamo|reclamação|reclamacao)/.test(t))
      return this.handoff("complaints", "complaint", "R-CMP-01", lang, text, L(lang, "Lamento la molestia. Registro tu queja y te paso con un especialista.", "Sinto muito. Registro sua reclamação e transfiro para um especialista."));
    if (/(aumentar|subir|ampliar).*(cupo|limite|límite)/.test(t))
      return this.handoff("credit_limits", "limit_increase", "R-LIM-04", lang, text, L(lang, "Un analista de crédito evaluará el aumento de cupo. Te transfiero.", "Um analista de crédito vai avaliar o aumento de limite. Vou transferir."));

    if (/(desbloque)/.test(t)) return this.pickCard("unblock", lang, (c) => c.status !== "active");
    if (/(bloque)/.test(t)) return this.pickCard("block", lang, (c) => c.status === "active");
    if (/(repon|venci|reemi|segunda via|segunda vía|nueva tarjeta|novo cartão)/.test(t)) return this.pickCard("reissue", lang, () => true);

    if (/(cupo|limite|límite|saldo|disponible|disponível|tarjetas|cartões|cartoes)/.test(t)) {
      const lines = cards.map((c) => `${c.brand} ${mask(c)} · ${statusWord(c.status, lang)}${c.limit ? ` · ${L(lang, "disponible", "disponível")} ${formatMoney(c.limit - c.used, c.currency)} ${L(lang, "de", "de")} ${formatMoney(c.limit, c.currency)}` : ""}`);
      return this.reply({ text: lines.join("\n"), outcome: "answered", lang, trace: { intent: "card_limit", intent_source: "model", policy_rule: "R-LIM-01", autonomy: "A0", tool: true, grounding: "pass" } });
    }

    return this.reply({
      text: L(lang, "No estoy seguro de qué necesitas. ¿Es sobre alguna de estas opciones?", "Não tenho certeza do que você precisa. É sobre alguma destas opções?"),
      outcome: "clarify", lang,
      buttons: [
        { label: L(lang, "Ver mis tarjetas", "Ver meus cartões"), action: "message", value: L(lang, "ver mis tarjetas", "ver meus cartões") },
        { label: L(lang, "Bloquear tarjeta", "Bloquear cartão"), action: "message", value: L(lang, "quiero bloquear mi tarjeta", "quero bloquear meu cartão") },
        { label: L(lang, "No reconozco un cargo", "Não reconheço uma compra"), action: "message", value: L(lang, "no reconozco un cargo", "não reconheço uma compra") },
      ],
      trace: { intent: "unknown", intent_confidence: 0.41, intent_source: "model_low_confidence", autonomy: "A0" },
    });
  }

  private pickCard(action: "block" | "unblock" | "reissue", lang: Lang, filter: (c: Card) => boolean) {
    const cands = this.persona.cards.filter(filter);
    const pool = cands.length ? cands : this.persona.cards;
    if (pool.length > 1) {
      this.awaitingCard = { action };
      return this.reply({
        text: L(lang, "Tienes varias tarjetas. ¿Cuál?", "Você tem vários cartões. Qual?"),
        outcome: "clarify", lang,
        buttons: pool.map((c) => ({ label: `${c.brand} ${mask(c)}`, action: "message" as const, value: c.suffix })),
        trace: { intent: `card_${action}`, intent_source: "model", intent_confidence: 0.94, policy_rule: "V-01", autonomy: "A2" },
      });
    }
    return this.startAction(action, pool[0]!, lang, "model");
  }

  private startAction(action: "block" | "unblock" | "reissue", card: Card, lang: Lang, source: NonNullable<Trace["intent_source"]>): ChatResponse {
    const intent = `card_${action}`;
    if (card.status === "cancelled" && action !== "block")
      return this.reply({ text: L(lang, `La tarjeta ${mask(card)} está cancelada y no puede reactivarse por este canal. Puedo pasarte con un asesor si lo deseas.`, `O cartão ${mask(card)} está cancelado e não pode ser reativado por este canal.`), outcome: "deny", lang, buttons: [{ label: L(lang, "Hablar con un asesor", "Falar com um atendente"), action: "message", value: L(lang, "quiero poner una queja", "quero fazer uma reclamação") }], trace: { intent, intent_source: source, intent_confidence: 0.95, policy_rule: "V-02", autonomy: "A2", card: mask(card) } });
    if (action === "block" && card.status !== "active")
      return this.reply({ text: L(lang, `La tarjeta ${mask(card)} ya no está activa (${statusWord(card.status, lang)}).`, `O cartão ${mask(card)} já não está ativo (${statusWord(card.status, lang)}).`), outcome: "answered", lang, trace: { intent, intent_source: source, policy_rule: "R-STS-01", autonomy: "A0", card: mask(card), tool: true } });
    this.pending = { action, card };
    if (action === "unblock" && !this.stepped)
      return this.reply({ text: L(lang, `Para desbloquear ${mask(card)} necesito un segundo factor. Ingresa el código que enviamos a tu app.`, `Para desbloquear ${mask(card)} preciso de um segundo fator. Digite o código enviado ao seu app.`), outcome: "stepup_required", lang, buttons: [{ label: L(lang, "Verificar segundo factor", "Verificar segundo fator"), action: "stepup" }], trace: { intent, intent_source: source, intent_confidence: 0.96, policy_rule: "V-04", autonomy: "A2", card: mask(card) } });
    const q = { block: L(lang, "bloquear", "bloquear"), unblock: L(lang, "desbloquear", "desbloquear"), reissue: L(lang, "reponer", "reemitir") }[action];
    return this.reply({
      text: L(lang, `¿Confirmas ${q} la tarjeta ${card.brand} ${mask(card)}?`, `Confirma ${q} o cartão ${card.brand} ${mask(card)}?`),
      outcome: "confirm_requested", lang,
      buttons: [{ label: "Confirmar", action: "confirm" }, { label: "Cancelar", action: "cancel" }],
      trace: { intent, intent_source: source, intent_confidence: 0.96, policy_rule: { block: "R-BLK-01", unblock: "R-UBK-01", reissue: "R-RSS-01" }[action], autonomy: "A2", card: mask(card) },
    });
  }

  private handoff(queue: Queue, intent: string, rule: string, lang: Lang, request: string, text: string, withProcedure = false): ChatResponse {
    const card = this.persona.cards[0]!;
    const packet: HandoffPacket = {
      handoff_id: rid("HO"),
      created_at: new Date().toISOString(),
      queue, priority: queue === "fraud" ? "high" : "normal", language: lang,
      customer_id: this.persona.customer_id,
      authentication: this.stepped ? "otp+step-up" : "otp",
      request: request.replace(/\d{6,}/g, "••••"),
      intent: { label: intent, confidence: 0.95, source: "model" },
      policy: { rule, version: "policy v1.7.2" },
      verified_facts: { card: mask(card), status: card.status, limit: formatMoney(card.limit, card.currency), used: formatMoney(card.used, card.currency) },
      actions_taken: [],
      procedures: withProcedure ? [{ cite: "pol-card-dispute v2.0", title: "Disputas de tarjeta", heading: "Mandatory intake data", classification: "internal", score: 0.94, text: "Registrar monto, fecha, comercio, canal y si la tarjeta está en posesión del cliente." }] : [],
      open_questions: queue === "fraud" ? ["¿Tarjeta en posesión del cliente?", "¿Otras transacciones no reconocidas?"] : ["¿Monto y fecha exactos?"],
      transcript: [...this.history, { role: "copilot", text }],
    };
    return this.reply({ text, outcome: "handoff", lang, handoff: packet, trace: { intent, intent_source: "model", intent_confidence: 0.95, policy_rule: rule, autonomy: "A3", grounding: withProcedure ? "pass" : "n/a", retrieval: withProcedure ? [{ cite: "pol-card-dispute v2.0 · Mandatory intake data", score: 0.94, classification: "internal" }] : undefined } });
  }

  private reply(r: {
    text: string; outcome: Outcome; lang: Lang; buttons?: ChatResponse["buttons"]; handoff?: HandoffPacket | null;
    trace: { [K in keyof Trace]?: Trace[K] | undefined } & { tool?: boolean; slow?: boolean };
  }): ChatResponse {
    const { tool, slow, ...tr } = r.trace;
    const usesLlm = tr.intent_source === "llm";
    const stages = [
      { stage: "guard", ms: +(0.8 + Math.random()).toFixed(1) },
      { stage: "intent", ms: usesLlm ? 380 + Math.round(Math.random() * 90) : +(1.8 + Math.random() * 2).toFixed(1) },
      { stage: "policy", ms: +(0.3 + Math.random() * 0.3).toFixed(1) },
      ...(tool ? [{ stage: "tool", ms: slow ? 5000 : +(9 + Math.random() * 14).toFixed(1) }] : []),
      ...(tr.retrieval ? [{ stage: "retrieval", ms: +(6 + Math.random() * 6).toFixed(1) }] : []),
      { stage: "grounding", ms: +(0.6 + Math.random()).toFixed(1) },
      { stage: "render", ms: +(0.5 + Math.random() * 0.8).toFixed(1) },
    ];
    const tokens_in = usesLlm ? 640 : 0;
    const trace: Trace = {
      turn_id: rid("T"),
      outcome: r.outcome,
      intent_confidence: tr.intent_confidence ?? (tr.intent ? 0.93 : undefined),
      policy_version: "v1.7.2",
      language: r.lang,
      guard: "pass",
      grounding: "pass",
      ...tr,
      stages,
      latency_ms: +stages.reduce((a, s) => a + s.ms, 0).toFixed(1),
      llm_calls: usesLlm ? 1 : 0,
      tokens_in, tokens_out: usesLlm ? 52 : 0,
      cost_usd: usesLlm ? 0.0011 : 0,
    } as Trace;
    this.history.push({ role: "copilot", text: r.text });
    return { text: r.text, outcome: r.outcome, lang: r.lang, buttons: r.buttons ?? [], handoff: r.handoff ?? null, trace };
  }
}

function statusWord(s: Card["status"], lang: Lang) {
  const es = { active: "activa", blocked: "bloqueada", expired: "vencida", cancelled: "cancelada" };
  const pt = { active: "ativo", blocked: "bloqueado", expired: "vencido", cancelled: "cancelado" };
  return (lang === "pt" ? pt : es)[s];
}
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
