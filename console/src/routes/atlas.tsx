import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { atlasService } from "@/services";
import type { AtlasCell } from "@/services/types";
import { IntervalBar, Mono, PageHeader, StatusBadge, VerdictBadge } from "@/components/beta/badges";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useTx } from "@/lib/i18n";

export const Route = createFileRoute("/atlas")({
  head: () => ({
    meta: [
      { title: "Readiness atlas — BETA AID" },
      { name: "description", content: "Gate verdicts for every candidate model by grain, with gains, 95% intervals, MDE and root causes." },
      { property: "og:title", content: "Readiness atlas — BETA AID" },
      { property: "og:description", content: "Gate verdicts for every candidate model by grain, with honest evidence." },
    ],
  }),
  component: AtlasPage,
});

const fmt = (n?: number) => (n === undefined ? "—" : (n >= 0 ? "+" : "") + n.toFixed(3).replace(".", ","));

function AtlasPage() {
  const tx = useTx();
  const { data } = useQuery({ queryKey: ["atlas"], queryFn: atlasService.matrix });
  const [sel, setSel] = useState<AtlasCell | null>(null);
  const count = (v: string) => data?.cells.filter((c) => c.verdict === v).length ?? 0;
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow={tx("Plano de control de datos", "Plano de controle de dados", "Data control plane")} title={tx("Atlas de preparación", "Atlas de prontidão", "Readiness atlas")}
        actions={<div className="flex gap-1.5"><StatusBadge status="ok" mono>{count("green")} green</StatusBadge><StatusBadge status="review" mono>{count("amber")} amber</StatusBadge><StatusBadge status="blocked" mono>{count("red")} red</StatusBadge></div>}>
        {tx("Ningún modelo pasa el gate todavía. «0 green» es el estado honesto: cada celda roja nombra la causa y el requisito de datos que la desbloquea.", "Nenhum modelo passa no gate ainda. «0 green» é o estado honesto.", "No model passes the gate yet. “0 green” is the honest state: every red cell names its cause and the data requirement that unblocks it.")}
      </PageHeader>
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead><tr className="border-b text-left text-xs text-muted-foreground"><th className="px-4 py-2 font-medium">model</th>{data?.grains.map((g) => <th key={g} className="px-2 py-2 font-mono font-medium">{g}</th>)}</tr></thead>
          <tbody>
            {data?.models.map((m) => (
              <tr key={m} className="border-b last:border-0">
                <td className="px-4 py-3 font-medium">{m}</td>
                {data.grains.map((g) => {
                  const c = data.cells.find((x) => x.model === m && x.grain === g);
                  if (!c) return <td key={g} className="px-2 py-3"><span className="text-xs text-muted-foreground">{tx("no evaluado", "não avaliado", "not evaluated")}</span></td>;
                  return (
                    <td key={g} className="px-2 py-3 align-top">
                      <button onClick={() => setSel(c)} className="w-full rounded-lg border p-2.5 text-left hover:border-primary">
                        <div className="flex items-center justify-between gap-2"><VerdictBadge verdict={c.verdict!} /><Mono>{fmt(c.gain)}</Mono></div>
                        <IntervalBar className="mt-2" value={c.gain!} lo={c.lo!} hi={c.hi!} min={-0.04} max={0.06} threshold={c.materiality} />
                        <div className="mt-1.5 font-mono text-[10px] text-muted-foreground">[{fmt(c.lo)}, {fmt(c.hi)}] · mat {c.materiality} · MDE {c.mde}</div>
                        {c.root_cause && <div className="mt-1 text-[11px] text-blocked">{c.root_cause}</div>}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">{tx("Línea naranja = umbral de materialidad. Banda = IC 95 % de la ganancia.", "Linha laranja = limiar de materialidade.", "Orange line = materiality threshold. Band = 95% CI of the gain.")}</p>

      <Sheet open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent className="w-[480px] overflow-y-auto sm:max-w-[480px]">
          {sel && (
            <>
              <SheetHeader><SheetTitle>{sel.model} · <Mono>{sel.grain}</Mono></SheetTitle></SheetHeader>
              <div className="mt-4 space-y-4 text-sm">
                <div className="flex flex-wrap gap-2"><VerdictBadge verdict={sel.verdict!} />{sel.root_cause && <StatusBadge status="blocked">{sel.root_cause}</StatusBadge>}</div>
                <Ev k={tx("Resultado fuera de tiempo", "Resultado fora do tempo", "Out-of-time result")} v={sel.oot} />
                <Ev k="Benchmark" v={sel.benchmark} />
                <Ev k={tx("Requisito de datos implicado", "Requisito de dados implicado", "Implied data requirement")} v={sel.requirement} />
                <div>
                  <div className="eyebrow mb-2">{tx("Sonda de modelo fundacional", "Sonda de modelo fundacional", "Foundation-model probe")}</div>
                  {sel.kumo ? sel.kumo.map((k) => (
                    <div key={k.variant} className="mb-3 rounded-lg border p-3">
                      <div className="flex justify-between"><span className="font-medium">{k.variant}</span><Mono>{fmt(k.gain)} [{fmt(k.lo)}, {fmt(k.hi)}]</Mono></div>
                      <IntervalBar className="mt-2" value={k.gain} lo={k.lo} hi={k.hi} min={-0.04} max={0.06} threshold={sel.materiality} />
                      <div className="mt-2 text-[11px] text-muted-foreground">{tx("Ablación por tabla", "Ablação por tabela", "Ablation by table")}</div>
                      {k.ablation.map((a) => <div key={a.table} className="flex justify-between text-xs"><Mono>−{a.table}</Mono><Mono>{fmt(a.delta)}</Mono></div>)}
                    </div>
                  )) : <p className="text-xs text-muted-foreground">{tx("Sonda no ejecutada para esta celda.", "Sonda não executada.", "Probe not run for this cell.")}</p>}
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function Ev({ k, v }: { k: string; v?: string | undefined }) {
  return <div><div className="eyebrow mb-0.5">{k}</div><p>{v ?? "—"}</p></div>;
}
