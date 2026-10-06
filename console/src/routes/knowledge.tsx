import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CheckCircle2, Search } from "lucide-react";
import { knowledgeService } from "@/services";
import type { KChunk } from "@/services/types";
import { Mono, PageHeader, StatusBadge } from "@/components/beta/badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTx } from "@/lib/i18n";

export const Route = createFileRoute("/knowledge")({
  head: () => ({
    meta: [
      { title: "Knowledge base — BETA AID" },
      { name: "description", content: "Governed procedures with versions and approvals, an identical active set hash and a retrieval playground." },
      { property: "og:title", content: "Knowledge base — BETA AID" },
      { property: "og:description", content: "Governed procedures and a retrieval playground with citations." },
    ],
  }),
  component: KnowledgePage,
});

const docStatus = { approved: "ok", draft: "info", superseded: "review", retired: "blocked" } as const;

function KnowledgePage() {
  const tx = useTx();
  const { data } = useQuery({ queryKey: ["kdocs"], queryFn: knowledgeService.docs });
  const [q, setQ] = useState("me cobraron dos veces, quiero una disputa");
  const [res, setRes] = useState<(KChunk & { score: number })[] | null>(null);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    setRes(await knowledgeService.retrieve(q));
    setBusy(false);
  }
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow={tx("Plano de control de datos", "Plano de controle de dados", "Data control plane")} title={tx("Base de conocimiento", "Base de conhecimento", "Knowledge base")} />
      <div className="panel mb-4 flex flex-wrap items-center gap-3 p-3 text-xs">
        <span className="font-semibold">active set hash</span>
        {data?.stores.map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1"><CheckCircle2 className="size-3.5 text-ok" aria-hidden />{s} <Mono>{data.hash}</Mono></span>
        ))}
        <StatusBadge status="ok">{tx("idéntico en los 3", "idêntico nos 3", "identical across 3")}</StatusBadge>
      </div>
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[800px] text-sm">
          <thead><tr className="border-b text-left text-xs text-muted-foreground">{["doc", "status", "version", "effective", "class", "owner", "approver"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
          <tbody>{data?.docs.map((d) => (
            <tr key={d.id + d.version} className="border-b last:border-0">
              <td className="px-3 py-2"><div className="font-medium">{d.title}</div><Mono className="text-muted-foreground">{d.id}</Mono></td>
              <td className="px-3"><StatusBadge status={docStatus[d.status]}>{d.status}</StatusBadge></td>
              <td className="px-3"><Mono>{d.version}</Mono></td>
              <td className="px-3"><Mono>{d.effective}</Mono></td>
              <td className="px-3"><StatusBadge status={d.classification === "public" ? "info" : "review"}>{d.classification}</StatusBadge></td>
              <td className="px-3 text-xs">{d.owner}</td><td className="px-3 text-xs">{d.approver}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>

      <h2 className="eyebrow mb-2 mt-6">{tx("Playground de recuperación", "Playground de recuperação", "Retrieval playground")}</h2>
      <form onSubmit={(e) => { e.preventDefault(); run(); }} className="flex gap-2">
        <label htmlFor="kq" className="sr-only">Query</label>
        <Input id="kq" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button type="submit" disabled={busy}><Search className="size-4" />{tx("Buscar", "Buscar", "Search")}</Button>
      </form>
      <div className="mt-3 space-y-2">
        {res?.length === 0 && <p className="text-sm text-muted-foreground">{tx("Sin resultados sobre el umbral.", "Sem resultados acima do limiar.", "No results above threshold.")}</p>}
        {res?.map((c) => (
          <div key={c.cite} className="panel p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Mono className="font-semibold">{c.cite}</Mono>
              <StatusBadge status={c.classification === "public" ? "info" : "review"}>{c.classification}</StatusBadge>
              <StatusBadge status="info" mono>{c.found_by}</StatusBadge>
              <Mono className="ml-auto">score {c.score.toFixed(2)}</Mono>
            </div>
            <p className="mt-1 text-sm">{c.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
