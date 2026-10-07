# BETA AID technical report

A LaTeX monograph on the mathematical and statistical foundations of the methods behind the Grain Atlas. The design
is in [`docs/designs/technical-report.md`](../docs/designs/technical-report.md).

## Build

Needs a TeX distribution with `latexmk` and `biber` (BasicTeX plus `tlmgr`; see the design's toolchain decision).

```bash
make -C report          # build/report.pdf from the claims and figures currently in build/
uv run --directory report pytest -q
```

## Layout

| path | what it holds |
|---|---|
| `tex/main.tex` | master document: six parts, twenty chapters, five appendices |
| `tex/preamble.tex`, `tex/macros.tex` | packages, layout, `\est` / `\proto`, theorem environments, notation |
| `tex/chapters/`, `tex/appendices/` | one file per chapter or appendix |
| `tex/refs.bib` | primary sources only, each verified |
| `src/report_lib/` | claims ledger, estimators, LaTeX generation |
| `scripts/claims/`, `scripts/figures/` | one script per chapter or figure |
| `conf/` | `protocol.toml`, `notebook_map.csv` and the other inputs |
| `tests/` | the guarantees the build enforces |
| `build/` | generated, git-ignored: claims, figures, the PDF |

## The claims contract

No number derived from data is typed into a chapter. Each one is `\est{<claim-id>}{<field>}`, generated from a row of
the claims ledger. That row records the claim's kind, its status (`exploratory`, `registered` or
`positive-control`) and the hash of its source. Protocol constants are `\proto{<key>}`, generated from
`conf/protocol.toml`. An undefined id prints a red marker in the PDF and a LaTeX warning.

`latam_eda` is imported read-only from `../eda/src`, because `eda` is a virtual uv project, not an installable
package. Scripts import `report_lib.eda` first, and pytest gets the same path from `pyproject.toml`. The shared
runtime dependencies are pinned to the versions in `eda/uv.lock`.
