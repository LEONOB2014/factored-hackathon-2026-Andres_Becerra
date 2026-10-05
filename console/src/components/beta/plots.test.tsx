import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { IntervalPoint, ReadinessRow } from "@/services/types";
import { ForestPlot, IntervalChart } from "./plots";

const row = (model: string, verdict: ReadinessRow["verdict"], delta: number): ReadinessRow => ({
  scenario: "05 agent and queue", model, metric: "AUC", value: 0.7, benchmark: "base rate", benchmark_value: 0.69,
  delta, delta_lo: delta - 0.001, delta_hi: delta + 0.001, material: 0.02, mde: 0.0004, verdict,
  root_cause: "generator independence", requirement_to_green: "real timestamps", n_train: 10, n_test: 5, n_test_needed: 5, best_variant: null,
});

const point = (run: string, variant: IntervalPoint["variant"], rate: number): IntervalPoint => ({
  metric: "correct", run, variant, series: `${run} · ${variant}`, rate, lo: rate - 0.05, hi: Math.min(1, rate + 0.03), k: 1, n: 1,
});

describe("ForestPlot", () => {
  it("draws one row per model with its interval, a zero rule and a materiality tick", () => {
    render(<ForestPlot label="forest" rows={[row("handle time per agent-hour", "amber", 0.0012), row("SLA breach at creation", "red", -0.008)]} />);
    const fig = screen.getByRole("img", { name: "forest" });
    const svg = fig.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(fig.textContent).toContain("handle time per agent-hour");
    expect(fig.textContent).toContain("SLA breach at creation");
    expect(fig.querySelectorAll("circle")).toHaveLength(2);
    expect(fig.querySelector('[aria-label="tick"]')).not.toBeNull();
    expect(fig.querySelector('[aria-label="rule"]')).not.toBeNull();
  });

  it("switches to the materiality-relative scale", () => {
    render(<ForestPlot label="forest" relative rows={[row("m", "red", -0.01)]} />);
    expect(screen.getByRole("img", { name: "forest" }).textContent).toContain("gain ÷ materiality");
  });
});

describe("IntervalChart", () => {
  it("draws one interval per run × variant", () => {
    const pts = [point("first scored run", "keyword", 0.6), point("first scored run", "learned", 0.95), point("after-fix", "learned", 0.958)];
    render(<IntervalChart label="correct" points={pts} />);
    const fig = screen.getByRole("img", { name: "correct" });
    expect(fig.querySelectorAll("circle")).toHaveLength(3);
    expect(fig.textContent).toContain("first scored run · learned");
    expect(fig.textContent).toContain("after-fix · learned");
  });
});
