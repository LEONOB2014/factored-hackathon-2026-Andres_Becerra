# %% [markdown]
# # 01 · Main against the backup run as main
# **Dataset comparison** · the country series on main (`notebooks/country_*`) against the same template run on
# `data_backup_20260831` as if it were the production source (`notebooks/backup_*`), for the whole bank and each country
#
# The backup-as-main series asked one question: **what if the quarantined folder had been delivered as the source?**
# Every number below was computed by the same template on each dataset, so a difference is a property of the data, not
# of the method. The notebook reads only the summary tables in `eda/reports/tables` (`country_*.csv` and `backup_*.csv`):
# no lakehouse is needed. It answers, in order: how big and how long each dataset is; whether the platform would accept
# the backup; which rules, calendar effects and anomalies change; and which modelling conclusions survive.

# %%
import sys
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import show

from latam_eda import theme

theme.register()
T = Path("../../reports/tables")
SCOPES = ["ALL", "MX", "CO", "AR"]
SCOPE = {"ALL": "whole bank", "MX": "Mexico", "CO": "Colombia", "AR": "Argentina"}
PREFIX = {"main": "country", "backup": "backup"}


def read(kind: str) -> pd.DataFrame:
    return pd.concat(
        [
            pd.read_csv(T / f"{PREFIX[d]}_{c.lower()}_{kind}.csv").assign(country=c, dataset=d)
            for d in PREFIX
            for c in SCOPES
        ],
        ignore_index=True,
    ).assign(scope=lambda x: x.country.map(SCOPE))


# %% [markdown]
# ## 1 · Size and time coverage
# Rows of every bronze table, and the window each event table covers.

# %%
size = read("size")
bank = size[size.country == "ALL"]
rows = bank.pivot_table(index=["zone", "table"], columns="dataset", values="rows").fillna(0)
rows["backup / main %"] = (100 * rows.backup / rows.main.replace(0, np.nan)).round(1)
show(rows.astype({"main": int, "backup": int}), paging=False)
span = bank[(bank.zone == "bronze_raw") & (bank.partitions > 1)].copy()
span["first_partition"] = pd.to_datetime(span.first_partition)
span["last_partition"] = pd.to_datetime(span.last_partition)
fig = px.timeline(
    span,
    x_start="first_partition",
    x_end="last_partition",
    y="table",
    color="dataset",
    title="Time span of each event table, main against the backup (bronze)",
)
fig.update_layout(height=380, yaxis_title=None, barmode="group")
fig.show()
gone = rows[(rows.backup == 0) & (rows.main > 0)].reset_index()
tx = rows.loc[("bronze_raw", "transactions")]
tx_span = span[span.table == "transactions"].set_index("dataset")
display(
    Markdown(
        f"**The backup holds {tx['backup / main %']:.0f} % of main's bronze transactions** "
        f"({int(tx.backup):,} against {int(tx.main):,}), dated {tx_span.loc['backup', 'first_partition']:%Y-%m-%d} to "
        f"{tx_span.loc['backup', 'last_partition']:%Y-%m-%d} against main's "
        f"{tx_span.loc['main', 'first_partition']:%Y-%m-%d} to {tx_span.loc['main', 'last_partition']:%Y-%m-%d}; "
        f"it has no rows at all for {', '.join(sorted(set(gone.table)))}. The other tables are about the same size "
        "and cover the same three years."
    )
)

# %% [markdown]
# ## 2 · Profile: who the customers are and how they transact

# %%
prof = read("profile").set_index(["scope", "dataset"]).drop(columns="country")
show(prof.T, paging=False)

# %% [markdown]
# ## 3 · Would the platform accept the backup? The contract and the breaker

# %%
ctr = read("contract")
show(ctr.drop(columns="country").set_index(["scope", "dataset"]), paging=False)
fig = px.bar(
    ctr,
    x="scope",
    y="partitions_held_country_contract",
    color="dataset",
    barmode="group",
    title="Partitions held with baselines fitted to each scope's own data",
)
fig.update_layout(height=320, xaxis_title=None)
fig.show()
rec = read("reconciliation")
show(
    rec[rec.country == "ALL"]
    .drop(columns=["country", "scope"])
    .set_index(["dataset", "table_name"]),
    paging=False,
)

# %% [markdown]
# ## 4 · Integrity rules, whole bank

# %%
slo = read("rule_slo")
bank_slo = slo[slo.country == "ALL"].pivot_table(
    index="rule_id", columns="dataset", values="country_rate_pct"
)
bank_slo["difference (points)"] = (bank_slo.backup - bank_slo.main).round(2)
bank_slo["SLO max"] = slo[slo.country == "ALL"].groupby("rule_id").global_max_pct.first()
show(bank_slo.round(2).sort_values("difference (points)", key=abs, ascending=False), paging=False)
fig = px.scatter(
    bank_slo.reset_index(),
    x="main",
    y="backup",
    hover_name="rule_id",
    text="rule_id",
    title="Rule violation rate (%), whole bank: main against the backup",
)
fig.add_shape(type="line", x0=0, y0=0, x1=100, y1=100, line=dict(dash="dot"))
fig.update_traces(textposition="top center")
fig.update_layout(height=480)
fig.show()

# %% [markdown]
# ## 5 · Calendar effects

# %%
cal = read("calendar_effects")
keep = {
    "C(iso_weekday)[T.6]": "Saturday",
    "C(iso_weekday)[T.7]": "Sunday",
    "is_holiday": "holiday",
    "is_long_weekend": "long weekend",
    "payday_window": "payday window",
    "is_month_end": "month end",
    "is_bonus_month": "bonus month",
    "t": "trend per year",
}
cal = cal[cal.term.isin(keep)].assign(effect=lambda d: d.term.map(keep))
cal["lo"] = 100 * (np.exp(cal.ci_low) - 1)
cal["hi"] = 100 * (np.exp(cal.ci_high) - 1)
fig = go.Figure()
for d in PREFIX:
    x = cal[(cal.dataset == d) & (cal.country == "ALL")]
    fig.add_trace(
        go.Scatter(
            x=x["effect %"],
            y=x.effect,
            mode="markers",
            name=d,
            error_x=dict(
                type="data",
                symmetric=False,
                array=x.hi - x["effect %"],
                arrayminus=x["effect %"] - x.lo,
            ),
        )
    )
fig.add_vline(x=0, line_dash="dot")
fig.update_layout(
    title="Calendar effects on daily volume, whole bank (%, 95 % CI)", height=420, yaxis_title=None
)
fig.show()
show(
    cal.pivot_table(index="effect", columns=["scope", "dataset"], values="effect %").round(1),
    paging=False,
)

# %% [markdown]
# ## 6 · Anomalies

# %%
show(read("anomalies").drop(columns="country").set_index(["scope", "dataset"]), paging=False)

# %% [markdown]
# ## 7 · Which modelling conclusions survive?

# %%
lrn = read("learnability")
fig = go.Figure()
for d in PREFIX:
    x = lrn[(lrn.dataset == d) & (lrn.country == "ALL") & np.isfinite(lrn.auc)]
    fig.add_trace(
        go.Scatter(
            x=x.auc,
            y=x.name,
            mode="markers",
            name=d,
            marker=dict(size=10),
            error_x=dict(
                type="data", symmetric=False, array=x.auc_hi - x.auc, arrayminus=x.auc - x.auc_lo
            ),
        )
    )
fig.add_vline(x=0.5, line_dash="dot")
fig.update_layout(
    title="Out-of-time test AUC per candidate target, whole bank (95 % CI)",
    height=420,
    yaxis_title=None,
    xaxis_range=[0.3, 1.0],
)
fig.show()
show(
    lrn.pivot_table(index="name", columns=["scope", "dataset"], values="verdict", aggfunc="first"),
    paging=False,
)
show(
    lrn.pivot_table(index="name", columns=["scope", "dataset"], values="auc").round(3),
    paging=False,
)
same = (
    lrn.pivot_table(index=["name", "scope"], columns="dataset", values="verdict", aggfunc="first")
    .dropna()
    .assign(same=lambda d: d.main == d.backup)
)
display(
    Markdown(
        f"**{int(same.same.sum())} of {len(same)} (target, scope) verdicts are the same on both datasets.** "
        "Those that differ: "
        + (
            "; ".join(
                f"{n} ({s}): {r.main} → {r.backup}" for (n, s), r in same[~same.same].iterrows()
            )
            or "none"
        )
        + "."
    )
)

# %% [markdown]
# ## 8 · Synthesis
# ### What the platform would have done with the backup as its source
# * **It would have accepted the missing twenty months without a word.** The backup's transactions stop on
#   25 September 2024; main's run to 17 May 2026. No contract check, data test or audit model notices: drift checks
#   judge the partitions that exist, and nothing states which partitions *should* exist. The audit gate does fail, but
#   through R01 (transactions dated before their product opened: 29 % against a 20 % maximum), a side effect of
#   the backup's transactions being concentrated in the first fifteen months, not a signal that data is missing.
# * **The circuit breaker would have held two whole tables, correctly.** `call_center_interactions.interaction_type`
#   is outside the contract vocabulary on most rows and `campaign_sends.was_clicked` is empty where the contract
#   requires it, every day. The holds are right, but their consequence is silent downstream: staging drops held
#   partitions, so the CX journey, the campaign mart and the escalation and conversion targets are simply empty.
# * **The two missing tables (`call_transcripts`, `satisfaction_surveys`) would have built empty models** with no
#   failure: no test asks a source table to have rows.
# * **Headers and types are main's**, so the structural checks pass; the only new typing findings are the two
#   content changes above.
#   New data-test failures are few and specific: 74 duplicate `document_number` values in customers (and, through
#   them, 74 duplicate knowledge-base document ids).
# * **The reconciliation control is the only one that says it plainly**: in either direction, no shared transaction,
#   product, complaint or contact record is identical, and only 2,239 of 4,025 shared customers are. It is the
#   cheapest fingerprint of a dataset's identity.
#
# ### What changes in the analysis, and what does not
# * **Behaviour per active month is the same.** Per month of coverage, about 0.82 transactions per customer in both;
#   a median ticket of 467 USD, a median income of about 2,295 USD, 45 % of transactions in the home currency and
#   20 % anonymous sessions in both. The backup's lower grid average (0.35) is the twenty empty months, not
#   customers who transact less.
# * **Rules move only where the data's structure moves**: R01 (+10 points, the early period), R23 (registration
#   branch unknown: 100 % in main, 50 % in the backup) and R24 (agent branch unknown: 69 % against 35 %), and the
#   rules on held or missing tables, which have no rate. Every other rule rate agrees within 0.2 points.
# * **Keys:** half of the backup's transactions lose a point-in-time key (34 % in main), for the same reason as R01.
# * **Calendar:** on the delivery day (`process_date`, ADR-014) the weekend effect is about the same (backup Saturday
#   −41 %, Sunday −42 %; main −39 %, −39 %), and holidays, month end and bonus months do nothing in either. Main's
#   pooled three-day payday dip (−1.3 %, p = 0.03) is not significant at 1 % and does not reappear in the backup
#   (+1.1 %, p = 0.22). No calendar effect beyond the weekend is confirmed in either dataset.
# * **Anomalies:** none in either: no abnormal day, no change point, the same low-side amount outliers (0.7 %), and
#   the forest and the AML rules agree 12–15× more than chance in both.
# * **Credit and fraud pipelines break on dates, not on data.** No customer is eligible for credit because the
#   eligibility window (the six months before 30 April 2026) holds no transaction; the fraud features' fixed split
#   dates leave the validation and test sets empty.
#
# ### Which modelling conclusions survive the change of source
# * **All of those that can be tested.** Dormancy is learnable in every scope of both datasets (AUC 0.72–0.73,
#   the six-month transaction count alone matching the model), honest fraud, complaints in 90 days and delinquency
#   show no evidence of signal in both, and the leaking `fraud_score` control reaches 0.78–0.85 in both. On the
#   backup, dormancy rests on two quarterly cutoffs only (the later ones would label every customer dormant because
#   the data stops; notebook 14 drops them).
# * **Campaign conversion and contact escalation cannot be tested on the backup**: their sources are held.
# * The conclusions are properties of the generator, and they are robust. What the swap exposes is the platform:
#   it would have served a bank that stopped in September 2024 as if it were current.
#
# ### Decisions, and what they mean for the next stages
# 1. **Add a completeness control**: an expected-partition calendar per fact table (every day from first landing to
#    `data_end`), severity A, so a source that stops early holds the run instead of passing it.
# 2. **Add row-count floors per source** (a table that lands empty fails), and make **window-based models fail when a
#    split or a window is empty** instead of training on nothing (fraud splits, credit eligibility, dormancy labels).
# 3. **Carry hold status to the marts and serving tables** (a `source_held` flag or a freshness date), so an empty CX
#    journey is read as "not delivered", not as "no contacts".
# 4. **Run the reconciliation fingerprint when any copy is restored**: a share of identical shared records far from
#    100 % means a different dataset, whatever its folder name says.
# 5. **Keep the backup quarantined.** It is a different and shorter dataset with the same generator; nothing in it
#    should be merged into main, and the analysis conclusions do not need it.
