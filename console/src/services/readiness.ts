// Readiness scorecard (ADR-018), read-only from the copilot API (no customer rows).
// The aggregates are the same in every region, so the screen reads the demo deployment by default.
import { api, type RegionId } from "./api";
import type { Readiness, ReadinessRow, Verdict } from "./types";

export const CONTROL_REGION: RegionId = "demo";

const VERDICTS: Verdict[] = ["green", "amber", "red"];

// The API sends the CSV's float columns as numbers and every other column as text (counts included).
const num = (v: unknown): number => (typeof v === "number" ? v : Number(v));
const optNum = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const str = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

type ApiRow = Partial<Record<keyof ReadinessRow, unknown>>;
type ApiReadiness = { source: string; counts?: Partial<Record<Verdict, number>>; models: ApiRow[] };

export const toReadinessRow = (r: ApiRow): ReadinessRow => ({
  scenario: str(r.scenario),
  model: str(r.model),
  metric: str(r.metric),
  value: num(r.value),
  benchmark: str(r.benchmark),
  benchmark_value: num(r.benchmark_value),
  delta: num(r.delta),
  delta_lo: num(r.delta_lo),
  delta_hi: num(r.delta_hi),
  material: num(r.material),
  mde: num(r.mde),
  verdict: (VERDICTS as string[]).includes(str(r.verdict)) ? (r.verdict as Verdict) : "red",
  root_cause: str(r.root_cause),
  requirement_to_green: str(r.requirement_to_green),
  n_train: optNum(r.n_train),
  n_test: optNum(r.n_test),
  n_test_needed: optNum(r.n_test_needed),
  best_variant: str(r.best_variant) || null,
});

export const readinessService = {
  get: async (region: RegionId = CONTROL_REGION): Promise<Readiness> => {
    const d = await api<ApiReadiness>(region, "/api/control/readiness");
    const models = d.models.map(toReadinessRow);
    const counts = Object.fromEntries(
      VERDICTS.map((v) => [v, d.counts?.[v] ?? models.filter((m) => m.verdict === v).length]),
    ) as Record<Verdict, number>;
    return { source: d.source, counts, models };
  },
};
