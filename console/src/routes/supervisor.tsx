import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { evaluationService, policyService, supervisorService } from "@/services";
import { headlineRun, intervalPoints } from "@/services/evaluation";
import { RATE_METRICS, type EvalBlock, type Rate, type RateMetric, type UnsafeCase } from "@/services/types";
import { AutonomyBadge, IntervalBar, Mono, OutcomeBadge, PageHeader, StatusBadge } from "@/components/beta/badges";
import { IntervalChart } from "@/components/beta/plots";
import { ModelEvals } from "@/components/beta/ModelEvals";
import { TracePanel } from "@/components/beta/TracePanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useI18n, useTx } from "@/lib/i18n";

export const Route = createFileRoute("/supervisor")({
  head: () => ({
    meta: [
      { title: "Supervisor — BETA AID" },
      { name: "description", content: "Copilot challenge-set KPIs with Wilson 95% intervals, keyword vs learned, unsafe case drill-down and the versioned autonomy policy." },
      { property: "og:title", content: "Supervisor — BETA AID" },
      { property: "og:description", content: "Copilot KPIs with 95% intervals and the versioned autonomy policy." },
    ],
  }),
  component: SupervisorPage,
});

const METRIC_KEY: Record<RateMetric, string> = {
  correct: "kpi.correct",
  safe_automated_resolution_in_scope: "kpi.safe",
  safe_automated_resolution_attempted: "kpi.safe_attempted",
  containment: "kpi.containment",
  missed_transfers: "kpi.missed",
  unnecessary_transfers: "kpi.unnecessary",
  unsafe_cases: "kpi.unsafe",
};
const LOWER_BETTER: RateMetric[] = ["missed_transfers", "unnecessary_transfers", "unsafe_cases"];

const pct = (x: number) => `${(x * 100).toFixed(1).replace(".", ",")} %`;
const ci = (r: Rate) => `[${pct(r.ci95[0])}, ${pct(r.ci95[1])}]`;

function SupervisorPage() {
  const { t } = useI18n();
  const tx = useTx();
  const ev = useQuery({ queryKey: ["control", "evaluation"], queryFn: () => evaluationService.get() });
  const { data: unsafe } = useQuery({ queryKey: ["unsafe"], queryFn: supervisorService.unsafe });
  const pol = useQuery({ queryKey: ["control", "policy"], queryFn: () => policyService.get() });
  const policy = pol.data;
  const [lang, setLang] = useState<"all" | "es" | "pt">("all");
  const [region, setRegion] = useState("all");
  const [drill, setDrill] = useState<UnsafeCase | null>(null);
  const rows = (unsafe ?? []).filter((u) => (lang === "all" || u.lang === lang) && (region === "all" || u.region === region));

  const head = ev.data ? headlineRun(ev.data) : undefined;
  const reruns = ev.data?.runs.filter((r) => r !== head) ?? [];
  const learned = head?.variants.learned;
  const block: EvalBlock | undefined = learned?.[lang];
  const points = ev.data ? intervalPoints(ev.data, lang) : [];
  const categories = Object.keys(learned?.by_category ?? {}).sort();

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow={tx("Atención al cliente", "Atendimento", "Customer service")} title="Supervisor"
        actions={<F label={tx("Idioma", "Idioma", "Language")} value={lang} onChange={(v) => setLang(v as typeof lang)} opts={[["all", "ES + PT"], ["es", "ES"], ["pt", "PT"]]} />}>
        {tx("KPIs del challenge set congelado, servidos por el copiloto (/api/control/evaluation). Intervalos de Wilson al 95 %.", "KPIs do challenge set congelado, servidos pelo copiloto (/api/control/evaluation). Intervalos de Wilson a 95 %.", "KPIs from the frozen challenge set, served by the copilot (/api/control/evaluation). Wilson 95% intervals.")}
      </PageHeader>
      <Tabs defaultValue="kpis">
        <TabsList><TabsTrigger value="kpis">KPIs</TabsTrigger><TabsTrigger value="models">{tx("Modelos", "Modelos", "Models")}</TabsTrigger><TabsTrigger value="policy">{tx("Política", "Política", "Policy")}</TabsTrigger></TabsList>
        <TabsContent value="kpis" className="mt-4 space-y-6">
          {ev.isLoading && <p className="text-sm text-muted-foreground">{tx("Cargando la evaluación…", "Carregando a avaliação…", "Loading the evaluation…")}</p>}
          {ev.isError && <div className="panel p-4 text-sm text-blocked">{tx("No se pudo leer /api/control/evaluation", "Não foi possível ler /api/control/evaluation", "Could not read /api/control/evaluation")}: <Mono>{ev.error instanceof Error ? ev.error.message : String(ev.error)}</Mono></div>}
          {ev.data && !head && <p className="text-sm text-muted-foreground">{tx("Este despliegue no incluye reportes de evaluación.", "Esta implantação não inclui relatórios de avaliação.", "This deployment bundles no evaluation reports.")}</p>}

          {head && (
            <div className="panel flex flex-wrap items-center gap-2 p-3 text-xs">
              <StatusBadge status="ok" mono>headline</StatusBadge>
              <span><b>{head.label}</b> · {head.n_cases} {tx("casos", "casos", "cases")} · manifest {head.manifest_ok ? "ok" : "✗"} · {tx("variante", "variante", "variant")} <Mono>learned</Mono></span>
              {reruns.map((r) => (
                <span key={r.label} className="flex items-center gap-2 text-muted-foreground">
                  <StatusBadge status="info" mono>{tx("re-ejecución etiquetada", "reexecução rotulada", "labelled re-run")}</StatusBadge>
                  <b>{r.label}</b> · {tx("solo para comparar; no reemplaza el titular", "só para comparar; não substitui o resultado principal", "for comparison only; it does not replace the headline")}
                </span>
              ))}
            </div>
          )}

          {block && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(["correct", "safe_automated_resolution_in_scope", "containment", "missed_transfers", "unnecessary_transfers", "unsafe_cases"] as const).map((m) => {
                const r = block[m];
                const low = LOWER_BETTER.includes(m);
                return (
                  <Tile key={m} label={t(METRIC_KEY[m])} value={pct(r.rate)} better={low ? "lower" : "higher"}>
                    <IntervalBar className="mt-3" value={r.rate} lo={r.ci95[0]} hi={r.ci95[1]} min={low ? 0 : 0.5} max={low ? 0.25 : 1} />
                    <div className="mt-1 font-mono text-[10px] text-muted-foreground">{r.k}/{r.n} · IC 95 % {ci(r)}</div>
                  </Tile>
                );
              })}
              <Tile label={t("kpi.p50")} value={`${block.latency_ms_p50} ms`} better="lower" />
              <Tile label={t("kpi.p95")} value={`${block.latency_ms_p95} ms`} better="lower" />
              <Tile label={t("kpi.cost")} value={`US$ ${block.cost_usd_per_resolution.toFixed(4)}`} better="lower">
                <div className="mt-1 font-mono text-[10px] text-muted-foreground">US$ {block.cost_usd_per_case.toFixed(4)} / {tx("caso", "caso", "case")}</div>
              </Tile>
            </div>
          )}

          {points.length > 0 && (
            <div className="panel p-4">
              <div className="text-sm font-semibold">keyword vs learned · {tx("titular vs re-ejecución", "principal vs reexecução", "headline vs re-run")}</div>
              <div className="mb-3 text-[11px] text-muted-foreground">{tx("Punto = tasa; barra = IC de Wilson 95 %. Opaco = primera ejecución (titular); tenue = re-ejecución etiquetada.", "Ponto = taxa; barra = IC de Wilson 95 %. Opaco = primeira execução (principal); tênue = reexecução rotulada.", "Dot = rate; bar = Wilson 95% CI. Solid = first scored run (headline); faded = labelled re-run.")}</div>
              <div className="grid gap-x-6 gap-y-4 lg:grid-cols-2">
                {RATE_METRICS.map((m) => (
                  <div key={m}>
                    <div className="text-xs font-medium">{t(METRIC_KEY[m])} <span className="text-muted-foreground">{LOWER_BETTER.includes(m) ? "↓" : "↑"}</span></div>
                    <IntervalChart label={t(METRIC_KEY[m])} points={points.filter((p) => p.metric === m)} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {learned && (
            <div className="grid gap-4 xl:grid-cols-[2fr_3fr]">
              <div className="panel overflow-x-auto">
                <div className="border-b px-4 py-2.5 text-sm font-semibold">{tx("Por idioma", "Por idioma", "By language")} <Mono className="ml-2 text-muted-foreground">{head?.label} · learned</Mono></div>
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground"><tr className="border-b"><th className="px-4 py-2 font-medium">KPI</th><th className="px-2 font-medium">ES</th><th className="px-2 font-medium">PT</th></tr></thead>
                  <tbody>
                    {RATE_METRICS.map((m) => (
                      <tr key={m} className="border-b last:border-0">
                        <td className="px-4 py-2 text-xs">{t(METRIC_KEY[m])}</td>
                        <td className="px-2"><RateCell r={learned.es[m]} /></td>
                        <td className="px-2"><RateCell r={learned.pt[m]} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="panel overflow-x-auto">
                <div className="border-b px-4 py-2.5 text-sm font-semibold">{tx("Decisión correcta por categoría", "Decisão correta por categoria", "Correct decision by category")}</div>
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                    <th className="px-4 py-2 font-medium">{tx("categoría", "categoria", "category")}</th>
                    <th className="px-2 font-medium">keyword</th>
                    <th className="px-2 font-medium">learned</th>
                    {reruns.map((r) => <th key={r.label} className="px-2 font-medium">learned · {r.label}</th>)}
                  </tr></thead>
                  <tbody>
                    {categories.map((c) => (
                      <tr key={c} className="border-b last:border-0">
                        <td className="px-4 py-2"><Mono>{c}</Mono></td>
                        <td className="px-2"><RateCell r={head?.variants.keyword?.by_category[c]} /></td>
                        <td className="px-2"><RateCell r={learned.by_category[c]} /></td>
                        {reruns.map((r) => <td key={r.label} className="px-2"><RateCell r={r.variants.learned?.by_category[c]} /></td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="panel overflow-x-auto">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
              <div className="text-sm font-semibold">{tx("Casos recientes inseguros o fallidos", "Casos recentes inseguros ou com falha", "Recent unsafe or failed cases")} <StatusBadge status="info" className="ml-2">{tx("datos de demostración", "dados de demonstração", "demo data")}</StatusBadge></div>
              <F label={tx("Región", "Região", "Region")} value={region} onChange={setRegion} opts={[["all", "MX · CO · AR"], ["MX", "MX"], ["CO", "CO"], ["AR", "AR"]]} />
            </div>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr className="border-b"><th className="px-4 py-2 font-medium">turn</th><th className="px-2 font-medium">{tx("cuándo", "quando", "when")}</th><th className="px-2 font-medium">lang · region</th><th className="px-2 font-medium">outcome</th><th className="px-2 font-medium">intent</th><th className="px-2 font-medium">{tx("problema", "problema", "issue")}</th></tr></thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.turn_id} className="cursor-pointer border-b last:border-0 hover:bg-muted/50" onClick={() => setDrill(u)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setDrill(u)}>
                    <td className="px-4 py-2"><Mono className="text-primary underline">{u.turn_id}</Mono></td><td className="px-2"><Mono>{u.at}</Mono></td><td className="px-2"><Mono>{u.lang} · {u.region}</Mono></td><td className="px-2"><OutcomeBadge outcome={u.outcome} /></td><td className="px-2"><Mono>{u.intent}</Mono></td><td className="px-2 text-xs">{u.issue}</td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-xs text-muted-foreground">—</td></tr>}
              </tbody>
            </table>
          </div>
        </TabsContent>
        <TabsContent value="models" className="mt-4">
          {ev.data ? <ModelEvals intent={ev.data.intent_model} retrieval={ev.data.retrieval} /> : <p className="text-sm text-muted-foreground">{ev.isError ? tx("No se pudo leer /api/control/evaluation", "Não foi possível ler /api/control/evaluation", "Could not read /api/control/evaluation") : tx("Cargando la evaluación…", "Carregando a avaliação…", "Loading the evaluation…")}</p>}
        </TabsContent>
        <TabsContent value="policy" className="mt-4 grid gap-4 lg:grid-cols-[3fr_2fr]">
          {pol.isError && <div className="panel p-4 text-sm text-blocked lg:col-span-2">{tx("No se pudo leer /api/policy", "Não foi possível ler /api/policy", "Could not read /api/policy")}: <Mono>{pol.error instanceof Error ? pol.error.message : String(pol.error)}</Mono></div>}
          <div className="panel overflow-x-auto">
            <div className="border-b px-4 py-2.5 text-sm font-semibold">intent → autonomy → queue <Mono className="ml-2 text-muted-foreground">{policy?.version}</Mono></div>
            <table className="w-full text-sm"><tbody>
              {policy?.rows.map((r) => (
                <tr key={r.intent} className="border-b last:border-0"><td className="px-4 py-2"><Mono>{r.intent}</Mono></td><td className="px-2"><AutonomyBadge level={r.autonomy} /></td><td className="px-2"><Mono>{r.queue}</Mono></td><td className="px-2 text-xs text-muted-foreground"><Mono>{r.rule}</Mono>{r.details && <div className="text-[11px]">{r.details}</div>}</td></tr>
              ))}
            </tbody></table>
          </div>
          <div className="panel">
            <div className="border-b px-4 py-2.5 text-sm font-semibold">Vetoes</div>
            <ul>{policy?.vetoes.map((v) => (
              <li key={v.id} className="border-b px-4 py-2.5 text-xs last:border-0"><Mono className="font-semibold">{v.id}</Mono> · {v.condition}<div className="text-muted-foreground">→ {v.effect}</div></li>
            ))}</ul>
          </div>
        </TabsContent>
      </Tabs>
      <Sheet open={!!drill} onOpenChange={(o) => !o && setDrill(null)}>
        <SheetContent className="w-[440px] overflow-y-auto p-0 sm:max-w-[440px]">
          <SheetHeader className="border-b p-4"><SheetTitle>{tx("Traza", "Rastro", "Trace")} {drill?.turn_id}</SheetTitle></SheetHeader>
          {drill && <><p className="px-4 pt-3 text-xs">{drill.issue}</p><TracePanel trace={drill.trace} /></>}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function Tile({ label, value, better, children }: { label: string; value: string; better: "higher" | "lower"; children?: ReactNode }) {
  const tx = useTx();
  return (
    <div className="panel p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-2"><span className="font-mono text-2xl font-semibold">{value}</span><span className="text-[11px] text-muted-foreground">{better === "higher" ? "↑" : "↓"} {tx("mejor", "melhor", "better")}</span></div>
      {children}
    </div>
  );
}

function RateCell({ r }: { r: Rate | undefined }) {
  if (!r) return <span className="text-xs text-muted-foreground">—</span>;
  return <span className="whitespace-nowrap"><Mono>{pct(r.rate)}</Mono> <Mono className="text-[10px] text-muted-foreground">{r.k}/{r.n} {ci(r)}</Mono></span>;
}

function F({ label, value, onChange, opts }: { label: string; value: string; onChange: (v: string) => void; opts: [string, string][] }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 w-36 text-xs" aria-label={label}><SelectValue /></SelectTrigger>
      <SelectContent>{opts.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
    </Select>
  );
}
