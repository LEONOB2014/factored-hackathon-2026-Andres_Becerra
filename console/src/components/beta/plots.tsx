// Observable Plot charts. Plot builds an SVG; PlotFigure renders it into a ref and rebuilds it when the
// options, the width or the theme change. Axes and text use currentColor, so they follow light and dark.
import * as Plot from "@observablehq/plot";
import { useEffect, useRef, useState } from "react";
import type { IntervalPoint, ReadinessRow, Verdict } from "@/services/types";

const PALETTE = {
  light: { green: "#0b6e4f", amber: "#b45309", red: "#b91c1c", orange: "#c2410c", ink: "#10171c", muted: "#8a8f94" },
  dark: { green: "#3fae86", amber: "#e08a3c", red: "#ef6461", orange: "#f97316", ink: "#f5f3ee", muted: "#8a8f94" },
};

function useDark() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const root = document.documentElement;
    const read = () => setDark(root.classList.contains("dark"));
    read();
    const mo = new MutationObserver(read);
    mo.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);
  return dark;
}

export const usePalette = () => PALETTE[useDark() ? "dark" : "light"];

export function PlotFigure({ build, label, className }: { build: (width: number) => Plot.PlotOptions; label: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => e && e.contentRect.width > 0 && setWidth(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = Plot.plot({
      width,
      style: { background: "transparent", color: "currentColor", fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: "11px", overflow: "visible" },
      ...build(width),
    });
    el.replaceChildren(chart);
    return () => chart.remove();
  }, [build, width]);
  return <div ref={ref} role="img" aria-label={label} className={className} />;
}

const fmt = (n: number) => (n >= 0 ? "+" : "") + n.toFixed(4);

// One row per model: the out-of-time gain with its 95 % interval, a rule at 0 and a tick at +materiality.
// `relative` divides by each model's materiality, so models on different metrics share one scale (tick at 1).
export function ForestPlot({ rows, relative = false, label }: { rows: ReadinessRow[]; relative?: boolean; label: string }) {
  const p = usePalette();
  const build = (_w: number): Plot.PlotOptions => {
    const s = (r: ReadinessRow, v: number) => (relative ? v / r.material : v);
    const data = rows.map((r) => ({
      ...r,
      y: r.model,
      x: s(r, r.delta),
      x1: s(r, r.delta_lo),
      x2: s(r, r.delta_hi),
      m: s(r, r.material),
    }));
    return {
      height: 40 + rows.length * 28,
      marginLeft: 260,
      marginRight: 24,
      x: { label: relative ? "gain ÷ materiality →" : "gain over benchmark →", grid: true, tickFormat: relative ? ".1f" : "+.3f" },
      y: { label: null, domain: data.map((d) => d.y) },
      color: { domain: ["green", "amber", "red"] satisfies Verdict[], range: [p.green, p.amber, p.red] },
      marks: [
        Plot.ruleX([0], { stroke: "currentColor", strokeOpacity: 0.6 }),
        Plot.tickX(data, { x: "m", y: "y", stroke: p.orange, strokeWidth: 2 }),
        Plot.ruleY(data, { y: "y", x1: "x1", x2: "x2", stroke: "verdict", strokeWidth: 3, strokeOpacity: 0.55 }),
        Plot.dot(data, {
          x: "x",
          y: "y",
          fill: "verdict",
          r: 4,
          title: (d: (typeof data)[number]) =>
            `${d.scenario} · ${d.model}\n${d.metric}: Δ ${fmt(d.delta)} [${fmt(d.delta_lo)}, ${fmt(d.delta_hi)}]\nmaterial +${d.material} · MDE ${d.mde} · ${d.verdict}`,
        }),
      ],
    };
  };
  return <PlotFigure build={build} label={label} />;
}

// One metric: each run × variant as a point with its Wilson 95 % interval.
export function IntervalChart({ points, label, domain }: { points: IntervalPoint[]; label: string; domain?: [number, number] }) {
  const p = usePalette();
  const build = (_w: number): Plot.PlotOptions => ({
    height: 30 + points.length * 22,
    marginLeft: 170,
    marginRight: 16,
    x: { label: null, grid: true, tickFormat: ".0%", domain: domain ?? [0, Math.min(1, Math.max(0.05, ...points.map((d) => d.hi)) * 1.1)] },
    y: { label: null, domain: points.map((d) => d.series) },
    color: { domain: ["keyword", "learned"], range: [p.muted, p.green] },
    marks: [
      Plot.ruleY(points, { y: "series", x1: "lo", x2: "hi", stroke: "variant", strokeWidth: 3, strokeOpacity: (d: IntervalPoint) => (d.run === points[0]?.run ? 0.6 : 0.3) }),
      Plot.dot(points, {
        x: "rate",
        y: "series",
        fill: "variant",
        r: 4,
        fillOpacity: (d: IntervalPoint) => (d.run === points[0]?.run ? 1 : 0.5),
        title: (d: IntervalPoint) => `${d.series}\n${d.k}/${d.n} = ${(d.rate * 100).toFixed(1)} % [${(d.lo * 100).toFixed(1)}, ${(d.hi * 100).toFixed(1)}]`,
      }),
    ],
  });
  return <PlotFigure build={build} label={label} />;
}
