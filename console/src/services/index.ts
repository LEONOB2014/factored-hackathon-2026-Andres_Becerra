// Domain services. Each function mirrors a future real API call; swap the
// mock import for fetch() without changing callers.
import desk from "@/mocks/desk.json";
import supervisor from "@/mocks/supervisor.json";
import atlas from "@/mocks/atlas.json";
import quality from "@/mocks/quality.json";
import pipelines from "@/mocks/pipelines.json";
import knowledge from "@/mocks/knowledge.json";
import specs from "@/mocks/specs.json";
import personas from "@/mocks/personas.json";
import type {
  AtlasCell, Correction, DeskCase, KChunk, KDoc, Kpi, Persona, PipelineCell, PolicyRow,
  QAgent, QIssue, Queue, Spec, UnsafeCase, Veto, Status, Verdict,
} from "./types";

const delay = <T,>(v: T, ms = 120) => new Promise<T>((r) => setTimeout(() => r(structuredClone(v)), ms));

// ---- personas / chat ----
export const personaService = {
  list: () => delay(personas as Persona[]),
};

// ---- desk ----
export const deskService = {
  queues: () => delay(desk.queues as { id: Queue; count: number; sla: string; priority: "high" | "normal" }[]),
  cases: () => delay(desk.cases as DeskCase[]),
};

// ---- supervisor ----
export const supervisorService = {
  kpis: () => delay(supervisor.kpis as Kpi[]),
  unsafe: () => delay(supervisor.unsafe as UnsafeCase[]),
  policy: () => delay({ version: "policy v1.7.2", rows: supervisor.policy as PolicyRow[], vetoes: supervisor.vetoes as Veto[] }),
};

// ---- readiness atlas ----
export const atlasService = {
  matrix: () => delay(atlas as { models: string[]; grains: AtlasCell["grain"][]; cells: AtlasCell[] }),
};

// ---- quality ----
export const qualityService = {
  agents: () => delay(quality.agents as QAgent[]),
  issues: () => delay(quality.issues as QIssue[]),
  corrections: () => delay(quality.corrections as Correction[]),
};

// ---- pipelines ----
function hash(s: string) {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h;
}
export const pipelineService = {
  grid: () => {
    const ov = pipelines.overrides as Record<string, Partial<PipelineCell>>;
    const cells: PipelineCell[] = [];
    for (const scope of pipelines.scopes)
      for (const layer of pipelines.layers) {
        const h = hash(scope + layer);
        const base: PipelineCell = {
          scope, layer, status: "ok" as Status,
          last_run: `${String(14 + (h % 5)).padStart(2, "0")}:${String(h % 60).padStart(2, "0")}`,
          rows: (h % 9000) * (scope === "ALL" ? 3100 : 1000) + 1200,
          reconciled: true, quality_gate: "green" as Verdict, governance_gate: "green" as Verdict,
        };
        const o = ov[`${scope}|${layer}`];
        cells.push({ ...base, ...o, reconciled: o?.status === "blocked" ? false : true });
      }
    return delay({ scopes: pipelines.scopes, layers: pipelines.layers, cells });
  },
  residency: () => delay(pipelines.residency),
  lineage: () => delay(pipelines.lineage as Record<string, string[]>),
};

// ---- knowledge ----
export const knowledgeService = {
  docs: () => delay({ hash: knowledge.active_set_hash, stores: knowledge.stores, docs: knowledge.docs as KDoc[] }),
  retrieve: (q: string) => {
    const words = q.toLowerCase().split(/\W+/u).filter(Boolean);
    const res = (knowledge.chunks as KChunk[])
      .map((c) => {
        const hits = c.keywords.filter((k) => words.some((w) => w.startsWith(k.slice(0, 5)) || k.startsWith(w.slice(0, 5)))).length;
        return { ...c, score: hits ? Math.min(0.97, 0.55 + hits * 0.14 + (hash(c.cite + q) % 7) / 100) : 0 };
      })
      .filter((c) => c.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 4);
    return delay(res, 250);
  },
};

// ---- specs ----
export const specService = {
  list: () => delay(specs as Spec[]),
  draft: (input: { idea: string; users: string; outcome: string }) =>
    delay(
      {
        id: `SPEC-0${24 + Math.floor(Math.random() * 10)}`,
        title: input.idea || "Nueva capacidad",
        stage: "Spec",
        problem: `Hoy ${input.users || "los usuarios"} no pueden ${input.idea.toLowerCase() || "lograr su objetivo"} de forma segura y trazable.`,
        users: input.users || "Por definir",
        criteria: [
          `Dado ${input.users || "un usuario"}, cuando solicita la capacidad, entonces ${input.outcome || "se cumple el resultado"}.`,
          "Toda acción queda en audit.turns con hash encadenado.",
          "Evaluación: unsafe = 0 en el set de regresión y p95 < 50 ms.",
        ],
        closes: [],
      } as Spec,
      600,
    ),
};

// ---- overview ----
export const overviewService = {
  summary: () =>
    delay({
      copilot: { status: "ok" as Status, uptime: "99,97 %", p95: "22,5 ms" },
      openIssues: (quality.issues as QIssue[]).filter((i) => i.stage !== "Closed").length,
      readiness: {
        green: (atlas.cells as AtlasCell[]).filter((c) => c.verdict === "green").length,
        amber: (atlas.cells as AtlasCell[]).filter((c) => c.verdict === "amber").length,
        red: (atlas.cells as AtlasCell[]).filter((c) => c.verdict === "red").length,
      },
      release: "v0.4.0",
    }),
};
