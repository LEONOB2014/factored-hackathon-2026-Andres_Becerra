import { afterEach, describe, expect, it, vi } from "vitest";
import { regionById } from "./api";
import { evaluationService, headlineRun, intervalPoints } from "./evaluation";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

afterEach(() => vi.restoreAllMocks());

const rate = (k: number, n: number, lo: number, hi: number) => ({ k, n, rate: k / n, ci95: [lo, hi] });
const block = (correct: number) => ({
  cases: 120,
  correct: rate(correct, 120, 0.89, 0.98),
  safe_automated_resolution_in_scope: rate(59, 63, 0.85, 0.98),
  safe_automated_resolution_attempted: rate(88, 93, 0.88, 0.98),
  containment: rate(93, 120, 0.69, 0.84),
  missed_transfers: rate(1, 27, 0.007, 0.18),
  unnecessary_transfers: rate(0, 63, 0, 0.057),
  unsafe_cases: rate(1, 120, 0.001, 0.046),
  latency_ms_p50: 2.9,
  latency_ms_p95: 22.5,
  cost_usd_per_case: 0,
  cost_usd_per_resolution: 0,
});
const summary = (correct: number) => ({ all: block(correct), es: block(correct), pt: block(correct), by_category: { fraud: rate(8, 8, 0.68, 1) } });

describe("evaluation service", () => {
  const body = {
    runs: [
      { label: "after-fix", n_cases: 120, manifest_ok: true, variants: { keyword: summary(80), learned: summary(115) } },
      { label: "first scored run", n_cases: 120, manifest_ok: true, variants: { keyword: summary(78), learned: summary(114) } },
    ],
    intent_model: { tuning: { cv_macro_f1: 0.74 }, held_out: [{ model: "learned_char_ngram_lr", n: 132, accuracy: 0.82, macro_f1: 0.82 }] },
    retrieval: { bundled: { "hit@1": 0.75 } },
  };

  it("puts the headline run first and labels the re-runs", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(body));
    const ev = await evaluationService.get();
    expect(spy.mock.calls[0]?.[0]).toBe(regionById("demo").base + "/api/control/evaluation");
    expect(ev.runs.map((r) => [r.label, r.headline])).toEqual([["first scored run", true], ["after-fix", false]]);
    expect(headlineRun(ev)?.variants.learned?.all.correct.k).toBe(114);
    expect(ev.intent_model?.held_out[0]?.model).toBe("learned_char_ngram_lr");
    expect(ev.retrieval["bundled"]?.["hit@1"]).toBe(0.75);
  });

  it("flattens runs × variants into interval points", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(body));
    const pts = intervalPoints(await evaluationService.get(), "all", ["correct"]);
    expect(pts).toHaveLength(4);
    expect(pts[0]).toMatchObject({ metric: "correct", run: "first scored run", variant: "keyword", k: 78, n: 120, lo: 0.89, hi: 0.98 });
    expect(pts.map((p) => p.series)).toContain("after-fix · learned");
  });

  it("tolerates a deployment without bundled reports", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ runs: [] }));
    const ev = await evaluationService.get("sa");
    expect(ev).toEqual({ runs: [], intent_model: null, retrieval: {} });
    expect(headlineRun(ev)).toBeUndefined();
  });
});
