import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type UiLang = "es" | "pt" | "en";

const dict = {
  "app.tagline": { es: "Banking Evolutionary Transformation and AI Deployment", pt: "Banking Evolutionary Transformation and AI Deployment", en: "Banking Evolutionary Transformation and AI Deployment" },
  "group.service": { es: "Atención al cliente", pt: "Atendimento", en: "Customer service" },
  "group.data": { es: "Plano de control de datos", pt: "Plano de controle de dados", en: "Data control plane" },
  "group.product": { es: "Producto", pt: "Produto", en: "Product" },
  "nav.overview": { es: "Resumen", pt: "Visão geral", en: "Overview" },
  "nav.chat": { es: "Chat cliente (simulador)", pt: "Chat cliente (simulador)", en: "Customer chat (simulator)" },
  "nav.desk": { es: "Mesa de agentes", pt: "Mesa de agentes", en: "Agent desk" },
  "nav.supervisor": { es: "Supervisor", pt: "Supervisor", en: "Supervisor" },
  "nav.atlas": { es: "Atlas de preparación", pt: "Atlas de prontidão", en: "Readiness atlas" },
  "nav.quality": { es: "Calidad y auditoría", pt: "Qualidade e auditoria", en: "Data quality & audit" },
  "nav.pipelines": { es: "Pipelines", pt: "Pipelines", en: "Pipelines" },
  "nav.knowledge": { es: "Base de conocimiento", pt: "Base de conhecimento", en: "Knowledge base" },
  "nav.specs": { es: "Entrega guiada por specs", pt: "Entrega guiada por specs", en: "Spec-driven delivery" },
  "theme.toggle": { es: "Cambiar tema", pt: "Alternar tema", en: "Toggle theme" },
  "mock": { es: "Datos sintéticos · sin backend", pt: "Dados sintéticos · sem backend", en: "Synthetic data · no backend" },
  "kpi.correct": { es: "Decisión correcta", pt: "Decisão correta", en: "Correct decision" },
  "kpi.safe": { es: "Resolución automática segura", pt: "Resolução automática segura", en: "Safe automated resolution" },
  "kpi.containment": { es: "Contención", pt: "Contenção", en: "Containment" },
  "kpi.missed": { es: "Traspasos omitidos", pt: "Transferências perdidas", en: "Missed transfers" },
  "kpi.unnecessary": { es: "Traspasos innecesarios", pt: "Transferências desnecessárias", en: "Unnecessary transfers" },
  "kpi.unsafe": { es: "Resultados inseguros", pt: "Resultados inseguros", en: "Unsafe outcomes" },
  "kpi.p50": { es: "Latencia p50 (modelo)", pt: "Latência p50 (modelo)", en: "p50 latency (model)" },
  "kpi.p95": { es: "Latencia p95 (modelo)", pt: "Latência p95 (modelo)", en: "p95 latency (model)" },
  "kpi.cost": { es: "Costo por resolución", pt: "Custo por resolução", en: "Cost per resolution" },
  "queue.fraud": { es: "Fraude", pt: "Fraude", en: "Fraud" },
  "queue.risk": { es: "Riesgo", pt: "Risco", en: "Risk" },
  "queue.credit_limits": { es: "Cupos", pt: "Limites", en: "Credit limits" },
  "queue.disputes": { es: "Disputas", pt: "Contestações", en: "Disputes" },
  "queue.complaints": { es: "Quejas", pt: "Reclamações", en: "Complaints" },
  "queue.general": { es: "General", pt: "Geral", en: "General" },
  "agent.profiler": { es: "Perfila particiones nuevas", pt: "Perfila partições novas", en: "Profiles new partitions" },
  "agent.auditor": { es: "Verifica contratos y cadenas hash", pt: "Verifica contratos e cadeias hash", en: "Checks contracts and hash chains" },
  "agent.writer": { es: "Convierte un gate fallido en requisito", pt: "Transforma gate reprovado em requisito", en: "Turns a failed gate into a data requirement" },
  "agent.reviewer": { es: "Aprobador humano", pt: "Aprovador humano", en: "Human approver" },
} satisfies Record<string, Record<UiLang, string>>;

export type TKey = keyof typeof dict;

const Ctx = createContext<{ lang: UiLang; setLang: (l: UiLang) => void; t: (k: string) => string }>({
  lang: "es",
  setLang: () => {},
  t: (k) => k,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<UiLang>("es");
  useEffect(() => {
    const s = localStorage.getItem("beta-lang") as UiLang | null;
    if (s) setLangState(s);
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = (l: UiLang) => {
    setLangState(l);
    localStorage.setItem("beta-lang", l);
  };
  const t = (k: string) => (dict as Record<string, Record<UiLang, string>>)[k]?.[lang] ?? k;
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);

/** Inline trilingual helper for page copy. */
export function useTx() {
  const { lang } = useI18n();
  return (es: string, pt: string, en: string) => (lang === "pt" ? pt : lang === "en" ? en : es);
}
