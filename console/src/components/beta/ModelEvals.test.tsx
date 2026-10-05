import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelEvals } from "./ModelEvals";

describe("ModelEvals", () => {
  it("renders the held-out intent scores, the tuning and one row per retrieval store", () => {
    render(
      <ModelEvals
        intent={{
          tuning: { params: { threshold: 0.73 }, cv_macro_f1: 0.7399, target_precision: 0.9, oof_coverage_at_threshold: 0.5291, mlflow_run_id: "7d620b491128481d" },
          held_out: [
            { model: "learned_char_ngram_lr", n: 132, accuracy: 0.8182, macro_f1: 0.8196, macro_f1_by_language: { es: 0.7893, pt: 0.8492 }, ece: 0.0806, coverage_at_threshold: 0.6136, accuracy_when_confident: 0.963 },
            { model: "keyword_baseline", n: 132, accuracy: 0.5758, macro_f1: 0.6055, ece: null },
          ],
        }}
        retrieval={{ bundled: { n_test: 21, "hit@1": 0.75, mrr: 0.833 }, graph: { n_test: 21, "hit@1": 0.688, governance_violations: 0 } }}
      />,
    );
    expect(screen.getByText("learned_char_ngram_lr")).toBeInTheDocument();
    expect(screen.getByText("81,8 %")).toBeInTheDocument();
    expect(screen.getByText("0,730")).toBeInTheDocument();
    expect(screen.getByText("7d620b49")).toBeInTheDocument();
    expect(screen.getByText("bundled")).toBeInTheDocument();
    expect(screen.getByText("68,8 %")).toBeInTheDocument();
  });

  it("says when a deployment bundles no reports", () => {
    render(<ModelEvals intent={null} retrieval={{}} />);
    expect(screen.getByText(/no intent-model report|no incluye el reporte del modelo/)).toBeInTheDocument();
  });
});
