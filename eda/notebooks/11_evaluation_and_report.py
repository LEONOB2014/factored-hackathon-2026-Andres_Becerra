# %% [markdown]
# # 11 · Evaluation, deployment and report
# **CRISP-DM phases 5–6** · what the study established, how confident we are, what to do about it, and how to reproduce everything.
#
# **Scope.** Two folders of a synthetic LATAM bank dataset — `data/` (main) and `data_backup_20260831/` (backup) — were compared for set differences, time shift, alignment, row-level and distributional equivalence,
# and both were mined for anomalies with classical, machine-learning and deep methods.

# %%
import sys

sys.path.insert(0, "../src")
import pandas as pd
from IPython.display import IFrame, display

from latam_eda import theme
from latam_eda.data import ROOT

theme.register()
T = ROOT / "reports" / "tables"
pd.options.display.float_format = "{:,.3f}".format

# %% [markdown]
# ## 1 · Executive summary
# **The backup is not a backup.** It is a *second, independently generated realisation* of the same bank, with the same schema and the same statistical behaviour for the core tables, **plus** a small shared core of
# records and a handful of targeted defects. Restoring from it would replace most primary keys, re-attribute products and transactions to other customers, and change the meaning of fields. It must not be used as a restore
# point, and its tables must never be joined with the main tables.
#
# | topic | headline |
# |---|---|
# | **Completeness** | 2 of 13 tables absent (`call_transcripts`, `satisfaction_surveys`); `transactions` covers only 2023-07 → 2024-09 (41 % of volume) |
# | **Keys** | customers share 2.7 % of IDs, transactions 1.4 %, products 32 %; only complaints and the static tables are fully shared |
# | **Time shift** | no global shift; shared-key rows drift by 0…+7 d (transactions), −18…+11 (events), −166…0 (sends) — an ID-stream offset, not a calendar shift |
# | **Same records?** | 7 % of customers (10.5 k) exist in both, 7.5 k under a different ID; 11.7 k transaction *clones* re-dated by a few days |
# | **Mutation** | untraced credit-score re-scoring, flat-rate currency re-denomination (4,000 COP / 350 ARS per USD), owner re-attribution of every product |
# | **Replicate?** | customers, products, transactions are statistically **indistinguishable** (classifier AUC 0.50) |
# | **Targeted defects in the backup** | `interaction_type` re-labelled in Spanish; call duration/wait wiped (14 → 99 % null); `has_recording` 86 → 1 %; `was_clicked`/`was_opened` and UTM fields gain nulls |
# | **Anomaly detection** | no method sees everything; a 3-member ensemble reaches AP 0.77 vs 0.69 for the best single detector; `is_fraud` is explained by `fraud_score` alone |

# %% [markdown]
# ## 2 · Hypotheses — verdicts
# | id | hypothesis | verdict | evidence (notebook) |
# |---|---|---|---|
# | **H1a** | whole series is lagged | **Rejected** | weekday phase identical in every quarter; no cross-correlation peak (03) |
# | **H1b** | shared rows are re-dated | **Confirmed, but not a calendar shift** | monotone, drifting, table-specific offsets; not whole days for events/sends (03) |
# | **H1c** | clean re-dating of identical rows | **Confirmed for a 0.27 % core** | 11,734 transaction clones, +0…+7 d (03, 05) |
# | **H2** | backup is a re-keyed copy | **Rejected** | ≈ 93 % of customers have no counterpart; products re-attributed (02, 04, 05) |
# | **H3** | independent replicate (same generator, other seed) | **Accepted for core tables** | marginals ≈ noise; C2ST AUC 0.496–0.502 (06) |
# | **H4** | backup incomplete | **Confirmed** | 2 absent tables, transactions truncated (02) |
# | **H5** | shared records silently mutated | **Confirmed, with structure** | credit-score re-scoring, currency re-denomination, hybrids, re-attribution (05) |
#
# *Why the backup exists is not answerable from the data.* The evidence is incompatible with a compliance archive (which would be complete and identical) and fits a **partial second generation run** or a **deliberate distractor**.

# %% [markdown]
# ## 3 · The numbers behind the headlines

# %%
pk = pd.read_csv(T / "set_difference_summary.csv")
pk[
    [
        "table",
        "main_keys",
        "backup_keys",
        "shared",
        "only_main",
        "only_backup",
        "pct_main_shared",
        "status",
    ]
].style.format(
    dict.fromkeys(["main_keys", "backup_keys", "shared", "only_main", "only_backup"], "{:,.0f}")
    | {"pct_main_shared": "{:.1f}"}
)

# %%
c2 = pd.read_csv(T / "c2st.csv")
c2.style.format(dict.fromkeys(c2.columns[1:], "{:.3f}"))

# %%
nulls = pd.read_csv(T / "null_rate_comparison.csv")
nulls.reindex(nulls.delta_pp.abs().sort_values(ascending=False).index).head(10).style.format(
    {"null_main_pct": "{:.1f}", "null_backup_pct": "{:.1f}", "delta_pp": "{:+.1f}", "z": "{:,.0f}"}
)

# %% [markdown]
# ## 4 · Data-quality findings that apply to **both** folders
# These come from the generator, not from the backup path, and matter for any analysis of the dataset:
#
# | finding | size | consequence |
# |---|---|---|
# | products opened before the customer registered | 50 % | tenure features unreliable |
# | transactions before the product existed | 18.7 % | causal order broken |
# | all Mexican transactions labelled `USD`; no `MXN` anywhere | 99 % of Mexican rows | currency analysis and `amount_usd` unusable without repair |
# | ~5 % null injection on mandatory fields (`response_code`, `amount_usd`, `branch_id`, `resolution_date`) | 5 % | validation gates needed |
# | `last_updated` after the end of the data | 6 % of customers/products | temporal leakage |
# | amounts capped below 10,000 USD; Benford-non-conforming | – | no AML-threshold structuring signal |
# | `fraud_score` ≥ 35 ⇒ 100 % fraud; ≈ 45 % of fraud has low/null score | 51 % / 45 % of fraud | `fraud_score` is the label; behaviour carries no signal |
# | first transaction gap encoded as a one-year placeholder | 3 % of rows | hides dormancy anomalies |
# | UTC−6 timestamp convention fails for 8 % of interactions/complaints | 8 % | day-level joins need care |

# %% [markdown]
# ## 5 · Anomaly-detection summary

# %%
sc = pd.read_csv(T / "method_scorecard.csv", index_col=0)
cols = [
    "amount_spike",
    "foreign_burst",
    "velocity_burst",
    "low_and_slow",
    "dormant_reactivation",
    "mean recall",
    "AP",
]
sc[cols].style.format(dict.fromkeys(cols[:-1], "{:.0%}") | {"AP": "{:.3f}"}).background_gradient(
    subset=cols[:-1], cmap="Blues", vmin=0, vmax=1
)

# %% [markdown]
# **Take-aways.** (1) Detector choice depends on the anomaly class: point anomalies → robust distance/univariate screens; collective bursts → almost anything; multi-feature combinations → marginal/isolation methods; dormancy → needs feature engineering.
# (2) A small, *diverse* ensemble beats every single detector; averaging everything does not. (3) Neural detectors add explanation, not accuracy, on tabular data. (4) Judge by **average precision and a cost view**, not AUC alone.

# %% [markdown]
# ## 6 · Interactive dashboards (D3.js)
# Standalone HTML under `reports/dashboards/` (open in a browser; they load D3 from a CDN and read local data files):
#
# * **overlap.html** — key overlap per table and monthly coverage, linked views
# * **timeshift.html** — drifting offset by table with brush, clones vs collisions
# * **anomalies.html** — detector × review budget, PCA map with brush, exact recall by anomaly type, scorecard

# %%
display(IFrame("../reports/dashboards/anomalies.html", width="100%", height=900))

# %% [markdown]
# ## 7 · Recommendations
# **Governance**
# 1. Treat `data/` as authoritative; quarantine `data_backup_20260831/` and never join across folders.
# 2. Ask the data owners what the backup represents (snapshot? alternate seed? distractor?) and record the answer in the data dictionary.
# 3. Add a reconciliation control: row counts, key-overlap and C2ST/PSI checks (the notebooks provide them) before accepting any copy of the data.
#
# **Data quality** — build the gates of notebook 07 §1 into ingestion (response code on approved payments, product/customer date order, currency vs country, audit stamps not in the future); normalise `interaction_type` vocabulary; repair the `MXN`→`USD` label.
#
# **Modelling**
# 4. Never evaluate behavioural fraud models on `is_fraud` without removing `fraud_score`; expect ≈ 45 % of positives to be unfindable.
# 5. For monitoring use *two* controls: a rule-based data-quality gate and an ensemble behavioural monitor; add a first-transaction flag before building dormancy features.
# 6. Choose the review budget with a cost model (notebook 09 §7); the best detector changes with the cost ratio.
#
# ## 8 · Limitations
# * The dataset is **synthetic**; conclusions about the generator (ID-stream drift, independent draws) do not transfer to real bank data, whereas the *methods* do.
# * Anomaly benchmarks use **injected** anomalies; their absolute numbers depend on the injection design (documented in `src/latam_eda/anomaly.py`), their *relative* ordering and failure modes are the finding.
# * Customer linkage assumes the identity fields are informative; held-out-field validation supports it but there is no external ground truth.
# * Day-level time-series tests have ≈ 1,100 points per table; PELT change-point penalty was fixed (8).
# * Two statements in the early `docs/dataset/backup_comparison.md` were superseded by this series (the "re-keyed copy" and "edited records" readings); the document now points here.
#
# ## 9 · Reproducibility
# ```
# uv run scripts/download_s3.py                         # data/raw  (12.5k CSVs, ~10 GB)
# uv run scripts/eda_overview.py                        # data/parquet  + reports/eda_overview.md
# uv run scripts/build_backup_parquet.py                # data/parquet_backup
# uv run scripts/build_notebook.py notebooks/NN_*.py --execute      # rebuild a notebook (01 … 11)
# uv run scripts/export_dashboard_data.py               # JSON/JS for the D3 dashboards
# ```
# Notebooks are authored as `# %%` percent-format sources (`notebooks/*.py`) and built into `.ipynb` + HTML (`reports/notebooks/`). Shared code lives in `src/latam_eda/`.
