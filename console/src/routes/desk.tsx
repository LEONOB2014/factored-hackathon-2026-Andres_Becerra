import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CheckCircle2, Clock, Link2, Square, CheckSquare, XCircle, Flame } from "lucide-react";
import { toast } from "sonner";
import { deskService } from "@/services";
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

const ME = "l.moreno";
const fakeHash = () => `${Math.random().toString(16).slice(2, 6)}…${Math.random().toString(16).slice(2, 6)}`;
const now = () => new Date().toTimeString().slice(0, 8);

function DeskPage() {
  const { t } = useI18n();
  const tx = useTx();
  const { data: queues } = useQuery({ queryKey: ["queues"], queryFn: deskService.queues });
  const { data: initial } = useQuery({ queryKey: ["cases"], queryFn: deskService.cases });
  const [cases, setCases] = useState<DeskCase[]>([]);
  const [queue, setQueue] = useState<Queue | "all">("all");
  const [selId, setSelId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [code, setCode] = useState("");
  const [approver, setApprover] = useState("");

  useEffect(() => {
    if (initial) { setCases(initial); setSelId(initial[0]?.packet.handoff_id ?? null); }
  }, [initial]);

  const visible = cases.filter((c) => queue === "all" || c.packet.queue === queue);
  const sel = cases.find((c) => c.packet.handoff_id === selId);

  function update(fn: (c: DeskCase) => DeskCase) {
    setCases((cs) => cs.map((c) => (c.packet.handoff_id === selId ? fn(c) : c)));
  }
  const log = (c: DeskCase, event: string, actor = `agent:${ME}`) => ({ ...c, timeline: [...c.timeline, { at: now(), event, actor, hash: fakeHash() }] });

  function requestApproval() {
    if (!approver) { toast.error(tx("Elige un aprobador", "Escolha um aprovador", "Pick an approver")); return; }
    if (approver === ME) { toast.error(tx("Cuatro ojos: el aprobador debe ser distinto del proponente.", "Quatro olhos: o aprovador deve ser diferente do proponente.", "Four eyes: approver must differ from proposer.")); return; }
    update((c) => log({ ...c, status: "pending_approval" }, `approval.requested approver=${approver}`));
    toast.success(tx("Segunda aprobación solicitada", "Segunda aprovação solicitada", "Second approval requested"));
  }

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader eyebrow={tx("Humano en el circuito", "Humano no circuito", "Human in the loop")} title={tx("Mesa de agentes", "Mesa de agentes", "Agent desk")} />
      <div className="grid gap-4 xl:grid-cols-[220px_300px_minmax(0,1fr)] lg:grid-cols-[200px_minmax(0,1fr)]">
        <div className="panel h-fit p-2">
          <button onClick={() => setQueue("all")} aria-pressed={queue === "all"} className={cn("mb-1 w-full rounded-md px-2.5 py-2 text-left text-sm", queue === "all" && "bg-accent font-semibold")}>{tx("Todas", "Todas", "All")}</button>
          {queues?.map((q) => (
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
                  <StatusBadge status={c.status === "resolved" ? "ok" : c.status === "pending_approval" ? "review" : "info"} mono>{c.status}</StatusBadge>
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
                  <Button size="sm" disabled={sel.status !== "new"} onClick={() => update((c) => log({ ...c, status: "accepted" }, "case.accepted"))}>{tx("Aceptar", "Aceitar", "Accept")}</Button>
                  <Button size="sm" variant="outline" onClick={() => update((c) => log({ ...c, status: "returned" }, "case.returned_to_copilot"))}>{tx("Devolver al copiloto", "Devolver ao copiloto", "Return to copilot")}</Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Select value={code} onValueChange={setCode}>
                    <SelectTrigger className="h-8 w-48 text-xs"><SelectValue placeholder={tx("Código de resolución", "Código de resolução", "Resolution code")} /></SelectTrigger>
                    <SelectContent>{["RES-FIXED", "RES-CHARGEBACK", "RES-NO-FRAUD", "RES-INFO-GIVEN", "RES-REJECTED"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                  <Button size="sm" variant="secondary" disabled={!code || sel.status === "resolved"} onClick={() => update((c) => log({ ...c, status: "resolved" }, `case.resolved code=${code}`))}>{tx("Resolver", "Resolver", "Resolve")}</Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Select value={approver} onValueChange={setApprover}>
                    <SelectTrigger className="h-8 w-48 text-xs"><SelectValue placeholder={tx("Aprobador", "Aprovador", "Approver")} /></SelectTrigger>
                    <SelectContent>{[ME, "j.paz", "c.vargas"].map((c) => <SelectItem key={c} value={c}>{c}{c === ME ? " (tú)" : ""}</SelectItem>)}</SelectContent>
                  </Select>
                  <Button size="sm" variant="outline" onClick={requestApproval}>{tx("Pedir segunda aprobación", "Pedir segunda aprovação", "Request second approval")}</Button>
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
