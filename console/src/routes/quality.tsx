import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Bot, Undo2, UserCheck } from "lucide-react";
import { toast } from "sonner";
import { qualityService } from "@/services";
import type { Correction, IssueStage, QIssue } from "@/services/types";
import { Mono, PageHeader, StatusBadge } from "@/components/beta/badges";
import { Button } from "@/components/ui/button";
import { useI18n, useTx } from "@/lib/i18n";

export const Route = createFileRoute("/quality")({
  head: () => ({
    meta: [
      { title: "Data quality & audit agents — BETA AID" },
      { name: "description", content: "Multi-agent data quality board, issue lifecycle kanban and four-eyes lakehouse corrections." },
      { property: "og:title", content: "Data quality & audit agents — BETA AID" },
      { property: "og:description", content: "Multi-agent data quality board and four-eyes lakehouse corrections." },
    ],
  }),
  component: QualityPage,
});

const STAGES: IssueStage[] = ["Detected", "Triaged", "Requirement drafted", "Owner assigned", "Acceptance test defined", "Fixed at source", "Verified", "Closed"];
const ME = "j.paz";

function QualityPage() {
  const { t } = useI18n();
  const tx = useTx();
  const { data: agents } = useQuery({ queryKey: ["agents"], queryFn: qualityService.agents });
  const { data: issuesInit } = useQuery({ queryKey: ["issues"], queryFn: qualityService.issues });
  const { data: corrInit } = useQuery({ queryKey: ["corrections"], queryFn: qualityService.corrections });
  const [issues, setIssues] = useState<QIssue[]>([]);
  const [corr, setCorr] = useState<Correction[]>([]);
  useEffect(() => { if (issuesInit) setIssues(issuesInit); }, [issuesInit]);
  useEffect(() => { if (corrInit) setCorr(corrInit); }, [corrInit]);

  const advance = (id: string) => setIssues((is) => is.map((i) => (i.id === id && i.stage !== "Closed" ? { ...i, stage: STAGES[STAGES.indexOf(i.stage) + 1] ?? i.stage } : i)));
  const setC = (id: string, patch: Partial<Correction>) => setCorr((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const sevStatus = { A: "blocked", B: "review", C: "info" } as const;

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader eyebrow={tx("Plano de control de datos", "Plano de controle de dados", "Data control plane")} title={tx("Agentes de calidad y auditoría", "Agentes de qualidade e auditoria", "Data quality & audit agents")} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {agents?.map((a) => (
          <div key={a.id} className="panel p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 font-semibold">{a.id === "reviewer" ? <UserCheck className="size-4" aria-hidden /> : <Bot className="size-4" aria-hidden />}{a.name}</div>
              <StatusBadge status={a.status}>{a.status_label}</StatusBadge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t(a.role)}</p>
            <div className="mt-3 flex justify-between text-xs"><span>{tx("Última ejecución", "Última execução", "Last run")} <Mono>{a.last_run}</Mono></span><span>{tx("Hallazgos", "Achados", "Findings")} <Mono className="font-semibold">{a.findings}</Mono></span></div>
          </div>
        ))}
      </div>

      <h2 className="eyebrow mb-2 mt-6">{tx("Ciclo de vida de incidencias", "Ciclo de vida dos problemas", "Issue lifecycle")}</h2>
      <div className="flex gap-3 overflow-x-auto pb-2">
        {STAGES.map((s) => (
          <div key={s} className="w-56 shrink-0 rounded-xl bg-muted/60 p-2">
            <div className="mb-2 flex justify-between px-1 text-xs font-semibold">{s}<Mono className="text-muted-foreground">{issues.filter((i) => i.stage === s).length}</Mono></div>
            <div className="space-y-2">
              {issues.filter((i) => i.stage === s).map((i) => (
                <div key={i.id} className="panel p-2.5 text-xs">
                  <div className="flex items-center justify-between"><Mono className="font-semibold">{i.id}</Mono><StatusBadge status={sevStatus[i.severity]} mono>sev {i.severity}</StatusBadge></div>
                  <div className="mt-1 font-medium">{i.title}</div>
                  <dl className="mt-1.5 grid grid-cols-[52px_1fr] gap-x-1 gap-y-0.5 text-[11px]">
                    <dt className="text-muted-foreground">table</dt><dd className="truncate font-mono">{i.table}</dd>
                    <dt className="text-muted-foreground">rule</dt><dd className="truncate font-mono" title={i.rule}>{i.rule}</dd>
                    <dt className="text-muted-foreground">rows</dt><dd className="font-mono">{i.rows.toLocaleString("es-AR")}</dd>
                    <dt className="text-muted-foreground">SLA</dt><dd className="font-mono">{i.sla}</dd>
                    <dt className="text-muted-foreground">owner</dt><dd className="truncate">{i.owner}</dd>
                    <dt className="text-muted-foreground">gate</dt><dd className="truncate">{i.gate}</dd>
                  </dl>
                  {i.stage !== "Closed" && <Button size="sm" variant="ghost" className="mt-1 h-6 w-full text-[11px]" onClick={() => advance(i.id)}>{tx("Avanzar →", "Avançar →", "Advance →")}</Button>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <h2 className="eyebrow mb-2 mt-6">{tx("Correcciones con cuatro ojos en el lakehouse", "Correções com quatro olhos no lakehouse", "Four-eyes corrections into the lakehouse")}</h2>
      <div className="grid gap-3 lg:grid-cols-2">
        {corr.map((c) => (
          <div key={c.id} className="panel p-4">
            <div className="flex flex-wrap items-center gap-2"><Mono className="font-semibold">{c.id}</Mono><Mono className="text-muted-foreground">{c.table}</Mono>
              <StatusBadge className="ml-auto" status={c.status === "applied" ? "ok" : c.status === "proposed" ? "review" : c.status === "rejected" ? "blocked" : "info"} mono>{c.status}</StatusBadge></div>
            <p className="mt-1 text-sm">{c.reason}</p>
            <table className="mt-3 w-full text-xs">
              <thead><tr className="text-left text-muted-foreground"><th className="py-1 font-medium">key</th><th className="font-medium">field</th><th className="font-medium">before</th><th className="font-medium">after</th></tr></thead>
              <tbody>{c.rows.map((r) => (
                <tr key={r.key} className="border-t"><td className="py-1 pr-2 font-mono">{r.key}</td><td className="font-mono">{r.field}</td><td className="bg-blocked-soft px-1 font-mono line-through">{r.before}</td><td className="bg-ok-soft px-1 font-mono">{r.after}</td></tr>
              ))}</tbody>
            </table>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>{tx("Propone", "Propõe", "Proposer")}: <b className="text-foreground">{c.proposer}</b></span>
              <span>{tx("Aprueba", "Aprova", "Approver")}: <b className="text-foreground">{c.approver ?? "—"}</b></span>
              {c.hash && <span>audit <Mono className="text-foreground">{c.hash}</Mono> · {c.applied_at}</span>}
            </div>
            <div className="mt-3 flex gap-2">
              {c.status === "proposed" && (<>
                <Button size="sm" onClick={() => {
                  if (c.proposer === ME) { toast.error("Four eyes"); return; }
                  setC(c.id, { status: "applied", approver: ME, hash: `sha256:${Math.random().toString(16).slice(2, 6)}…${Math.random().toString(16).slice(2, 6)}`, applied_at: new Date().toISOString().slice(0, 16).replace("T", " ") });
                  toast.success(tx(`Aprobado por ${ME} (distinto de ${c.proposer})`, `Aprovado por ${ME}`, `Approved by ${ME} (≠ ${c.proposer})`));
                }}>{tx("Aprobar", "Aprovar", "Approve")} ({ME})</Button>
                <Button size="sm" variant="outline" onClick={() => setC(c.id, { status: "rejected", approver: ME })}>{tx("Rechazar", "Rejeitar", "Reject")}</Button>
              </>)}
              {c.status === "applied" && <Button size="sm" variant="outline" onClick={() => setC(c.id, { status: "reverted" })}><Undo2 className="size-3.5" />{tx("Revertir a fecha", "Reverter à data", "Revert as of time")} {c.applied_at}</Button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
