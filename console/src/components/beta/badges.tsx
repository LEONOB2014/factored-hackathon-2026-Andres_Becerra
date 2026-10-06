import { AlertTriangle, CheckCircle2, Info, OctagonX, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Outcome, Status, Verdict } from "@/services/types";

const statusStyle: Record<Status, { cls: string; icon: LucideIcon }> = {
  ok: { cls: "bg-ok-soft text-ok border-ok/30", icon: CheckCircle2 },
  review: { cls: "bg-review-soft text-review border-review/30", icon: AlertTriangle },
  blocked: { cls: "bg-blocked-soft text-blocked border-blocked/30", icon: OctagonX },
  info: { cls: "bg-info-soft text-info border-info/30", icon: Info },
};

export function StatusBadge({ status, children, className, mono }: { status: Status; children: ReactNode; className?: string; mono?: boolean }) {
  const s = statusStyle[status];
  const Icon = s.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap", s.cls, mono && "font-mono", className)}>
      <Icon className="size-3 shrink-0" aria-hidden />
      {children}
    </span>
  );
}

export const verdictStatus: Record<Verdict, Status> = { green: "ok", amber: "review", red: "blocked" };
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <StatusBadge status={verdictStatus[verdict]}>{verdict}</StatusBadge>;
}

export const outcomeStatus: Record<Outcome, Status> = {
  answered: "ok",
  action_done: "ok",
  clarify: "info",
  confirm_requested: "info",
  stepup_required: "review",
  auth_required: "review",
  cancelled: "info",
  handoff: "review",
  deny: "blocked",
  refused: "blocked",
  tool_failure: "blocked",
};
export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return <StatusBadge status={outcomeStatus[outcome]} mono>{outcome}</StatusBadge>;
}

const autonomyText = { A0: "answer", A2: "act after confirm", A3: "a person decides" };
export function AutonomyBadge({ level, short }: { level: "A0" | "A2" | "A3"; short?: boolean }) {
  const cls = level === "A0" ? "bg-secondary text-secondary-foreground" : level === "A2" ? "bg-accent text-accent-foreground" : "bg-highlight text-highlight-foreground";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border border-transparent px-1.5 py-0.5 font-mono text-[11px] font-semibold", cls)} title={autonomyText[level]}>
      {level}
      {!short && <span className="font-sans font-normal opacity-90">· {autonomyText[level]}</span>}
    </span>
  );
}

/** 95% interval range bar. Domain defaults to [0,1]. */
export function IntervalBar({ value, lo, hi, min = 0, max = 1, threshold, className }: { value: number; lo: number; hi: number; min?: number; max?: number; threshold?: number | undefined; className?: string }) {
  const p = (x: number) => `${Math.max(0, Math.min(100, ((x - min) / (max - min)) * 100))}%`;
  return (
    <div className={cn("relative h-2 w-full rounded-full bg-muted", className)} role="img" aria-label={`IC 95 %: ${lo} – ${hi}, punto ${value}`}>
      <div className="absolute inset-y-0 rounded-full bg-primary/35" style={{ left: p(lo), width: `calc(${p(hi)} - ${p(lo)})` }} />
      <div className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card bg-primary" style={{ left: p(value) }} />
      {threshold !== undefined && <div className="absolute -inset-y-1 w-px bg-highlight" style={{ left: p(threshold) }} title={`umbral ${threshold}`} />}
    </div>
  );
}

export function PageHeader({ eyebrow, title, children, actions }: { eyebrow?: string; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {children && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{children}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[12px]", className)}>{children}</span>;
}
