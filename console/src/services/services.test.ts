import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, regionById } from "./api";
import { ChatBackend } from "./chat";
import { deskService, personaService } from "./index";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("calls the selected region and sends token and staff code", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ ok: true }));
    await api("sa", "/api/handoffs", { token: "t1", staffCode: "s1" });
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(regionById("sa").base + "/api/handoffs");
    expect((init.headers as Record<string, string>)["authorization"]).toBe("Bearer t1");
    expect((init.headers as Record<string, string>)["x-staff-code"]).toBe("s1");
    expect(init.method).toBe("GET");
  });

  it("raises ApiError with the server detail", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ detail: "four_eyes" }, 409));
    await expect(api("mx", "/x", { body: {} })).rejects.toEqual(new ApiError(409, "four_eyes"));
  });
});

describe("services", () => {
  it("maps /api/demo customers to personas without names", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      reply({ customers: [{ role: "fraud_flag", customer_id: "CLI-1", cards: 1, label_es: "Alerta", label_pt: "Alerta PT" }], otp: "1", stepup: "2", staff: "3", deployment: { name: "x", region: "r", countries: ["MX"] } }),
    );
    const [p] = await personaService.list("mx", "pt");
    expect(p).toMatchObject({ customer_id: "CLI-1", scenario: "Alerta PT", role: "fraud_flag", cards: 1 });
    expect(p).not.toHaveProperty("name");
  });

  it("maps handoff cases and derives queue counts", async () => {
    const created = new Date(Date.now() - 5 * 60000).toISOString();
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      reply({ cases: [{ packet: { handoff_id: "HO-1", queue: "fraud", created_at: created }, status: "new", proposer: null, timeline: [{ at: created, event: "created", actor: "copilot" }] }] }),
    );
    const cases = await deskService.cases("mx", "3");
    expect(cases[0]).toMatchObject({ status: "new", sla_minutes: 15 });
    expect(cases[0]?.elapsed_minutes).toBeGreaterThanOrEqual(4);
    expect(deskService.queues(cases).find((q) => q.id === "fraud")?.count).toBe(1);
  });

  it("chat backend keeps the session token for later turns", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((_u, init) =>
      reply(String((init as RequestInit).body).includes("otp") ? { token: "tok" } : { text: "ok", outcome: "answered", lang: "es", buttons: [], handoff: null, trace: {} }),
    );
    const b = new ChatBackend("mx", { customer_id: "CLI-1", role: "x", scenario: "x", cards: 1, hint: "" });
    await b.session("CLI-1", "1");
    await b.message("hola");
    const init = spy.mock.calls[1]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["authorization"]).toBe("Bearer tok");
  });
});
