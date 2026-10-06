import { CheckCircle2, XCircle } from "lucide-react";
import type { Trace } from "@/services/types";
import { AutonomyBadge, Mono, OutcomeBadge, StatusBadge } from "./badges";

export function TracePanel({ trace }: { trace: Trace | null }) {
  if (!trace) return <div className="p-4 text-sm text-muted-foreground">Envía un mensaje para ver la traza del turno.</div>;
  const max = Math.max(...trace.stages.map((s) => s.ms), 1);
  const row = (k: string, v: import("react").ReactNode) => (
    <div className="flex items-center justify-between gap-3 border-b border-dashed py-1.5 last:border-0">
      <span className="text-xs text-muted-foreground">{k}</span>
      <span className="text-right text-xs">{v ?? "—"}</span>
    </div>
  );
  const verdict = (v?: string) => (!v ? "—" : <StatusBadge status={v === "pass" ? "ok" : v === "n/a" ? "info" : "blocked"} mono>{v}</StatusBadge>);
  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={trace.outcome} />
        {trace.autonomy && <AutonomyBadge level={trace.autonomy} />}
        <Mono className="ml-auto text-muted-foreground">{trace.turn_id}</Mono>
      </div>
      <div>
        {row("intent", <Mono>{trace.intent}</Mono>)}
        {row("confidence", trace.intent_confidence !== undefined && <Mono>{trace.intent_confidence.toFixed(2)}</Mono>)}
        {row("intent source", trace.intent_source && <Mono>{trace.intent_source}</Mono>)}
        {row("policy rule", trace.policy_rule && <Mono>{trace.policy_rule} · {trace.policy_version}</Mono>)}
        {row("language", trace.language && <Mono>{trace.language}</Mono>)}
        {row("guard", verdict(trace.guard))}
        {row("grounding", verdict(trace.grounding))}
        {trace.card && row("card", <Mono>{trace.card}</Mono>)}
      </div>
      {trace.action && (
        <div className="rounded-lg border bg-ok-soft p-3 text-xs">
          <div className="eyebrow mb-1">action</div>
          <div className="flex flex-wrap items-center gap-2">
            <Mono>{trace.action}</Mono>
            <Mono>{trace.action_id ?? "—"}</Mono>
            {trace.read_back ? (
              <span className="inline-flex items-center gap-1 font-medium text-ok"><CheckCircle2 className="size-3.5" aria-hidden /> read-back ✔</span>
            ) : (
              <span className="inline-flex items-center gap-1 font-medium text-blocked"><XCircle className="size-3.5" aria-hidden /> read-back ✘</span>
            )}
          </div>
        </div>
      )}
      <div>
        <div className="eyebrow mb-2">stage latency · {trace.latency_ms} ms</div>
        <div className="space-y-1.5">
          {trace.stages.map((s) => (
            <div key={s.stage} className="grid grid-cols-[72px_1fr_64px] items-center gap-2 text-xs">
              <Mono className="text-muted-foreground">{s.stage}</Mono>
              <div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${Math.max(2, (s.ms / max) * 100)}%` }} /></div>
              <Mono className="text-right">{s.ms} ms</Mono>
            </div>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        {[["LLM", trace.llm_calls], ["tok in", trace.tokens_in], ["tok out", trace.tokens_out], ["US$", trace.cost_usd.toFixed(4)]].map(([k, v]) => (
          <div key={k} className="rounded-md border p-2"><div className="text-[10px] text-muted-foreground">{k}</div><Mono>{v}</Mono></div>
        ))}
      </div>
      {trace.retrieval && (
        <div>
          <div className="eyebrow mb-1">retrieval</div>
          {trace.retrieval.map((r) => (
            <div key={r.cite} className="flex items-center justify-between gap-2 text-xs"><span className="truncate">{r.cite}</span><Mono>{r.score.toFixed(2)} · {r.classification}</Mono></div>
          ))}
        </div>
      )}
    </div>
  );
}
