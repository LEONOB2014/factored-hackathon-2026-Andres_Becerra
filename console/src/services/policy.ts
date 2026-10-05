// The copilot's versioned autonomy policy (copilot/src/copilot/policy.yaml), read-only from GET /api/policy.
import { api, type RegionId } from "./api";
import { CONTROL_REGION } from "./readiness";
import type { PolicyRow, Queue, Veto } from "./types";

type ApiIntent = {
  autonomy: PolicyRow["autonomy"];
  queue?: Queue;
  priority?: string;
  needs_card?: boolean;
  action?: string;
  step_up?: boolean;
  uses_kb?: boolean;
  escalate_after?: number;
};
type ApiVeto = { id: string; when: string; intents?: string[]; except_intents?: string[]; then: { handoff?: string; priority?: string; answer?: string } };
type ApiPolicy = { version: string; intents: Record<string, ApiIntent>; vetoes: ApiVeto[] };

// The rule id the engine writes into each trace (policy.py: P10 hand-off, P20 confirm, P30 answer).
const RULE_PREFIX: Record<PolicyRow["autonomy"], string> = { A3: "P10", A2: "P20", A0: "P30" };

export const toPolicyRow = (intent: string, s: ApiIntent): PolicyRow => ({
  intent,
  autonomy: s.autonomy,
  queue: s.queue ?? "—",
  rule: intent === "out_of_scope" ? "P02_out_of_scope / P01_repeated_out_of_scope" : `${RULE_PREFIX[s.autonomy]}_${intent}`,
  details: [
    s.action && `action: ${s.action}`,
    s.step_up && "step-up",
    s.needs_card && "needs card",
    s.uses_kb && "knowledge base",
    s.priority && `priority: ${s.priority}`,
    s.escalate_after && `escalate after ${s.escalate_after}`,
  ].filter(Boolean).join(" · "),
});

export const toVeto = (v: ApiVeto): Veto => ({
  id: v.id,
  condition: [
    v.when,
    v.intents?.length ? `intents: ${v.intents.join(", ")}` : "all intents",
    v.except_intents?.length ? `except ${v.except_intents.join(", ")}` : "",
  ].filter(Boolean).join(" · "),
  effect: v.then.handoff
    ? `handoff → ${v.then.handoff}${v.then.priority ? ` (${v.then.priority})` : ""}`
    : `answer: ${v.then.answer ?? "—"}`,
});

export const policyService = {
  get: async (region: RegionId = CONTROL_REGION): Promise<{ version: string; rows: PolicyRow[]; vetoes: Veto[] }> => {
    const d = await api<ApiPolicy>(region, "/api/policy");
    return {
      version: d.version,
      rows: Object.entries(d.intents).map(([k, s]) => toPolicyRow(k, s)),
      vetoes: d.vetoes.map(toVeto),
    };
  },
};
