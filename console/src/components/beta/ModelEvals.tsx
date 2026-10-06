// Held-out intent-model scores and knowledge-base retrieval scores from GET /api/control/evaluation.
import type { Evaluation } from "@/services/types";
import { Mono } from "@/components/beta/badges";
import { useTx } from "@/lib/i18n";

const n3 = (x: number | null | undefined) => (x === null || x === undefined ? "—" : x.toFixed(3).replace(".", ","));
const pct = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(1).replace(".", ",")} %`);
const ms = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${x} ms`);

// [API key, column header, format]
const RETRIEVAL_COLS: [string, string, (x: number | undefined) => string][] = [
  ["hit@1", "hit@1", pct], ["hit@3", "hit@3", pct], ["mrr", "MRR", n3], ["answerable_kept", "answerable kept", pct],
  ["unanswerable_rejected", "unanswerable rejected", pct], ["governance_violations", "governance violations", (x) => (x === undefined ? "—" : String(x))],
  ["latency_ms_p50", "p50", ms], ["latency_ms_p95", "p95", ms],
];

export function ModelEvals({ intent, retrieval }: { intent: Evaluation["intent_model"]; retrieval: Evaluation["retrieval"] }) {
  const tx = useTx();
  const stores = Object.keys(retrieval);
  return (
    <div className="space-y-4">
      <div className="panel overflow-x-auto">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">{tx("Modelo de intención · conjunto retenido", "Modelo de intenção · conjunto retido", "Intent model · held-out set")}</div>
        {intent ? (
          <>
            <table className="w-full whitespace-nowrap text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                <th className="px-4 py-2 font-medium">model</th><th className="px-2 font-medium">n</th><th className="px-2 font-medium">accuracy</th><th className="px-2 font-medium">macro F1</th>
                <th className="px-2 font-medium">F1 ES</th><th className="px-2 font-medium">F1 PT</th><th className="px-2 font-medium">ECE</th>
                <th className="px-2 font-medium">{tx("cobertura al umbral", "cobertura no limiar", "coverage at threshold")}</th><th className="px-2 font-medium">{tx("acierto si confiado", "acerto se confiante", "accuracy when confident")}</th>
                <th className="px-2 font-medium">p50 · p95</th>
              </tr></thead>
              <tbody>
                {intent.held_out.map((m) => (
                  <tr key={m.model} className="border-b last:border-0">
                    <td className="px-4 py-2"><Mono>{m.model}</Mono></td><td className="px-2"><Mono>{m.n}</Mono></td>
                    <td className="px-2"><Mono>{pct(m.accuracy)}</Mono></td><td className="px-2"><Mono>{n3(m.macro_f1)}</Mono></td>
                    <td className="px-2"><Mono>{n3(m.macro_f1_by_language?.["es"])}</Mono></td><td className="px-2"><Mono>{n3(m.macro_f1_by_language?.["pt"])}</Mono></td>
                    <td className="px-2"><Mono>{n3(m.ece)}</Mono></td><td className="px-2"><Mono>{pct(m.coverage_at_threshold)}</Mono></td>
                    <td className="px-2"><Mono>{pct(m.accuracy_when_confident)}</Mono></td><td className="px-2"><Mono>{ms(m.latency_ms_p50)} · {ms(m.latency_ms_p95)}</Mono></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">
              {tx("Ajuste", "Ajuste", "Tuning")}: {tx("umbral", "limiar", "threshold")} <Mono>{n3(intent.tuning.params?.threshold)}</Mono> · CV macro F1 <Mono>{n3(intent.tuning.cv_macro_f1)}</Mono> · {tx("precisión objetivo", "precisão alvo", "target precision")} <Mono>{pct(intent.tuning.target_precision)}</Mono> · {tx("cobertura OOF", "cobertura OOF", "OOF coverage")} <Mono>{pct(intent.tuning.oof_coverage_at_threshold)}</Mono>
              {intent.tuning.tuned_at && <> · <Mono>{intent.tuning.tuned_at}</Mono></>}
              {intent.tuning.mlflow_run_id && <> · MLflow <Mono>{intent.tuning.mlflow_run_id.slice(0, 8)}</Mono></>}
            </p>
          </>
        ) : <p className="px-4 py-6 text-xs text-muted-foreground">{tx("Este despliegue no incluye el reporte del modelo de intención.", "Esta implantação não inclui o relatório do modelo de intenção.", "This deployment bundles no intent-model report.")}</p>}
      </div>
      <div className="panel overflow-x-auto">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">{tx("Recuperación de la base de conocimiento", "Recuperação da base de conhecimento", "Knowledge-base retrieval")}</div>
        {stores.length ? (
          <table className="w-full whitespace-nowrap text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
              <th className="px-4 py-2 font-medium">store</th>{RETRIEVAL_COLS.map(([c, h]) => <th key={c} className="px-2 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {stores.map((s) => (
                <tr key={s} className="border-b last:border-0">
                  <td className="px-4 py-2"><Mono>{s}</Mono> <span className="text-[11px] text-muted-foreground">n={retrieval[s]?.["n_test"] ?? "—"}</span></td>
                  {RETRIEVAL_COLS.map(([c, , f]) => <td key={c} className="px-2"><Mono>{f(retrieval[s]?.[c])}</Mono></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="px-4 py-6 text-xs text-muted-foreground">{tx("Este despliegue no incluye el reporte de recuperación.", "Esta implantação não inclui o relatório de recuperação.", "This deployment bundles no retrieval report.")}</p>}
      </div>
    </div>
  );
}
