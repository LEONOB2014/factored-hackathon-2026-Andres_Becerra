import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ExternalLink, Plus } from "lucide-react";
import { specService } from "@/services";
import type { Spec } from "@/services/types";
import { Mono, PageHeader, StatusBadge } from "@/components/beta/badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useTx } from "@/lib/i18n";

export const Route = createFileRoute("/specs")({
  head: () => ({
    meta: [
      { title: "Spec-driven delivery — BETA AID" },
      { name: "description", content: "Take ideas from spec to plan, tasks, implementation, verification and release, linked to the gates they close." },
      { property: "og:title", content: "Spec-driven delivery — BETA AID" },
      { property: "og:description", content: "From spec to verified release, linked to readiness gates and quality issues." },
    ],
  }),
  component: SpecsPage,
});

const STAGES: Spec["stage"][] = ["Spec", "Plan", "Tasks", "Implementation", "Verification", "Released"];

function SpecsPage() {
  const tx = useTx();
  const { data } = useQuery({ queryKey: ["specs"], queryFn: specService.list });
  const [specs, setSpecs] = useState<Spec[]>([]);
  useEffect(() => { if (data) setSpecs(data); }, [data]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ idea: "", users: "", outcome: "" });
  const [draft, setDraft] = useState<Spec | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader eyebrow={tx("Producto", "Produto", "Product")} title={tx("Entrega guiada por specs", "Entrega guiada por specs", "Spec-driven delivery")}
        actions={
          <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setDraft(null); }}>
            <DialogTrigger asChild><Button><Plus className="size-4" />{tx("Lanzar spec", "Lançar spec", "Launch spec")}</Button></DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader><DialogTitle>{tx("Nueva spec", "Nova spec", "New spec")}</DialogTitle><DialogDescription>{tx("Genera un borrador para revisión (texto simulado).", "Gera um rascunho para revisão (texto simulado).", "Generates a draft for review (mock text).")}</DialogDescription></DialogHeader>
              {!draft ? (
                <form className="space-y-3" onSubmit={async (e) => { e.preventDefault(); setBusy(true); setDraft(await specService.draft(form)); setBusy(false); }}>
                  <label className="block text-xs">{tx("Idea", "Ideia", "Idea")}<Input required value={form.idea} onChange={(e) => setForm({ ...form, idea: e.target.value })} placeholder="Consultar movimientos por WhatsApp" /></label>
                  <label className="block text-xs">{tx("Usuarios", "Usuários", "Users")}<Input value={form.users} onChange={(e) => setForm({ ...form, users: e.target.value })} placeholder="clientes MX con tarjeta de crédito" /></label>
                  <label className="block text-xs">{tx("Resultado esperado", "Resultado esperado", "Expected outcome")}<Textarea value={form.outcome} onChange={(e) => setForm({ ...form, outcome: e.target.value })} placeholder="ve sus últimos 5 movimientos con montos enmascarados" /></label>
                  <Button type="submit" disabled={busy} className="w-full">{busy ? "…" : tx("Generar borrador", "Gerar rascunho", "Generate draft")}</Button>
                </form>
              ) : (
                <div className="space-y-2 text-sm">
                  <div className="flex items-center gap-2"><Mono className="font-semibold">{draft.id}</Mono><StatusBadge status="info">draft</StatusBadge></div>
                  <div className="font-semibold">{draft.title}</div>
                  <p><b>{tx("Problema", "Problema", "Problem")}:</b> {draft.problem}</p>
                  <p><b>{tx("Usuarios", "Usuários", "Users")}:</b> {draft.users}</p>
                  <ul className="list-disc pl-5 text-xs">{draft.criteria.map((c) => <li key={c}>{c}</li>)}</ul>
                  <Button className="w-full" onClick={() => { setSpecs((s) => [draft, ...s]); setOpen(false); setDraft(null); setForm({ idea: "", users: "", outcome: "" }); }}>{tx("Enviar a revisión", "Enviar para revisão", "Submit for review")}</Button>
                </div>
              )}
            </DialogContent>
          </Dialog>
        } />
      <div className="flex gap-3 overflow-x-auto pb-2">
        {STAGES.map((st) => (
          <div key={st} className="w-64 shrink-0 rounded-xl bg-muted/60 p-2">
            <div className="mb-2 flex justify-between px-1 text-xs font-semibold">{st}<Mono className="text-muted-foreground">{specs.filter((s) => s.stage === st).length}</Mono></div>
            <div className="space-y-2">
              {specs.filter((s) => s.stage === st).map((s) => (
                <div key={s.id} className="panel p-3 text-xs">
                  <Mono className="font-semibold">{s.id}</Mono>
                  <div className="mt-0.5 text-sm font-medium">{s.title}</div>
                  <p className="mt-1 text-muted-foreground">{s.problem}</p>
                  <ul className="mt-1.5 list-disc pl-4">{s.criteria.map((c) => <li key={c}>{c}</li>)}</ul>
                  <div className="mt-2 space-y-0.5">
                    {s.plan && <div className="flex items-center gap-1"><ExternalLink className="size-3" aria-hidden /><span className="text-primary underline">{s.plan}</span></div>}
                    {s.prs && <div>PRs <Mono>{s.prs.join(" ")}</Mono></div>}
                    {s.tests && <div>tests <Mono>{s.tests}</Mono> · eval <Mono>{s.eval}</Mono></div>}
                    {s.version && <StatusBadge status="ok" mono>{s.version}</StatusBadge>}
                  </div>
                  {s.closes.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{s.closes.map((c) => <StatusBadge key={c} status="info" mono>closes {c}</StatusBadge>)}</div>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
