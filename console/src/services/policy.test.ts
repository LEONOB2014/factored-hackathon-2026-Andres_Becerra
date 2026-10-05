import { afterEach, describe, expect, it, vi } from "vitest";
import { regionById } from "./api";
import { policyService } from "./policy";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

afterEach(() => vi.restoreAllMocks());

// A slice of copilot/src/copilot/policy.yaml as GET /api/policy serves it.
const POLICY = {
  version: "2026-10-05.1",
  intents: {
    out_of_scope: { autonomy: "A0", escalate_after: 2, queue: "general" },
    card_status: { autonomy: "A0", needs_card: true },
    unblock_card: { autonomy: "A2", needs_card: true, action: "unblock", step_up: true },
    fraud_report: { autonomy: "A3", queue: "fraud", priority: "high" },
  },
  vetoes: [
    { id: "V01_fraud_flag", when: "card_fraud_flag", except_intents: ["block_card"], then: { handoff: "fraud", priority: "high" } },
    { id: "V05_already_blocked", when: "card_blocked", intents: ["block_card"], then: { answer: "already_blocked" } },
  ],
};

describe("policy service", () => {
  it("maps intents to the rule ids the engine writes into traces", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(POLICY));
    const p = await policyService.get();
    expect(spy.mock.calls[0]?.[0]).toBe(regionById("demo").base + "/api/policy");
    expect(p.version).toBe("2026-10-05.1");
    const row = (i: string) => p.rows.find((r) => r.intent === i);
    expect(row("card_status")).toMatchObject({ autonomy: "A0", queue: "—", rule: "P30_card_status", details: "needs card" });
    expect(row("unblock_card")).toMatchObject({ autonomy: "A2", rule: "P20_unblock_card", details: "action: unblock · step-up · needs card" });
    expect(row("fraud_report")).toMatchObject({ autonomy: "A3", queue: "fraud", rule: "P10_fraud_report", details: "priority: high" });
    expect(row("out_of_scope")?.details).toBe("escalate after 2");
  });

  it("describes each veto's scope and effect", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(POLICY));
    const [v1, v5] = (await policyService.get("mx")).vetoes;
    expect(v1).toEqual({ id: "V01_fraud_flag", condition: "card_fraud_flag · all intents · except block_card", effect: "handoff → fraud (high)" });
    expect(v5).toEqual({ id: "V05_already_blocked", condition: "card_blocked · intents: block_card", effect: "answer: already_blocked" });
  });
});
