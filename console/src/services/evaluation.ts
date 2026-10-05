// Challenge-set evaluation (headline run and labelled re-runs), read-only from the copilot API.
import { api, type RegionId } from "./api";
import { CONTROL_REGION } from "./readiness";
import {
  RATE_METRICS,
  type EvalBlock,
  type EvalRun,
  type EvalSummary,
  type EvalVariant,
  type Evaluation,
  type IntervalPoint,
  type RateMetric,
} from "./types";

const VARIANTS: EvalVariant[] = ["keyword", "learned"];
export const HEADLINE_LABEL = "first scored run";

type ApiEvaluation = {
  runs?: { label: string; n_cases: number; manifest_ok: boolean; variants: Partial<Record<EvalVariant, EvalSummary>> }[];
  intent_model?: Evaluation["intent_model"];
  retrieval?: Evaluation["retrieval"];
};

export const evaluationService = {
  get: async (region: RegionId = CONTROL_REGION): Promise<Evaluation> => {
    const d = await api<ApiEvaluation>(region, "/api/control/evaluation");
    const runs: EvalRun[] = (d.runs ?? []).map((r) => ({ ...r, headline: r.label === HEADLINE_LABEL }));
    // The headline run always comes first, whatever order the API lists the files in.
    runs.sort((a, b) => Number(b.headline) - Number(a.headline));
    return { runs, intent_model: d.intent_model ?? null, retrieval: d.retrieval ?? {} };
  },
};

export const headlineRun = (ev: Evaluation): EvalRun | undefined => ev.runs.find((r) => r.headline) ?? ev.runs[0];

// Flattens runs × variants into one interval point per metric, for the comparison charts.
export function intervalPoints(ev: Evaluation, block: "all" | "es" | "pt" = "all", metrics: readonly RateMetric[] = RATE_METRICS): IntervalPoint[] {
  const out: IntervalPoint[] = [];
  for (const run of ev.runs)
    for (const variant of VARIANTS) {
      const b: EvalBlock | undefined = run.variants[variant]?.[block];
      if (!b) continue;
      for (const metric of metrics) {
        const r = b[metric];
        if (!r) continue;
        out.push({
          metric,
          run: run.label,
          variant,
          series: `${run.label} · ${variant}`,
          rate: r.rate,
          lo: r.ci95[0],
          hi: r.ci95[1],
          k: r.k,
          n: r.n,
        });
      }
    }
  return out;
}
