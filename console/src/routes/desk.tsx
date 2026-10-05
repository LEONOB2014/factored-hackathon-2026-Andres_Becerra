import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CheckCircle2, Clock, Link2, Square, CheckSquare, XCircle, Flame } from "lucide-react";
import { toast } from "sonner";
import { demoService, deskService } from "@/services";
import { ApiError, REGIONS, type RegionId } from "@/services/api";
import type { DeskCase, Queue } from "@/services/types";
import { Mono, PageHeader, StatusBadge } from "@/components/beta/badges";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useI18n, useTx } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/desk")({
  head: () => ({
    meta: [
      { title: "Agent desk — BETA AID" },
      { name: "description", content: "Human-in-the-loop queues and handoff packets with verified facts, cited procedures and four-eyes approvals." },
      { property: "og:title", content: "Agent desk — BETA AID" },
      { property: "og:description", content: "Human-in-the-loop queues and handoff packets with four-eyes approvals." },
    ],
  }),
  component: DeskPage,
});

// Test staff identities: the desk acts as one of them; approving needs a different one (four eyes, enforced by the API).
const STAFF = ["agente.ana", "agente.bruno", "lider.carla"];

function DeskPage() {
  const { t } = useI18n();
  const tx = useTx();
  const qc = useQueryClient();
  const [region, setRegion] = useState<RegionId>("mx");
  const [me, setMe] = useState<string>("agente.ana");
  const { data: demo } = useQuery({ queryKey: ["demo", region], queryFn: () => demoService.info(region) });
  const { data: cases = [], error } = useQuery({
    queryKey: ["cases", region],
    queryFn: () => deskService.cases(region, demo!.staff),
    enabled: !!demo,
    refetchInterval: 4000,
  });
  const queues = deskService.queues(cases);
  const [queue, setQueue] = useState<Queue | "all">("all");
  const [selId, setSelId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [code, setCode] = useState("");

  useEffect(() => {
    if (!selId && cases[0]) setSelId(cases[0].packet.handoff_id);
  }, [cases, selId]);

  const visible = cases.filter((c) => queue === "all" || c.packet.queue === queue);
  const sel = cases.find((c) => c.packet.handoff_id === selId);

  async function act(status: string, note = "") {
    if (!sel || !demo) return;
    try {
      await deskService.setStatus(region, demo.staff, sel.packet.handoff_id, status, me, note);
      await qc.invalidateQueries({ queryKey: ["cases", region] });
      toast.success(`${status} · ${me}`);
    } catch (e) {
      const four = e instanceof ApiError && e.status === 409;
      toast.error(four ? tx("Cuatro ojos: quien propone no puede aprobar. Cambia de identidad.", "Quatro olhos: quem propõe não pode aprovar. Troque de identidade.", "Four eyes: the proposer cannot approve. Switch identity.") : String(e));
    }
  }

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader eyebrow={tx("Humano en el circuito", "Humano no circuito", "Human in the loop")} title={tx("Mesa de agentes", "Mesa de agentes", "Agent desk")} />
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="eyebrow">{tx("Región", "Região", "Region")}</span>
        {REGIONS.map((r) => (
          <button key={r.id} aria-pressed={region === r.id} onClick={() => { setRegion(r.id); setSelId(null); }} className={cn("rounded-md border px-2 py-1", region === r.id ? "border-primary bg-accent font-medium" : "border-border")}>{r.label}</button>
        ))}
        <span className="eyebrow ml-4">{tx("Actuando como", "Atuando como", "Acting as")}</span>
        <Select value={me} onValueChange={setMe}>
          <SelectTrigger className="h-8 w-40 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{STAFF.map((s2) => <SelectItem key={s2} value={s2}>{s2}</SelectItem>)}</SelectContent>
        </Select>
        <span className="text-muted-foreground">{tx("Casos reales de esta región; se actualiza cada 4 s.", "Casos reais desta região; atualiza a cada 4 s.", "Real cases from this region; refreshes every 4 s.")}</span>
      </div>
      {error && <p role="alert" className="mb-2 text-xs text-blocked">{String(error)}</p>}
      {cases.length === 0 && !error && (
        <p className="panel mb-3 p-4 text-sm text-muted-foreground">{tx("Aún no hay casos. Genera uno desde el chat (p. ej. «¿por qué rechazaron mi tarjeta?» con «Tarjeta con alerta de fraude», o «me cobraron dos veces»).", "Ainda não há casos. Gere um pelo chat (ex.: «me cobraram duas vezes»).", "No cases yet. Create one from the chat (e.g. a fraud-flag card or a double charge).")}</p>
      )}
      <div className="grid gap-4 xl:grid-cols-[220px_300px_minmax(0,1fr)] lg:grid-cols-[200px_minmax(0,1fr)]">
        <div className="panel h-fit p-2">
          <button onClick={() => setQueue("all")} aria-pressed={queue === "all"} className={cn("mb-1 w-full rounded-md px-2.5 py-2 text-left text-sm", queue === "all" && "bg-accent font-semibold")}>{tx("Todas", "Todas", "All")}</button>
          {queues.map((q) => (
            <button key={q.id} onClick={() => setQueue(q.id)} aria-pressed={queue === q.id} className={cn("flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left text-sm hover:bg-muted", queue === q.id && "bg-accent font-semibold")}>
              <span className="flex items-center gap-1.5">{q.priority === "high" && <Flame className="size-3.5 text-highlight" aria-label="high priority" />}{t(`queue.${q.id}`)}</span>
              <span className="flex items-center gap-2 text-[11px] text-muted-foreground"><Clock className="size-3" aria-hidden />{q.sla}<Mono className="rounded bg-muted px-1.5 text-foreground">{q.count}</Mono></span>
            </button>
          ))}
        </div>

        <div className="space-y-2">
          {visible.map((c) => {
            const left = c.sla_minutes - c.elapsed_minutes;
            const pct = c.elapsed_minutes / c.sla_minutes;
            return (
              <button key={c.packet.handoff_id} onClick={() => setSelId(c.packet.handoff_id)} className={cn("panel w-full p-3 text-left hover:border-primary", selId === c.packet.handoff_id && "border-primary ring-1 ring-primary")}>
                <div className="flex items-center justify-between gap-2"><Mono>{c.packet.handoff_id}</Mono>{c.packet.priority === "high" && <StatusBadge status="blocked">high</StatusBadge>}</div>
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{c.packet.request}</p>
                <div className="mt-2 flex items-center gap-2 text-[11px]">
                  <span className="font-medium">{t(`queue.${c.packet.queue}`)}</span>
                  <StatusBadge status={pct > 0.5 ? "review" : "ok"} mono>SLA {left >= 60 ? `${Math.floor(left / 60)} h` : `${left} min`}</StatusBadge>
                  <StatusBadge status={c.status === "resolved" || c.status === "approved" ? "ok" : c.status === "approval_requested" ? "review" : c.status === "rejected" ? "blocked" : "info"} mono>{c.status}</StatusBadge>
                </div>
              </button>
            );
          })}
        </div>

        {sel && (
          <div className="panel min-w-0 lg:col-span-2 xl:col-span-1">
            <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
              <Mono className="font-semibold">{sel.packet.handoff_id}</Mono>
              <span className="text-xs text-muted-foreground">· {sel.packet.customer_id} · {sel.packet.language.toUpperCase()} · {sel.packet.authentication}</span>
              <span className="ml-auto text-xs text-muted-foreground"><Mono>{sel.packet.policy.rule}</Mono> · {sel.packet.policy.version}</span>
            </div>
            <div className="grid gap-4 p-4 2xl:grid-cols-2">
              <section>
                <h3 className="eyebrow mb-1">{tx("Solicitud (enmascarada)", "Solicitação (mascarada)", "Request (masked)")}</h3>
                <p className="text-sm">{sel.packet.request}</p>
                <p className="mt-1 text-xs text-muted-foreground">intent <Mono>{sel.packet.intent.label}</Mono> · <Mono>{sel.packet.intent.confidence}</Mono> · {sel.packet.intent.source}</p>
                <h3 className="eyebrow mb-1 mt-4">{tx("Hechos verificados", "Fatos verificados", "Verified facts")}</h3>
                <table className="w-full text-xs"><tbody>
                  {Object.entries(sel.packet.verified_facts ?? {}).map(([k, v]) => (
                    <tr key={k} className="border-b last:border-0"><td className="py-1 pr-2 text-muted-foreground">{k}</td><td className="py-1 font-mono">{String(v)}</td></tr>
                  ))}
                </tbody></table>
                <h3 className="eyebrow mb-1 mt-4">{tx("Acciones realizadas", "Ações realizadas", "Actions taken")}</h3>
                {sel.packet.actions_taken.length === 0 ? <p className="text-xs text-muted-foreground">—</p> : sel.packet.actions_taken.map((a) => (
                  <div key={a.action_id} className="flex flex-wrap items-center gap-2 text-xs"><Mono>{a.action_id}</Mono>{a.action}<Mono className="text-muted-foreground">{a.product_id}</Mono>
                    {a.read_back ? <span className="inline-flex items-center gap-1 text-ok"><CheckCircle2 className="size-3" aria-hidden />read-back ✔</span> : <span className="inline-flex items-center gap-1 text-blocked"><XCircle className="size-3" aria-hidden />read-back ✘</span>}
                  </div>
                ))}
                <h3 className="eyebrow mb-1 mt-4">{tx("Procedimientos internos", "Procedimentos internos", "Internal procedures")}</h3>
                {sel.packet.procedures.length === 0 && <p className="text-xs text-muted-foreground">—</p>}
                {sel.packet.procedures.map((p) => (
                  <blockquote key={p.cite} className="mb-2 border-l-2 border-primary bg-muted/50 px-3 py-2 text-xs">
                    <div className="font-mono font-semibold">{p.cite} · {p.heading}</div>
                    <p className="mt-1">{p.text}</p>
                    <div className="mt-1 text-[10px] text-muted-foreground">{p.classification} · score {p.score}</div>
                  </blockquote>
                ))}
              </section>
              <section>
                <h3 className="eyebrow mb-1">{tx("Preguntas abiertas", "Perguntas em aberto", "Open questions")}</h3>
                <ul className="space-y-1">
                  {sel.packet.open_questions.map((q) => {
                    const k = sel.packet.handoff_id + q;
                    return (
                      <li key={q}><button onClick={() => setChecked((c) => ({ ...c, [k]: !c[k] }))} role="checkbox" aria-checked={!!checked[k]} className="flex items-start gap-2 text-left text-sm">
                        {checked[k] ? <CheckSquare className="mt-0.5 size-4 shrink-0 text-primary" /> : <Square className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}<span className={cn(checked[k] && "line-through opacity-60")}>{q}</span>
                      </button></li>
                    );
                  })}
                </ul>
                <h3 className="eyebrow mb-1 mt-4">{tx("Transcripción", "Transcrição", "Transcript")}</h3>
                <div className="space-y-1.5 rounded-md bg-muted/50 p-2.5 text-xs">
                  {sel.packet.transcript.map((m, i) => <p key={i}><b className="font-mono text-[10px] uppercase">{m.role}</b> {m.text}</p>)}
                </div>
                <h3 className="eyebrow mb-1 mt-4">{tx("Acciones del agente", "Ações do agente", "Agent actions")}</h3>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={!["new", "returned"].includes(sel.status)} onClick={() => act("accepted")}>{tx("Aceptar", "Aceitar", "Accept")}</Button>
                  <Button size="sm" variant="outline" disabled={!["new", "accepted"].includes(sel.status)} onClick={() => act("returned")}>{tx("Devolver al copiloto", "Devolver ao copiloto", "Return to copilot")}</Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Select value={code} onValueChange={setCode}>
                    <SelectTrigger className="h-8 w-48 text-xs"><SelectValue placeholder={tx("Código de resolución", "Código de resolução", "Resolution code")} /></SelectTrigger>
                    <SelectContent>{["RES-FIXED", "RES-CHARGEBACK", "RES-NO-FRAUD", "RES-INFO-GIVEN", "RES-REJECTED"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                  <Button size="sm" variant="secondary" disabled={!code || !["accepted", "approved", "rejected"].includes(sel.status)} onClick={() => act("resolved", code)}>{tx("Resolver", "Resolver", "Resolve")}</Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" disabled={sel.status !== "accepted"} onClick={() => act("approval_requested", code || "sensitive action")}>{tx("Pedir segunda aprobación", "Pedir segunda aprovação", "Request second approval")}</Button>
                  <Button size="sm" disabled={sel.status !== "approval_requested"} onClick={() => act("approved")}>{tx("Aprobar", "Aprovar", "Approve")}</Button>
                  <Button size="sm" variant="outline" disabled={sel.status !== "approval_requested"} onClick={() => act("rejected")}>{tx("Rechazar", "Rejeitar", "Reject")}</Button>
                </div>
                <h3 className="eyebrow mb-1 mt-4">Timeline</h3>
                <ol className="space-y-1">
                  {sel.timeline.map((e, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-2 text-xs"><Mono className="text-muted-foreground">{e.at}</Mono><Mono>{e.event}</Mono><span className="text-muted-foreground">{e.actor}</span>
                      <StatusBadge status="ok" mono className="ml-auto"><Link2 className="size-3" aria-hidden />{e.hash}</StatusBadge></li>
                  ))}
                </ol>
              </section>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
