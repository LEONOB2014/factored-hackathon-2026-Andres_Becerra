import { Link, useRouterState } from "@tanstack/react-router";
import {
  BookOpen, ClipboardCheck, Gauge, Grid3x3, Headset, LayoutDashboard, Menu, MessageSquare, Monitor, Moon, Network, ShieldCheck, Sun, Workflow, X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useI18n, type UiLang } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const groups = [
  { key: "group.service", items: [
    { to: "/chat", label: "nav.chat", icon: MessageSquare },
    { to: "/desk", label: "nav.desk", icon: Headset },
    { to: "/supervisor", label: "nav.supervisor", icon: Gauge },
  ] },
  { key: "group.data", items: [
    { to: "/atlas", label: "nav.atlas", icon: Grid3x3 },
    { to: "/quality", label: "nav.quality", icon: ShieldCheck },
    { to: "/pipelines", label: "nav.pipelines", icon: Workflow },
    { to: "/knowledge", label: "nav.knowledge", icon: BookOpen },
  ] },
  { key: "group.product", items: [
    { to: "/specs", label: "nav.specs", icon: ClipboardCheck },
  ] },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const { mode, cycle } = useTheme();
  const [open, setOpen] = useState(false);
  const path = useRouterState({ select: (s) => s.location.pathname });
  const ThemeIcon = mode === "dark" ? Moon : mode === "light" ? Sun : Monitor;

  const nav = (
    <nav className="flex flex-col gap-5 px-3 py-4" aria-label="Main">
      <Link to="/" onClick={() => setOpen(false)} className={cn("flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-sidebar-accent", path === "/" && "bg-sidebar-accent font-semibold")}>
        <LayoutDashboard className="size-4" aria-hidden /> {t("nav.overview")}
      </Link>
      {groups.map((g) => (
        <div key={g.key}>
          <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.12em] opacity-60">{t(g.key)}</div>
          <ul className="flex flex-col gap-0.5">
            {g.items.map((it) => {
              const active = path.startsWith(it.to);
              return (
                <li key={it.to}>
                  <Link to={it.to} onClick={() => setOpen(false)} aria-current={active ? "page" : undefined}
                    className={cn("flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-sidebar-accent", active && "bg-sidebar-accent font-semibold")}>
                    <it.icon className="size-4 shrink-0" aria-hidden />
                    <span className="truncate">{t(it.label)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col overflow-y-auto border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:flex">
        <Brand />
        {nav}
        <div className="mt-auto border-t border-sidebar-border px-5 py-3 text-[11px] opacity-60">{t("mock")}</div>
      </aside>
      {open && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div className="w-64 overflow-y-auto bg-sidebar text-sidebar-foreground">
            <div className="flex items-center justify-between pr-3"><Brand /><button aria-label="Close menu" onClick={() => setOpen(false)} className="rounded p-1.5 hover:bg-sidebar-accent"><X className="size-4" /></button></div>
            {nav}
          </div>
          <button aria-label="Close menu" className="flex-1 bg-foreground/40" onClick={() => setOpen(false)} />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur">
          <button aria-label="Open menu" onClick={() => setOpen(true)} className="rounded p-1.5 hover:bg-muted lg:hidden"><Menu className="size-4" /></button>
          <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
            <Network className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">LATAM Bank · MX · CO · AR</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div role="group" aria-label="Language" className="flex rounded-md border p-0.5">
              {(["es", "pt", "en"] as UiLang[]).map((l) => (
                <button key={l} onClick={() => setLang(l)} aria-pressed={lang === l}
                  className={cn("rounded px-2 py-0.5 font-mono text-[11px] uppercase", lang === l ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>{l}</button>
              ))}
            </div>
            <button onClick={cycle} aria-label={`${t("theme.toggle")} (${mode})`} title={mode} className="rounded-md border p-1.5 hover:bg-muted">
              <ThemeIcon className="size-4" />
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-5 pb-1 pt-4">
      <div className="grid size-8 place-items-center rounded-lg bg-primary font-mono text-xs font-bold text-primary-foreground">β</div>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-tight">BETA AID</div>
        <div className="text-[10px] opacity-60">Console · LATAM Bank</div>
      </div>
    </div>
  );
}
