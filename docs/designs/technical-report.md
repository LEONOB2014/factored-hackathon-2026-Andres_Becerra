# Design: BETA AID Technical Report — the mathematical and statistical foundations behind the Grain Atlas

Design: 2026-10-07 · Engineering review: 2026-10-07
Branch: `docs/technical-report`
Repo: LEONOB2014/factored-hackathon-2026-Andres_Becerra
Status: approved (design and engineering review, 2026-10-07)

## Problem Statement

The Grain Atlas (eda/reports/dashboards/grain_atlas) presents the results of the exploratory phase at four grains
(event, country, daily, hourly), and the readiness gates (ADR-016 to ADR-018) that decide which grain cells may feed
a model. The methods behind those results live in 65 distinct notebook sources (about 40,000 lines of Python in
`eda/notebooks/**`, jupytext `.py` paired with executed `.ipynb`). Nowhere is there a single, rigorous document that
states each method's mathematics, its assumptions, why it was chosen, what its results mean, and what follows for the
pipelines. The author wants that document: a scientific technical report in LaTeX, independent chapter files
consolidated by a master document, meeting academic standards (sources, tables, figures, reproducibility), that
serves as "the backing and technical support of all the pipelines".

## What Makes This Cool

- **No statistic is typed into prose.** Every data-derived number in chapter prose, including inside math, is an
  `\est{claim-id}{field}` macro generated from a claims ledger row (its kind-specific fields, status and the hash of
  its source). Every generated table is rendered from one hashed source whose path and SHA-256 appear in its caption;
  its cells are not individual claims. Protocol constants (gate thresholds, clock offsets, the cut-off date) are `\proto{key}` macros
  generated from `protocol.toml`. The lint rejects any typed integer, decimal, percentage or number word (two and above) in
  chapter prose and in math mode outside a closed allowlist (see Recommended Approach → Lint). Figures are not macros, but each figure script reads
  only manifest rows or hashed sources and writes its inputs' hashes into `build/figures/manifest.csv`, and
  `test_figures.py` checks every included figure against it. The author's standing rule — measured numbers with denominators and intervals, never
  invented — becomes a property of the build, not a habit.
- **The readiness gate is the spine.** Each chapter ends by saying which gate decision its methods feed, and whether
  changing the method could flip that gate. A reader can follow any pipeline decision back to its mathematics.
- **It re-earns its own numbers, honestly.** Notebook results are labelled exploratory. Every gate-driving claim is
  re-estimated out of time under a specification registered before the re-run (status `registered`), with
  clustered intervals. The design says plainly that this is not an untouched holdout: the notebooks already saw
  those rows.

## Constraints

- **Local only.** No push, PR, merge, tag, release or redeploy while the hackathon evaluation runs (author's instruction of 2026-10-07). Commits allowed on a local worktree branch.
- **Repository rules** (AGENTS.md): worktree per branch under `../antigravity-worktrees/`, branch from
  `origin/develop`, Conventional Commits enforced by hooks, data never in git, secrets never printed.
- **Evidence rules** (author's standing rules): measured numbers with denominators and intervals; null results stated and turned
  into diagnoses; no synthetic data presented as evidence; checkable primary sources only; outside material the user
  shared is never named or cited; never disparage other teams.
- **Machine:** macOS, no TeX distribution installed, 29 GiB free on a 460 GiB disk (94 % used). Dataset is local in
  the main checkout's git-ignored `data/` (symlinked into worktrees).
- **Scale:** dataset rows include 4.4 M transactions and 15.6 M digital events; estimators that re-scan must use
  DuckDB over parquet, not pandas in memory.

## Premises

1. **Scope** is exactly the 65 notebook sources the Atlas indexes, plus the readiness gates they feed:
   event grain (`notebooks/01–11`, `medallion/01`, `model_risk/01–02`, `pipeline/01–12`); country grain (one
   14-notebook template, `country_template/01–14`, executed 8 times — MX, CO, AR, ALL on main and backup — plus
   `country_compare/01`, `dataset_compare/01`); daily grain (`granularity/01–09`, `granularity_time/01–05`); hourly
   grain (`granularity_hour/01–09`). The country template is one methods treatment with per-market results, not eight
   copies. The copilot evaluation (`copilot/eval`) is out of scope (the Atlas does not index it).
   **Amended (named extensions):** three new estimators adopted during review are in scope, and no
   others: the paired main–backup disagreement estimator (Ch. 6), the business-date flip rate by country (Ch. 4) and
   the cross-grain consistency check (Ch. 14). Their manifest rows carry `source_type=scripted` (no notebook source).
   Appendix A lists them in a separate "report-only analyses" block with their rationale. **Contradiction policy:**
   if any of them, or any registered re-estimation, disagrees with a current gate decision, the report states it as
   a finding with its numbers. Gates, ADRs and pipelines are not changed by this work.
2. **Structure follows the scientific argument**, not notebook numbering, with a generated traceability appendix
   mapping every notebook section to the report section that justifies it.
3. **(Revised after review.)** Every number comes from an executed artefact
   or a scripted re-run on the real dataset, with the fields its claim kind requires (see the claim schema).
   - **Statuses (closed enum):**
     - `exploratory`: numbers from notebooks or the 147 tables, except the `notebooks/08` injected-anomaly
       benchmark, which is `positive-control`. `test_manifest.py` derives the expected status from `source_type` and
       `source_path`, so the exception is checked, not implied.
     - `registered`: an out-of-time re-estimation under a specification frozen in `protocol.toml` at P3, before
       any clustered gate estimate is computed. The frozen specification covers gate claim ids, estimator, cluster
       unit, threshold, family, cut-off, main/backup tolerance, the disagreement rule and the dataset hashes. Any later
       change is a dated, reasoned amendment listed in Chapter 19; registered rows cite the `protocol.toml` git
       commit in force when they ran.
     - `positive-control`: an injected-anomaly benchmark, never mixed into real-data tables or gate claims.
   - **What `registered` cannot claim:** the dataset ends on 2026-06-17 (the process-date range in
     `eda/reports/eda_overview.md`; re-measured at P3 as a max-timestamp query per table and stored as a `\proto`
     value) and has no later rows, so no untouched
     holdout exists. The post-cut-off window was already seen by the notebooks (`notebook_map.csv` column `data_window_end`
     generates the list in Appendix A; if all saw it, Appendix A says so in one sentence). A
     `registered` re-estimation rules out specification drift and naive intervals. It does not rule out choices
     already shaped by those rows, and Chapter 2 says so.
   - **Resampling and null results:** bootstrap and permutation resampling of real rows is allowed. Null results stay
     null and become diagnoses.
   - **Multiple testing:** controlled per declared family with Benjamini–Hochberg over every test performed in the
     family's scope, cited or not (see Contracts → Multiplicity).
4. **Figures** are vector PDFs produced only by scripts from the real tables and dataset; no screenshots of the
   interactive charts.
5. **Citations** are primary, checkable sources (original method papers, standard textbooks, software papers), each
   verified (DOI, ISBN or stable URL) before it enters `refs.bib`; BibLaTeX.
6. **Local only** (see Constraints).

## Recommended Approach

**Approach B — a `report/` uv project that turns data into claims, claims into macros, and macros into a LaTeX
monograph.**

### Layout (in worktree `../antigravity-worktrees/docs-technical-report`)

```
report/
  README.md                 how to build, what each directory holds, the claims contract
  pyproject.toml uv.lock    own uv project; path dependency on eda (latam_eda loaders)
  Makefile                  data → claims → figures → latexmk → build/report.pdf
  conf/
    protocol.toml           frozen at P3: cut-off, gate claim ids, thresholds, cluster policy, BH family scopes and
                            sizes, main/backup tolerance, disagreement rule, dataset hashes, dataset end date
    notebook_map.csv        notebook heading → report label or out_of_scope_reason, data_window_end; Appendix A
    lint_allow.txt          closed allowlist for the lint, one reason per entry
  src/report_lib/
    manifest.py             claim schema (pydantic, discriminated by kind; see Contracts below)
    sources.py              readers for eda/reports/tables/*.csv and notebook outputs (hash each artefact)
    estimators/             wilson.py, cluster_bootstrap.py, cluster_robust.py, bh.py, paired_main_backup.py,
                            business_date_flip.py, cross_grain_consistency.py, reestimate.py
    texgen.py               manifest → build/generated/claims.tex (\est); protocol.toml → protocol.tex (\proto);
                            hashed sources → tables/*.tex (booktabs, path and SHA-256 in each caption)
    db.py                   one DuckDB connection: memory_limit, temp_directory under build/tmp, threads
  scripts/
    claims/NN_*.py          one script per chapter: reads sources / runs estimators, overwrites
                            build/claims/NN.parquet (amended by eng review A1, D15; texgen merges strictly)
    figures/NN_*.py         one script per figure: matplotlib, PDF, embedded fonts, colour-blind-safe palette
  tex/
    main.tex                master: explicit \include list of every chapter; front matter, parts, appendices
    preamble.tex            KOMA scrbook, amsmath/amsthm, siunitx, booktabs, biblatex (biber), cleveref, hyperref
    macros.tex              \est, \proto, notation macros, theorem environments
    chapters/NN_*.tex       one file per chapter, buildable selectively via \includeonly
    refs.bib                verified primary sources only
  tests/
    test_no_bare_numbers.py lint (see Contracts → Lint), with cases proving a typed decimal fails in inline and
                            display math; walks chapters with pylatexenc LatexWalker (eng review Q1, D17)
    test_figures.py         every \includegraphics target has a row in build/figures/manifest.csv whose input
                            hashes match manifest rows or hashed sources
    test_tables.py          every generated table's caption hash matches the file it was rendered from
    test_protocol.py        freeze integrity against freeze_commit and [[amendments]] (eng review Q3, D19)
    test_manifest.py        every \est and \proto id exists; each row valid for its kind; status in the closed enum;
                            source hash matches; positive-control rows never referenced by gate claims or
                            real-data tables; every test claim names a declared family and carries q;
                            each family's test count equals the size declared in protocol.toml; every gate id in protocol.toml has a registered row
    test_traceability.py    parses level-1/2 markdown headings from each jupytext source; every heading has a
                            notebook_map.csv row with a report label or an out_of_scope_reason; 65/65 sources
    test_bib.py             every \cite key in refs.bib; every entry has doi | isbn | url and a row in
                            conf/bib_verification.csv (key, identifier, date resolved, resolved title)
  build/                    git-ignored: manifest.csv, generated/, figures/, report.pdf
```

### Contracts

**Claim schema (kinds).** Each row has `id` (`<chapter>.<topic>`, one row; the macro's second argument picks the field), `kind`, `status`, `source_type`
(`notebook` | `table` | `scripted`), `source_path`, `source_sha256`, `chapter`, and the fields its kind requires.
Only values cited in prose become claims. Every generated table is rendered from one hashed source whose path and
SHA-256 appear in its caption; its cells are not individual claims (checked by `test_tables.py`). Exception: test
families, below, include uncited tests.

| kind | required | interval |
|---|---|---|
| `count` | value | none |
| `proportion` | num, den, lo, hi, interval_method, cluster_unit | any method from the enum below |
| `rate` | events, exposure, lo, hi, interval_method, cluster_unit | any method from the enum below |
| `difference` / `ratio` (incl. hazard ratio, coefficient) | estimate, se or lo/hi, interval_method, cluster_unit | model-based robust, or bootstrap |
| `test` | statistic, df or null distribution, p, family_id, q, family_size | p cluster-robust per the cluster policy on nested data; q from BH within family |
| `metric` (AUC, MAE, recall …) | estimate, n, lo, hi, interval_method | bootstrap over the cluster unit, or DeLong for AUC |
| `location` (change point, date, threshold crossing) | value, method; optional lo/hi | bootstrap if reported |
| `descriptive` | value, reason it carries no inference | none |

`interval_method` is a closed enum: `naive-iid`, `wilson-iid`, `poisson-exact`, `cluster-bootstrap`,
`block-bootstrap`, `wild-cluster-bootstrap`, `cr2`, `delong`, `model-robust`. `cluster_unit = none` is allowed
only with `naive-iid`, `wilson-iid` or `poisson-exact`.

**Gate-driving claim** (amended by eng review E1, D11). The 11 rows of `latam_eda.hour_models.scorecard()` (ADR-018):
each row's out-of-time gain `delta` over its benchmark and its bootstrap distribution. `protocol.toml` freezes the
11 row ids for all gates, whatever their current verdict. Choosing the re-estimation scope by outcome is not allowed.

**Disagreement rule** (amended by eng review E1, D11; frozen at P3). The registered re-estimate passes the clustered
bootstrap distribution to the imported, unmodified `latam_eda.granularity.readiness_verdict()`. That function
applies ADR-018's rule: green, amber or red, from materiality, the minimum detectable effect and fold stability.
Chapter 19 reports each row's verdict and root cause before and after. A disagreement is a changed verdict or a
changed root cause, reported as a finding, never as a gate change. The three report-only estimators carry no
gate, so they are reported against their stated null, with their family's q-value.

**Multiplicity.** `protocol.toml` declares families: one per grain series (event, country, daily, hourly), plus
the gate family. Each family is defined by a selection rule over sources (all p-values in the named stored tables
and scripted runs in its scope), not by citation, and its size is recorded at the P3 freeze. `bh.py` computes q over
every test in the family; only cited tests become `\est` claims, and the report prints the family size next to each
q. A sentence using "significant" or "significance" must contain an `\est{…}{q}`; the lint enforces it.

**Cluster policy** (recorded per family in `protocol.toml`, with its reason):
- **Customer-level outcomes:** customer clusters. For customers nested in branches, use two-way clustering when
  both counts reach 30, otherwise cluster on customer.
- **Day-indexed series at the daily and hourly grains:** a stationary bootstrap with block length chosen by the
  Politis–White automatic rule. Hourly series are blocked on days (hours stay together within their day). Plain cluster bootstrap is not used, because days are serially correlated.
- **Few clusters:**
  - Below 30 clusters, use the wild cluster bootstrap (Rademacher weights) or CR2 small-sample correction.
  - Below 10 clusters, such as the three markets, a claim is `descriptive` with no inferential interval.
- **Tests:** `cluster_bootstrap.py` and `cluster_robust.py` have unit tests on simulated nested data with known
  coverage. That simulated data is test fixtures only, never evidence.

**Dataset copy and pinning.**
- **Which copy:** gate-driving and registered claims run on **main**, the copy the pipeline serves. The backup enters
  through the paired estimator. Each gate claim also gets a backup re-run, and where their estimates differ by more
  than the frozen tolerance, the gate row is flagged `copy_disagreement` in Chapter 19. The tolerance is the 95th
  percentile of the paired estimator's sampling-noise baseline from Chapter 6, on the absolute difference.
- **Pinning:** `protocol.toml` records the SHA-256 of every parquet file at the P3 freeze, and `test_manifest.py`
  checks that `scripted` rows cite those hashes. Before P3 no scripted rows exist.

**Exploratory intervals.** Stored intervals from the 147 tables keep `interval_method=naive-iid` and are rendered
with a dagger and a footnote: "computed treating rows as independent; likely too narrow". Chapter 2 explains this.
Proportions that are gate-driving are recomputed, so a gate never rests on a naive interval.

**Lint.** It scans prose **and math mode**. It fails on any digit sequence, and on number words from "two" up, outside
`\est`, `\proto`, `\ref`, `\eqref` and `\cite`. The closed allowlist covers four-digit years 1900–2099,
chapter, section and equation references, and `conf/lint_allow.txt`, where each entry has a reason. That file holds
notation digits in math (exponents in formulas, constants such as 1/2, indices) and fixed structural counts, which
are `\proto` constants where possible (two copies, three markets, four grains, six parts). "One" is not flagged.

**Pre-commit.** The report tests run in pre-commit on every commit. Before the P3 freeze, the checks that depend on
the freeze (gate ids, dataset hashes, family sizes) are skipped, because `protocol.toml` has `frozen = false`; after
the freeze they are mandatory. Stubs must pass the lint and traceability checks from P1. Nothing passes through
`--no-verify`.

**Resources.** `db.py` opens `latam_eda.data.connect()` and applies `latam_eda.pipeline.SETTINGS` (memory_limit
4 GB, 6 GB spill, 4 threads; amended by eng review E4, D14), with `temp_directory` set to `build/tmp`. The disk budget
(amended by eng review P1, D22) is TeX ≤ 2 GiB + DuckDB spill ≤ 6 GiB + build ≤ 4 GiB + one scratch scope
(measured at P0, est. 4–8 GiB), at most 20 GiB. Gate re-runs run main, then backup, with `LATAM_SCOPE_DIR` under
`report/build/scratch`, and delete each scope's scratch once its CSV is written. `make` stops with a message unless
the budget plus 5 GiB is free.

**Privacy** (added by eng review A2, D16). `texgen.py` and every figure script reject identifier columns (`*_id`,
names, account and card numbers, free text) and any table cell or plotted group with fewer than
`\proto{privacy.min_cell}` contributing customers (10, in `protocol.toml`). `test_tables.py` and `test_figures.py`
enforce it.

**Effort and the minimum viable report.**

| Phase | Human | CC |
|---|---|---|
| P0–P1 worktree, toolchain, skeleton | ~2 days | ~1 h |
| P2 claims machinery and tests | ~1 week | ~3 h |
| P3 evidence model, Ch. 2 | ~1 week | ~3 h |
| Parts II–VI, per chapter (≈ 1 h per method section, reusing stored tables for exploratory claims) | ~3–5 days | ~2–4 h |
| P10 gate-input estimators (learnability metrics of Ch. 18, audit and SLO rates of Ch. 13, scorecard inputs) + re-estimation, Ch. 19 | ~2 weeks | ~1–2 sessions |
| P11 front and back matter | ~3 days | ~2 h |
| **Total** (18 content chapters) | **~3–4 months** | **~12–16 sessions** |

The **minimum viable report** is Part I, Chapter 19 with its registered re-estimation (and the gate-input
estimators that P10 builds for it), the claims machinery and all tests, and every other chapter as a structured stub. A stub has its method list, its notebook mapping and its
gate links, and it passes the lint. Parts are added in order II → III → IV → V → VI, so stopping at any point
leaves a coherent, buildable document.

### Chapter plan (master document in six parts)

Front matter: abstract, notation and conventions, reproducibility statement, how to read the claims macros.

**Part I — Foundations**
1. Introduction: LATAM Bank, the dataset, the two copies, the readiness question, contributions, reading guide.
2. The evidence model: estimands, claims ledger, the status enum (exploratory, registered, positive-control) and what each can claim, cluster-robust and bootstrap intervals,
   Wilson / Clopper–Pearson and when they fail on nested data, multiplicity (BH families), the registered re-estimation protocol and its limits.

**Part II — Data integrity**
3. Inventory, keys and set difference: coverage, surrogate vs natural keys, content fingerprints (`notebooks/01–02`,
   `medallion/01`).
4. Time: shift diagnostics (constant / linear / segmented drift model comparison, matched filter), the delivery-day
   clock scan (ADR-014), business-date flip rates by country (`notebooks/03`, `granularity_time/01`,
   `country_template/04`).
5. Record linkage and comparable rows: Fellegi–Sunter with EM, natural-key alignment, clone detection, mismatch
   taxonomy and transition matrices (`notebooks/04–05`).
6. Are the two copies the same process? Sampling-noise baselines, positive and negative controls, classifier
   two-sample test, dependence structure, Benford's law; the paired main–backup estimator (`notebooks/06`,
   `dataset_compare/01`).
7. Schema forensics, contracts and drift: layered detectors L0–L4 with positive controls, the circuit breaker,
   country baselines and the binomial noise of empty shares, monthly stability (`model_risk/01–02`,
   `pipeline/02–03`, `country_template/02–03`).

**Part III — Anomalies and change**
8. Anomaly detection: integrity rules, robust univariate outliers, robust Mahalanobis (MCD), Isolation Forest, COPOD,
   autoencoder and VAE, the supervised ceiling, the `fraud_score` leakage, cost-based evaluation, rank-fusion
   consensus (`notebooks/07–11`, `country_template/13` §3–4).
9. Change points and process control: PELT and penalty choice, control charts and alert rates
   (`country_template/13` §1–2, `granularity/04` §5, `granularity_time/02` §5).

**Part IV — The pipeline as a statistical object**
10. Conformance: FX backbone and conversion, USD imputation and its bias, SCD2 snapshots, point-in-time joins
    (`pipeline/04–06`, `country_template/05–06`).
11. Marts, rules and features without leakage: deterministic rules, additive scores, out-of-time splits with embargo,
    point-in-time windows, single-feature AUC; the known R25 defect in `mart_card_support` / `mart_transaction_disputes`
    reported as a defect with its counts (`pipeline/07–09`, `country_template/07–09`).
12. Graph exports and privacy: degree distributions, bounded contributions, noise on small cells
    (`pipeline/10–11`, `country_template/10–11`).
13. Audit, SLOs and the three gates; emulator fidelity (`pipeline/12`, `country_template/12`).

**Part V — Grain**
14. Aggregation theory: bus matrix, information loss under aggregation, the ecological fallacy measured, the
    cross-grain consistency check (`granularity/01`, `granularity/09` §1–2, `granularity_hour/01`).
15. Customer dynamics: activity Markov chain, cohorts, count models, value concentration, Kaplan–Meier, Cox PH,
    lifetime-value proxy, preferred hour and dayparts (`granularity/02–03`, `granularity_hour/02`).
16. Operations: rolling-origin forecast backtests, Granger causality, hierarchical coherence, newsvendor, Erlang C,
    reliability of agent league tables, fairness test, censored case clocks and regulatory deadlines
    (`granularity/04–06`, `granularity_time/02`, `granularity_hour/03–06`).
17. Products, campaigns and the limits of causal claims: vintages, why roll rates cannot be built, dormancy, campaign
    economics, sequences and bursts, the campaign decision cell, allocation policies, the holdout that would settle
    causation (`granularity/07–08`, `granularity_time/03–05`, `granularity_hour/07`).

**Part VI — Learnability and readiness**
18. Which targets are learnable? Candidate models out of time by country, the learnability map
    (`country_template/14`, `country_compare/01`, `pipeline/09` §4).
19. Readiness gates as decisions: the scorecard, gate thresholds, false-discovery control across the series, the
    re-evaluation loop, and the registered re-estimation results on main and backup (`granularity/09` §3, `granularity_hour/08–09`,
    ADR-016–018).
20. Discussion, limitations and conclusions.

**Appendices:** A traceability matrix (generated from `notebook_map.csv`); B claims ledger (generated); C per-country
tables; D software, versions and environment; E notation index.

Each method section follows one template: question → estimand → model and assumptions (stated formally) → why this
method over alternatives → estimation and inference → diagnostics → results (macros, tables, figures) →
interpretation → implications for the pipeline and the gate → limitations.

## Open Questions

**Resolved at P0 (user answers, 2026-10-07):** (1) toolchain: BasicTeX + tlmgr (latexmk, biber); (2) notebooks/08
injected anomalies kept as `positive-control`; (4) English; (5) KOMA `scrbook`, A4, two-sided; (6) `build/` stays
git-ignored, no PDF committed. Still open: (3) the cut-off date, decided at P3 after the dataset end date is measured.


1. **TeX toolchain.** Options: Tectonic (small, self-fetching, but biber versions must match), BasicTeX + `tlmgr` +
   latexmk + biber (~1–2 GiB), MacTeX-no-gui (~5–7 GiB of 29 GiB free), or a Docker TeX Live image (~4–5 GiB).
   Leaning BasicTeX + tlmgr for a standard latexmk + biber toolchain at modest disk cost. Needs the user's go-ahead
   to install.
2. **Injected anomalies.** `notebooks/08` measures detector recall on a benchmark with injected anomalies. This is
   a positive control, not evidence about the bank.
   - **Proposed:** keep it under `status=positive-control` (already in the closed enum and enforced by
     `test_manifest.py`), with the injection mechanism stated.
   - **If you reject it:** the `notebooks/08` recall numbers are excluded. Their headings stay in `notebook_map.csv`
     with `out_of_scope_reason = "synthetic positive control excluded by author"`, and Chapter 8 reports only the
     real-label checks (`is_fraud`).
3. **Cut-off date.** Which date separates history from the re-estimation window? The scope is already fixed: all
   gates, listed before the re-run.
4. **Language.** English, matching the repository; confirm.
5. **Document class and format.** KOMA `scrbook`, A4, two-sided; confirm or name a house style.
6. **The built PDF.** Keep `build/` git-ignored and regenerate, or also commit a dated PDF on the local branch.

## Success Criteria

- `make -C report` on a clean worktree with the local dataset produces `build/report.pdf` with no undefined
  references or citations and no overfull boxes beyond 1 pt.
- `uv run pytest report/tests` is green:
  - the lint finds zero violations;
  - every `\est` and `\proto` id resolves;
  - every manifest row is valid for its kind and status, with a matching source hash;
  - every `test` claim has a family and a q-value.
- Traceability: 65/65 notebook sources are mapped. Every level-1 and level-2 heading parsed from the jupytext
  sources has a report label or an out-of-scope reason. The three report-only analyses appear in their own block.
- Every gate id listed in `protocol.toml` has a `registered` row with an interval clustered per the cluster policy,
  a backup re-run, its verdict and root cause before and after (E1), and its NaN-draw share. Rows above the share
  limit carry `not-assessable` (Q2). Every other notebook-derived claim is
  `exploratory`, except the `notebooks/08` injected-anomaly claims, which are `positive-control`. Naive intervals
  are visibly marked.
- Every `refs.bib` entry has a DOI, ISBN or stable URL that was resolved during writing; no secondary summary is cited
  for a method's definition.
- Every chapter contains, for each method: assumptions, rationale, formal statement, results, interpretation,
  implications and limitations.
- The pre-commit hooks pass on every commit; nothing is pushed.

## Distribution Plan

Local PDF at `report/build/report.pdf`, built by `make -C report`. No publication while the evaluation runs. After it
ends, the user decides whether to push the branch, open a PR into `develop`, and attach the PDF to a release.

## Dependencies

- A TeX distribution (Open Question 1).
- The local dataset in the main checkout's `data/`, symlinked into the worktree.
- The `eda` uv environment (`latam_eda` loaders, DuckDB, scipy, statsmodels, scikit-learn, lifelines, ruptures, pyod).
- ADR-014 and ADR-016 to ADR-018 (gate definitions) and `docs/strategy/13_data_readiness_audit.md`.
- The known R25 defect is reported as is, not fixed in this work: `fct_complaint.affected_product_id` never belongs
  to the complainant, so `mart_card_support.open_cases` counts other customers' complaints, and most dispute links are
  `none` (counts re-measured as claims in Chapter 11).

## Next Steps

1. **P0 — Worktree and toolchain:** `git worktree add -b docs/technical-report
   ../antigravity-worktrees/docs-technical-report origin/develop`, symlink `data/`, install the chosen TeX toolchain.
   `origin/develop` was checked on 2026-10-07 and matches `main` for every input (`eda/notebooks`, the Grain Atlas,
   `docs/platform/adr`, `docs/strategy/13_data_readiness_audit.md`). P0 re-checks this before branching. Commit an
   engineering extract of this design as `docs/designs/technical-report.md`: problem, premises, approach, contracts,
   chapter plan, success criteria. The coaching section, the cross-model transcript and private tool references stay
   in the private copy.
2. **P1 — Skeleton:** `report/` uv project, `main.tex` with six parts and twenty empty chapters, preamble and macros,
   Makefile; `latexmk` builds an empty book.
3. **P2 — Claims machinery:** manifest schema, artefact hashing, `texgen.py`, `db.py`, all tests failing closed
   and wired into pre-commit; ingest
   the 147 result tables as `status=exploratory`.
4. **P3 — Evidence model and freeze:** the dataset end date is measured, the cut-off chosen, and `protocol.toml` is
   **frozen** before any clustered gate estimate exists. The freeze covers gate claim ids, estimators, cluster units,
   thresholds, BH family scopes and sizes, the main/backup tolerance, the disagreement rule and the dataset hashes.
   The freeze commit is recorded. This phase also builds the cluster bootstrap, block bootstrap and cluster-robust
   estimators with unit tests, and writes Chapter 2.
5. **P4…P9 — Parts II to VI**, one phase per part: claims scripts, figure scripts, verified citations, chapter prose,
   build, lint, local commit per chapter.
6. **P10 — Registered re-estimation:** build the gate-input estimators. Re-run every gate-driving claim on main and
   backup under the frozen `protocol.toml`, citing its commit, and report each gate's verdict and root cause before and
   after (E1), with its NaN-draw share (Q2). Write the Chapter 19 results, listing every amendment since the freeze, and Appendix B.
7. **P11 — Front and back matter:** abstract, conclusions, appendices, index; full build; a read-through against the
   success criteria.


## Approaches considered

- **Narrative over stored results:** rejected; weakest under statistical review, no single source of truth per claim.
- **Claims ledger with a reproducible build:** chosen (this document).
- **Executable book (Quarto to LaTeX):** rejected; chapter sources would not be plain LaTeX files.

## Engineering review decisions

| ID | Decision |
|---|---|
| Structure | Standalone `report/` uv project; `latam_eda` imported read-only, except E2 |
| E1 | Gates are the 11 rows of `hour_models.scorecard()`; re-estimation re-runs `readiness_verdict()` on a clustered bootstrap; disagreement is a changed verdict or root cause |
| E2 | Default-off cluster/block switch in `granularity.paired_boot`, `hour_models.scorecard(cluster=)`, `readiness_check.py --cluster` |
| E3 | The report has its own `bh.py` |
| E4 | `db.py` uses `data.connect()` with `pipeline.SETTINGS` (4 GB, 6 GB spill, 4 threads) |
| A1 | Per-chapter claim files, strict merge (duplicates and orphan ids fail) |
| A2 | Build refuses identifier columns and cells under 10 customers |
| Q1 | Lint walks LaTeX with pylatexenc (prose and math) |
| Q2 | Clustered runs record the NaN-draw share; above 5 % a gate is not assessable |
| Q3 | Git-backed protocol freeze with recorded amendments |
| T1 | Default path proven by unit identity and a byte-for-byte golden scorecard |
| T2 | Report BH tested for equivalence with `bh_fdr` and statsmodels |
| P1 | Measured disk budget ≤ 20 GiB, scopes run sequentially, scratch deleted after each |
| TD1 | R25 defect tracked in `TODOS.md` |
