import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { supervisorService } from "@/services";
import type { UnsafeCase } from "@/services/types";
import { AutonomyBadge, IntervalBar, Mono, OutcomeBadge, PageHeader } from "@/components/beta/badges";
import { TracePanel } from "@/components/beta/TracePanel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useI18n, useTx } from "@/lib/i18n";

export const Route = createFileRoute("/supervisor")({
  head: () => ({
    meta: [
      { title: "Supervisor — BETA AID" },
      { name: "description", content: "Copilot KPIs with 95% intervals, unsafe case drill-down and the versioned autonomy policy." },
      { property: "og:title", content: "Supervisor — BETA AID" },
      { property: "og:description", content: "Copilot KPIs with 95% intervals and the versioned autonomy policy." },
    ],
  }),
  component: SupervisorPage,
});

function SupervisorPage() {
  const { t } = useI18n();
  const tx = useTx();
  const { data: kpis } = useQuery({ queryKey: ["kpis"], queryFn: supervisorService.kpis });
  const { data: unsafe } = useQuery({ queryKey: ["unsafe"], queryFn: supervisorService.unsafe });
  const { data: policy } = useQuery({ queryKey: ["policy"], queryFn: supervisorService.policy });
  const [lang, setLang] = useState("all");
  const [region, setRegion] = useState("all");
  const [date, setDate] = useState("7d");
  const [drill, setDrill] = useState<UnsafeCase | null>(null);
  const rows = (unsafe ?? []).filter((u) => (lang === "all" || u.lang === lang) && (region === "all" || u.region === region));

  const filters = (
    <div className="flex flex-wrap gap-2">
      <F label="Idioma" value={lang} onChange={setLang} opts={[["all", "ES + PT"], ["es", "ES"], ["pt", "PT"]]} />
      <F label="Región" value={region} onChange={setRegion} opts={[["all", "MX · CO · AR"], ["MX", "MX"], ["CO", "CO"], ["AR", "AR"]]} />
      <F label="Fecha" value={date} onChange={setDate} opts={[["24h", "24 h"], ["7d", "7 d"], ["30d", "30 d"]]} />
    </div>
  );

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow={tx("Atención al cliente", "Atendimento", "Customer service")} title="Supervisor" actions={filters} />
      <Tabs defaultValue="kpis">
        <TabsList><TabsTrigger value="kpis">KPIs</TabsTrigger><TabsTrigger value="policy">{tx("Política", "Política", "Policy")}</TabsTrigger></TabsList>
        <TabsContent value="kpis" className="mt-4 space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {kpis?.map((k) => {
              const scale = k.id === "p50" || k.id === "p95" ? 30 : k.id === "cost" ? 0.005 : ["missed", "unnecessary", "unsafe"].includes(k.id) ? 0.25 : 1;
              const min = scale === 1 ? 0.5 : 0;
              return (
                <div key={k.id} className="panel p-4">
                  <div className="text-xs text-muted-foreground">{t(k.label)}</div>
                  <div className="mt-1 flex items-baseline gap-2"><span className="font-mono text-2xl font-semibold">{k.display}</span><span className="text-[11px] text-muted-foreground">{k.better === "higher" ? "↑" : "↓"} {tx("mejor", "melhor", "better")}</span></div>
                  <IntervalBar className="mt-3" value={k.value} lo={k.lo} hi={k.hi} min={min} max={scale} />
                  <div className="mt-1 font-mono text-[10px] text-muted-foreground">IC 95 % [{k.lo}, {k.hi}]</div>
                </div>
              );
            })}
          </div>
          <div className="panel overflow-x-auto">
            <div className="border-b px-4 py-2.5 text-sm font-semibold">{tx("Casos recientes inseguros o fallidos", "Casos recentes inseguros ou com falha", "Recent unsafe or failed cases")}</div>
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
        <TabsContent value="policy" className="mt-4 grid gap-4 lg:grid-cols-[3fr_2fr]">
          <div className="panel overflow-x-auto">
            <div className="border-b px-4 py-2.5 text-sm font-semibold">intent → autonomy → queue <Mono className="ml-2 text-muted-foreground">{policy?.version}</Mono></div>
            <table className="w-full text-sm"><tbody>
              {policy?.rows.map((r) => (
                <tr key={r.intent} className="border-b last:border-0"><td className="px-4 py-2"><Mono>{r.intent}</Mono></td><td className="px-2"><AutonomyBadge level={r.autonomy} /></td><td className="px-2"><Mono>{r.queue}</Mono></td><td className="px-2 text-xs text-muted-foreground"><Mono>{r.rule}</Mono></td></tr>
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

function F({ label, value, onChange, opts }: { label: string; value: string; onChange: (v: string) => void; opts: [string, string][] }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 w-36 text-xs" aria-label={label}><SelectValue /></SelectTrigger>
      <SelectContent>{opts.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
    </Select>
  );
}
