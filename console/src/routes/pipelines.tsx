import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowDown, CheckCircle2, MapPin, XCircle } from "lucide-react";
import { pipelineService } from "@/services";
import { Mono, PageHeader, StatusBadge, verdictStatus } from "@/components/beta/badges";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useTx } from "@/lib/i18n";

export const Route = createFileRoute("/pipelines")({
  head: () => ({
    meta: [
      { title: "Pipelines — BETA AID" },
      { name: "description", content: "Scope by layer pipeline status with reconciliation, quality and governance gates, residency and lineage." },
      { property: "og:title", content: "Pipelines — BETA AID" },
      { property: "og:description", content: "Pipeline status, gates, data residency and lineage per model." },
    ],
  }),
  component: PipelinesPage,
});

const statusLabel = { ok: "ok", review: "review", blocked: "blocked", info: "running" } as const;

function PipelinesPage() {
  const tx = useTx();
  const { data } = useQuery({ queryKey: ["pipes"], queryFn: pipelineService.grid });
  const { data: residency } = useQuery({ queryKey: ["residency"], queryFn: pipelineService.residency });
  const { data: lineage } = useQuery({ queryKey: ["lineage"], queryFn: pipelineService.lineage });
  const [model, setModel] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader eyebrow={tx("Plano de control de datos", "Plano de controle de dados", "Data control plane")} title="Pipelines"
        actions={<div className="flex flex-wrap gap-1.5">{lineage && Object.keys(lineage).map((m) => <Button key={m} size="sm" variant="outline" onClick={() => setModel(m)}>{tx("Linaje", "Linhagem", "Lineage")}: {m}</Button>)}</div>} />
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[1100px] text-xs">
          <thead><tr className="border-b text-left text-muted-foreground"><th className="px-3 py-2 font-medium">scope</th>{data?.layers.map((l) => <th key={l} className="px-1.5 py-2 font-mono font-medium">{l}</th>)}</tr></thead>
          <tbody>
            {data?.scopes.map((s) => (
              <tr key={s} className="border-b last:border-0">
                <td className="px-3 py-2 font-mono font-semibold">{s}</td>
                {data.layers.map((l) => {
                  const c = data.cells.find((x) => x.scope === s && x.layer === l)!;
                  return (
                    <td key={l} className="px-1.5 py-2 align-top">
                      <div className="rounded-lg border p-2">
                        <StatusBadge status={c.status} mono>{statusLabel[c.status]}</StatusBadge>
                        <div className="mt-1 font-mono text-[10px] text-muted-foreground">{c.last_run} · {c.rows.toLocaleString("es-AR")}</div>
                        <div className="mt-1 flex items-center gap-1 text-[10px]">
                          {c.reconciled ? <span className="inline-flex items-center gap-0.5 text-ok"><CheckCircle2 className="size-3" aria-hidden />rec ✔</span> : <span className="inline-flex items-center gap-0.5 text-blocked"><XCircle className="size-3" aria-hidden />rec ✘</span>}
                        </div>
                        <div className="mt-1 flex gap-1"><StatusBadge status={verdictStatus[c.quality_gate]} className="px-1 text-[9px]">Q</StatusBadge><StatusBadge status={verdictStatus[c.governance_gate]} className="px-1 text-[9px]">G</StatusBadge></div>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">Q = quality gate · G = governance gate · rec = reconcile</p>

      <div className="panel mt-6 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><MapPin className="size-4" aria-hidden />{tx("Residencia de datos", "Residência de dados", "Data residency")}</div>
        <div className="grid gap-3 md:grid-cols-3">
          {residency?.map((r) => (
            <div key={r.scope} className="rounded-lg border p-3">
              <div className="flex items-center gap-2"><Mono className="text-base font-semibold">{r.scope}</Mono><span className="text-muted-foreground">→</span><span className="font-medium">{r.region}</span></div>
              <Mono className="text-muted-foreground">{r.gcp}</Mono>
              <p className="mt-1 text-xs">{r.basis}</p>
            </div>
          ))}
        </div>
      </div>

      <Sheet open={!!model} onOpenChange={(o) => !o && setModel(null)}>
        <SheetContent>
          <SheetHeader><SheetTitle>{tx("Linaje", "Linhagem", "Lineage")} · {model}</SheetTitle></SheetHeader>
          <ol className="mt-6 space-y-1">
            {model && lineage?.[model]?.map((n, i, arr) => (
              <li key={n} className="flex flex-col items-center">
                <div className="w-full rounded-lg border px-3 py-2 text-center font-mono text-xs">{n}</div>
                {i < arr.length - 1 && <ArrowDown className="my-1 size-4 text-muted-foreground" aria-hidden />}
              </li>
            ))}
          </ol>
        </SheetContent>
      </Sheet>
    </div>
  );
}
