import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Mode = "system" | "light" | "dark";
const Ctx = createContext<{ mode: Mode; cycle: () => void }>({ mode: "system", cycle: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>("system");
  useEffect(() => {
    const s = localStorage.getItem("beta-theme") as Mode | null;
    if (s) setMode(s);
  }, []);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = mode === "dark" || (mode === "system" && mq.matches);
      document.documentElement.classList.toggle("dark", dark);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [mode]);
  const cycle = () => {
    const next: Mode = mode === "system" ? "light" : mode === "light" ? "dark" : "system";
    setMode(next);
    localStorage.setItem("beta-theme", next);
  };
  return <Ctx.Provider value={{ mode, cycle }}>{children}</Ctx.Provider>;
}
export const useTheme = () => useContext(Ctx);
