import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { readinessService } from "@/services";
import type { ReadinessRow } from "@/services/types";
import { IntervalBar, Mono, PageHeader, StatusBadge, VerdictBadge } from "@/components/beta/badges";
import { ForestPlot } from "@/components/beta/plots";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useTx } from "@/lib/i18n";

export const Route = createFileRoute("/atlas")({
  head: () => ({
    meta: [
      { title: "Readiness atlas — BETA AID" },
      { name: "description", content: "Gate verdicts for every candidate model, with out-of-time gains, 95% intervals, MDE and root causes." },
      { property: "og:title", content: "Readiness atlas — BETA AID" },
      { property: "og:description", content: "Gate verdicts for every candidate model, with honest evidence." },
    ],
  }),
  component: AtlasPage,
});

const fmt = (n: number) => (n >= 0 ? "+" : "") + n.toFixed(4).replace(".", ",");
const int = (n: number | null) => (n === null ? "—" : n.toLocaleString("es"));

function AtlasPage() {
  const tx = useTx();
  const { data, isError, error, isLoading } = useQuery({ queryKey: ["control", "readiness"], queryFn: () => readinessService.get() });
  const [sel, setSel] = useState<ReadinessRow | null>(null);
  const [relative, setRelative] = useState(false);
  const counts = data?.counts;
  const pending = tx("Sonda de modelo fundacional (Kumo) — pendiente", "Sonda de modelo fundacional (Kumo) — pendente", "Foundation-model probe (Kumo) — pending");
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow={tx("Plano de control de datos", "Plano de controle de dados", "Data control plane")} title={tx("Atlas de preparación", "Atlas de prontidão", "Readiness atlas")}
        actions={<div className="flex gap-1.5"><StatusBadge status="ok" mono>{counts?.green ?? "–"} green</StatusBadge><StatusBadge status="review" mono>{counts?.amber ?? "–"} amber</StatusBadge><StatusBadge status="blocked" mono>{counts?.red ?? "–"} red</StatusBadge></div>}>
        {tx("Ningún modelo pasa el gate todavía. «0 green» es el estado honesto: cada fila roja nombra la causa y el requisito de datos que la desbloquea.", "Nenhum modelo passa no gate ainda. «0 green» é o estado honesto: cada linha vermelha nomeia a causa e o requisito de dados que a desbloqueia.", "No model passes the gate yet. “0 green” is the honest state: every red row names its cause and the data requirement that unblocks it.")}
      </PageHeader>

      {isLoading && <p className="text-sm text-muted-foreground">{tx("Cargando el scorecard…", "Carregando o scorecard…", "Loading the scorecard…")}</p>}
      {isError && <div className="panel p-4 text-sm text-blocked">{tx("No se pudo leer /api/control/readiness", "Não foi possível ler /api/control/readiness", "Could not read /api/control/readiness")}: <Mono>{error instanceof Error ? error.message : String(error)}</Mono></div>}

      {data && (
        <>
          <div className="panel mb-6 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-semibold">{tx("Ganancia fuera de tiempo vs. benchmark", "Ganho fora do tempo vs. benchmark", "Out-of-time gain over the benchmark")}</div>
                <div className="text-[11px] text-muted-foreground">{tx("Punto = ganancia; barra = IC 95 %; línea = 0; marca naranja = +materialidad.", "Ponto = ganho; barra = IC 95 %; linha = 0; marca laranja = +materialidade.", "Dot = gain; bar = 95% CI; rule = 0; orange tick = +materiality.")}</div>
              </div>
              <div className="flex gap-1 text-xs" role="group" aria-label={tx("Escala", "Escala", "Scale")}>
                <ScaleButton on={!relative} onClick={() => setRelative(false)}>{tx("absoluta", "absoluta", "absolute")}</ScaleButton>
                <ScaleButton on={relative} onClick={() => setRelative(true)}>÷ {tx("materialidad", "materialidade", "materiality")}</ScaleButton>
              </div>
            </div>
            <ForestPlot rows={data.models} relative={relative} label={tx("Forest plot de la preparación de modelos", "Forest plot da prontidão dos modelos", "Model readiness forest plot")} />
          </div>

          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[880px] text-sm">
              <thead><tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-2 font-medium">{tx("escenario · modelo", "cenário · modelo", "scenario · model")}</th>
                <th className="px-2 py-2 font-mono font-medium">hour</th>
                <th className="px-2 py-2 font-medium">{pending}</th>
              </tr></thead>
              <tbody>
                {data.models.map((c) => {
                  const span = Math.max(Math.abs(c.delta_lo), Math.abs(c.delta_hi), c.material) * 1.2;
                  return (
                    <tr key={`${c.scenario}|${c.model}`} className="border-b last:border-0">
                      <td className="px-4 py-3 align-top"><div className="text-[11px] text-muted-foreground">{c.scenario}</div><div className="font-medium">{c.model}</div><Mono className="text-[11px] text-muted-foreground">{c.metric} · vs {c.benchmark}</Mono></td>
                      <td className="w-[340px] px-2 py-3 align-top">
                        <button onClick={() => setSel(c)} className="w-full rounded-lg border p-2.5 text-left hover:border-primary">
                          <div className="flex items-center justify-between gap-2"><VerdictBadge verdict={c.verdict} /><Mono>{fmt(c.delta)}</Mono></div>
                          <IntervalBar className="mt-2" value={c.delta} lo={c.delta_lo} hi={c.delta_hi} min={-span} max={span} threshold={c.material} />
                          <div className="mt-1.5 font-mono text-[10px] text-muted-foreground">[{fmt(c.delta_lo)}, {fmt(c.delta_hi)}] · mat {c.material} · MDE {c.mde.toFixed(4)}</div>
                          <div className={`mt-1 text-[11px] ${c.verdict === "red" ? "text-blocked" : "text-review"}`}>{c.root_cause}</div>
                        </button>
                      </td>
                      <td className="px-2 py-3 align-top"><span className="text-xs text-muted-foreground">{tx("pendiente", "pendente", "pending")}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">{tx("Línea naranja = umbral de materialidad. Banda = IC 95 % de la ganancia. Fuente", "Linha laranja = limiar de materialidade. Faixa = IC 95 % do ganho. Fonte", "Orange line = materiality threshold. Band = 95% CI of the gain. Source")}: <Mono>{data.source}</Mono></p>
        </>
      )}

      <Sheet open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent className="w-[480px] overflow-y-auto sm:max-w-[480px]">
          {sel && (
            <>
              <SheetHeader><SheetTitle>{sel.model} · <Mono>hour</Mono></SheetTitle></SheetHeader>
              <div className="mt-4 space-y-4 text-sm">
                <div className="flex flex-wrap gap-2"><VerdictBadge verdict={sel.verdict} /><StatusBadge status={sel.verdict === "red" ? "blocked" : "review"}>{sel.root_cause}</StatusBadge></div>
                <Ev k={tx("Causa raíz", "Causa raiz", "Root cause")} v={sel.root_cause} />
                <Ev k={tx("Requisito para llegar a green", "Requisito para chegar a green", "Requirement to green")} v={sel.requirement_to_green} />
                <Ev k={tx("Resultado fuera de tiempo", "Resultado fora do tempo", "Out-of-time result")} v={`${sel.metric}: ${sel.value.toFixed(4)} vs ${sel.benchmark_value.toFixed(4)} · Δ ${fmt(sel.delta)} [${fmt(sel.delta_lo)}, ${fmt(sel.delta_hi)}]`} />
                <Ev k="Benchmark" v={sel.benchmark} />
                <Ev k={tx("Materialidad · MDE", "Materialidade · MDE", "Materiality · MDE")} v={`+${sel.material} · ${sel.mde.toFixed(4)}`} />
                <Ev k="n train · n test · n test needed" v={`${int(sel.n_train)} · ${int(sel.n_test)} · ${int(sel.n_test_needed)}`} />
                {sel.best_variant && <Ev k={tx("Mejor variante", "Melhor variante", "Best variant")} v={sel.best_variant} />}
                <div>
                  <div className="eyebrow mb-2">{tx("Sonda de modelo fundacional", "Sonda de modelo fundacional", "Foundation-model probe")}</div>
                  <p className="text-xs text-muted-foreground">{pending}</p>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function ScaleButton({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return <button onClick={onClick} aria-pressed={on} className={`rounded-md border px-2 py-1 ${on ? "border-primary text-primary" : "text-muted-foreground"}`}>{children}</button>;
}

function Ev({ k, v }: { k: string; v?: string | undefined }) {
  return <div><div className="eyebrow mb-0.5">{k}</div><p>{v || "—"}</p></div>;
}
