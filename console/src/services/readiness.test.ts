import { afterEach, describe, expect, it, vi } from "vitest";
import { regionById } from "./api";
import { readinessService } from "./readiness";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

afterEach(() => vi.restoreAllMocks());

// Two rows as /api/control/readiness serves them: CSV floats as numbers, every other column as text.
const ROWS = [
  {
    scenario: "05 agent and queue", model: "handle time per agent-hour", metric: "MAE (s)", value: 143.069152,
    benchmark: "agent's own mean", benchmark_value: 143.234939, delta: 0.001157, delta_lo: 0.000887, delta_hi: 0.00141,
    material: 0.02, mde: 0.000359, verdict: "amber", root_cause: "significant but not material",
    requirement_to_green: "workforce data", n_train: "438818", n_test: "219400", n_test_needed: "219400", best_variant: "",
  },
  {
    scenario: "03 market and channel", model: "hourly volume per market × channel", metric: "MASE (pooled)", value: 0.748358,
    benchmark: "weekday mean / 24", benchmark_value: 0.736807, delta: -0.011551, delta_lo: -0.012765, delta_hi: -0.010111,
    material: 0.05, mde: 0.001964, verdict: "red", root_cause: "generator independence",
    requirement_to_green: "an intraday arrival profile", n_train: "78624", n_test: "24192", n_test_needed: "24192",
    best_variant: "Poisson GLM hour-of-week",
  },
];

describe("readiness service", () => {
  it("reads the demo region by default and types the CSV columns", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      reply({ source: "granularity_hour_readiness.csv", counts: { green: 0, amber: 2, red: 9 }, models: ROWS }),
    );
    const r = await readinessService.get();
    expect(spy.mock.calls[0]?.[0]).toBe(regionById("demo").base + "/api/control/readiness");
    expect(r.counts).toEqual({ green: 0, amber: 2, red: 9 });
    expect(r.models[0]).toMatchObject({ verdict: "amber", delta: 0.001157, n_train: 438818, n_test_needed: 219400, best_variant: null });
    expect(r.models[1]).toMatchObject({ verdict: "red", delta_lo: -0.012765, best_variant: "Poisson GLM hour-of-week" });
  });

  it("derives the counts when the API omits them", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ source: "x.csv", models: ROWS }));
    expect((await readinessService.get("mx")).counts).toEqual({ green: 0, amber: 1, red: 1 });
  });
});
