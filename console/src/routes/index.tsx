import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Activity, ShieldAlert, Grid3x3, Tag } from "lucide-react";
import { overviewService } from "@/services";
import { Mono, PageHeader, StatusBadge } from "@/components/beta/badges";
import { useI18n, useTx } from "@/lib/i18n";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Overview — BETA AID Console" },
      { name: "description", content: "Staff landing for BETA AID: copilot health, data quality, model readiness and releases." },
      { property: "og:title", content: "Overview — BETA AID Console" },
      { property: "og:description", content: "Staff landing for BETA AID: copilot health, data quality, model readiness and releases." },
    ],
  }),
  component: Overview,
});

const areas = [
  { to: "/chat", k: "nav.chat" }, { to: "/desk", k: "nav.desk" }, { to: "/supervisor", k: "nav.supervisor" },
  { to: "/atlas", k: "nav.atlas" }, { to: "/quality", k: "nav.quality" }, { to: "/pipelines", k: "nav.pipelines" },
  { to: "/knowledge", k: "nav.knowledge" }, { to: "/specs", k: "nav.specs" },
] as const;

function Overview() {
  const { t } = useI18n();
  const tx = useTx();
  const { data } = useQuery({ queryKey: ["overview"], queryFn: overviewService.summary });
  // Its own query, so the other tiles never wait on the control plane.
  const { data: readiness } = useQuery({ queryKey: ["control", "readiness", "counts"], queryFn: overviewService.readiness });
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow="BETA AID · Banking Evolutionary Transformation and AI Deployment" title={tx("Consola de operaciones", "Console de operações", "Operations console")}>
        {tx(
          "BETA AID es la plataforma bancaria AI-first de LATAM Bank: un copiloto que responde, actúa con confirmación o traspasa a una persona según una política versionada, sobre un plano de datos gobernado donde cada modelo debe ganarse su lugar con evidencia fuera de tiempo.",
          "BETA AID é a plataforma bancária AI-first do LATAM Bank: um copiloto que responde, age com confirmação ou transfere para uma pessoa segundo uma política versionada, sobre um plano de dados governado onde cada modelo precisa provar seu valor com evidência fora do tempo.",
          "BETA AID is LATAM Bank's AI-first banking platform: a copilot that answers, acts after confirmation or hands off to a person under a versioned policy, on a governed data plane where every model must earn its place with out-of-time evidence.",
        )}
      </PageHeader>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile icon={Activity} label={tx("Salud del copiloto", "Saúde do copiloto", "Copilot health")} to="/supervisor">
          <StatusBadge status="ok">operational</StatusBadge>
          <div className="mt-2 text-xs text-muted-foreground">uptime <Mono>{data?.copilot.uptime ?? "…"}</Mono> · p95 <Mono>{data?.copilot.p95 ?? "…"}</Mono></div>
        </Tile>
        <Tile icon={ShieldAlert} label={tx("Incidencias de calidad abiertas", "Problemas de qualidade abertos", "Open quality issues")} to="/quality">
          <div className="font-mono text-3xl font-semibold">{data?.openIssues ?? "…"}</div>
        </Tile>
        <Tile icon={Grid3x3} label={tx("Preparación de modelos", "Prontidão de modelos", "Readiness")} to="/atlas">
          <div className="flex flex-wrap gap-1.5">
            <StatusBadge status="ok" mono>{readiness?.green ?? "–"} green</StatusBadge>
            <StatusBadge status="review" mono>{readiness?.amber ?? "–"} amber</StatusBadge>
            <StatusBadge status="blocked" mono>{readiness?.red ?? "–"} red</StatusBadge>
          </div>
          <div className="mt-2 text-xs text-muted-foreground">{tx("«0 green» es el estado honesto.", "«0 green» é o estado honesto.", "“0 green” is the honest state.")}</div>
        </Tile>
        <Tile icon={Tag} label={tx("Última versión", "Última versão", "Last release")} to="/specs">
          <div className="font-mono text-3xl font-semibold">{data?.release ?? "…"}</div>
        </Tile>
      </div>
      <h2 className="eyebrow mb-2 mt-8">{tx("Áreas", "Áreas", "Areas")}</h2>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {areas.map((a) => (
          <Link key={a.to} to={a.to} className="panel group flex items-center justify-between px-4 py-3 text-sm hover:border-primary">
            {t(a.k)} <ArrowRight className="size-4 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden />
          </Link>
        ))}
      </div>
    </div>
  );
}

function Tile({ icon: Icon, label, to, children }: { icon: typeof Activity; label: string; to: "/supervisor" | "/quality" | "/atlas" | "/specs"; children: import("react").ReactNode }) {
  return (
    <Link to={to} className="panel block p-4 hover:border-primary">
      <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground"><Icon className="size-4" aria-hidden />{label}</div>
      {children}
    </Link>
  );
}
