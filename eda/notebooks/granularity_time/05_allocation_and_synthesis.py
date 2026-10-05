# %% [markdown]
# # 05 · Allocation and synthesis
# **Granularity series II · time and cells** · reads the tables written by notebooks 01 to 04
#
# **Stakeholders.** The chief marketing officer (next year's channel mix), finance (what a reallocation is worth and
# how sure we are), the data and ML platform (what to build), the governance office (what the numbers may claim).
#
# **The allocation question.** Notebook 04 showed that every tracked send pays back its cost: money is not the
# constraint, **customer attention is**. So a policy is evaluated at a **fixed number of sends** (the contacts actually
# made in the held-out year) and judged by the conversions it produces.
#
# **Method: off-policy replay on the held-out year.** Each policy chooses how many held-out sends each cell gets, using
# only fit-period information; each cell's **realised** held-out conversion rate then values the choice. Two guards:
# * **No extrapolation:** a cell may receive between 0 and 2 times the sends it actually received (a cell's audience and
#   consent are finite, and its rate is only observed near its actual volume).
# * **Intervals:** a parametric bootstrap redraws every cell's held-out conversions from Binomial(sends, realised rate);
#   policies are compared in pairs on the same draws.
#
# **What a replay cannot do.** It values *where* sends go assuming each cell's conversion rate would hold. It cannot say
# whether the send *caused* the conversion (uplift), because no customer was randomly withheld. Section 3 sizes the
# holdout that would.

# %%
import sys
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show
from scipy import stats
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize

from latam_eda import granularity as g
from latam_eda import theme

theme.register()
OUT = Path("../../reports/tables")
rng = np.random.default_rng(2026)
KEY = ["send_channel", "promoted_product", "campaign_objective", "segment", "country_code"]
allc = (
    pd.read_csv(OUT / "granularity_time_cells.csv")
    .sort_values(KEY, kind="stable")
    .reset_index(drop=True)
)
cells = allc[allc.tracked & (allc.sends_fit > 0) & (allc.sends_ho > 0)].reset_index(drop=True)
untracked = allc[~allc.tracked]
TOTAL = float(cells.sends_ho.sum())
display(
    Markdown(
        f"**Replay universe: {len(cells):,} tracked cells seen in both periods, {int(TOTAL):,} held-out sends** "
        f"({100 * TOTAL / allc[allc.tracked].sends_ho.sum():.0f} % of the tracked held-out sends). The untracked "
        f"channels ({', '.join(sorted(untracked.send_channel.unique()))}; {int(untracked.sends_ho.sum()):,} held-out "
        "sends) cannot be valued and keep their volume in every policy."
    )
)

# %% [markdown]
# ## 1 · Policies

# %%
CAP = 2.0
base = cells.sends_ho.to_numpy(dtype=float)
raw_rate = (cells.conversions_fit / cells.sends_fit).to_numpy()
chan_rate = (
    cells.groupby("send_channel")
    .apply(lambda d: d.conversions_fit.sum() / d.sends_fit.sum(), include_groups=False)
    .reindex(cells.send_channel)
    .to_numpy()
)


def greedy(score: np.ndarray) -> np.ndarray:
    """Fill cells in descending score order up to CAP × their actual sends until the fixed total is used."""
    order = np.lexsort((np.arange(len(score)), -score))  # stable: ties keep the cell order
    alloc, left = np.zeros(len(score)), TOTAL
    for i in order:
        a = min(CAP * base[i], left)
        alloc[i], left = a, left - a
    return alloc


POLICIES = {
    "actual mix": base,
    "greedy on raw cell rate": greedy(raw_rate),
    "greedy on channel rate": greedy(chan_rate),
    "greedy on EB cell rate": greedy(cells.rate_eb.to_numpy()),
    "proportional tilt to EB rate": base
    * cells.rate_eb.to_numpy()
    / np.average(cells.rate_eb, weights=base),
}
ix = cells.set_index(KEY)
rows = []
for name, w in POLICIES.items():
    v = g.policy_value(ix, pd.Series(w, index=ix.index), TOTAL)
    rows.append({"policy": name, **v})
placebo = []
for _ in range(200):
    v = g.policy_value(ix, pd.Series(greedy(rng.random(len(cells))), index=ix.index), TOTAL)
    placebo.append(v["conversions"])
pol = pd.DataFrame(rows)
act = pol.set_index("policy").loc["actual mix"]
pol["conversions vs actual %"] = 100 * (pol.conversions / act.conversions - 1)
pol["cost vs actual %"] = 100 * (pol.cost / act.cost - 1)

# paired parametric bootstrap of the realised held-out outcomes
B = 1000
n_ho = cells.sends_ho.to_numpy().astype(int)
draw = (
    rng.binomial(n_ho[None, :], cells.rate_ho.to_numpy()[None, :], size=(B, len(cells)))
    / n_ho[None, :]
)
W = {k: (v / v.sum() * TOTAL) for k, v in POLICIES.items()}
conv_b = {k: draw @ w for k, w in W.items()}
for k in POLICIES:
    d = conv_b[k] - conv_b["actual mix"]
    i = pol.policy == k
    pol.loc[i, "gain 2.5 %"], pol.loc[i, "gain 97.5 %"] = np.quantile(d, [0.025, 0.975])
    pol.loc[i, "p (gain ≤ 0)"] = (d <= 0).mean() if k != "actual mix" else np.nan
pol["sends to SMS %"] = [
    100 * W[k][cells.send_channel.to_numpy() == "SMS"].sum() / TOTAL for k in pol.policy
]
show(pol.round(3), paging=False)
fig = px.bar(
    pol,
    x="policy",
    y="conversions vs actual %",
    error_y=100 * (pol["gain 97.5 %"] / act.conversions) - pol["conversions vs actual %"],
    error_y_minus=pol["conversions vs actual %"] - 100 * (pol["gain 2.5 %"] / act.conversions),
    title="Held-out conversions at a fixed number of sends, against the actual mix (95 % bootstrap intervals)",
)
fig.add_hline(
    y=100 * (np.mean(placebo) / act.conversions - 1),
    line_dash="dot",
    annotation_text="random reallocation (mean of 200)",
)
fig.update_layout(height=380)
fig.show()
pol_out = pol.assign(cap=CAP, total_sends=TOTAL, placebo_mean_conversions=np.mean(placebo))
pol_out.to_csv(OUT / "granularity_time_allocation.csv", index=False)
best = pol.loc[pol.conversions.idxmax()]
rawp = pol.set_index("policy").loc["greedy on raw cell rate"]
ebp = pol.set_index("policy").loc["greedy on EB cell rate"]
display(
    Markdown(
        f"**The best policy, {best.policy}, converts {best['conversions vs actual %']:+.1f} % more at the same number of "
        f"sends (95 % interval {100 * best['gain 2.5 %'] / act.conversions:+.1f} to "
        f"{100 * best['gain 97.5 %'] / act.conversions:+.1f} %), moving the SMS share from "
        f"{pol['sends to SMS %'].iloc[0]:.0f} % to {best['sends to SMS %']:.0f} % of sends and raising send cost "
        f"{best['cost vs actual %']:+.0f} %.** "
        f"A random reallocation under the same cap gains {100 * (np.mean(placebo) / act.conversions - 1):+.1f} % on "
        f"average, so the gain is the channel signal, not the reshuffling. Choosing cells by their **raw** rate gains "
        f"{rawp['conversions vs actual %']:+.1f} % against {ebp['conversions vs actual %']:+.1f} % for the "
        "shrunk rate: the raw ranking partly selects cells that were lucky in the fit period (the winner's curse), "
        "which shrinkage removes. "
        f"Over the held-out year the reallocation is worth {best.conversions - act.conversions:,.0f} more conversions "
        f"(gross attributed value {best.value - act.value:,.0f} USD, not a margin, see notebook 04)."
    )
)

# %% [markdown]
# ## 2 · The untracked channels
# Voice and WhatsApp cost money and cannot report a conversion. The replay keeps them as they are; the decision they
# need is an experiment, not an allocation.

# %%
ut = untracked.groupby("send_channel")[["sends_fit", "cost_fit", "sends_ho", "send_cost_ho"]].sum()
ut["held-out cost per send"] = ut.send_cost_ho / ut.sends_ho
ut["share of held-out sends %"] = 100 * ut.sends_ho / allc.sends_ho.sum()
show(ut.round(4), paging=False)
cov = 100 * allc[allc.tracked].sends_ho.sum() / allc.sends_ho.sum()
display(
    Markdown(
        f"**Attribution coverage is {cov:.0f} % of held-out sends**: {100 - cov:.0f} % of contacts "
        f"({ut.send_cost_ho.sum():,.0f} USD of held-out cost) go to channels whose effect is unmeasured. Stopping them on "
        "the evidence of a zero that cannot be anything else would be a decision on a measurement artefact."
    )
)

# %% [markdown]
# ## 3 · From correlation to cause: the holdout that would settle it
# A randomised holdout withholds the send from a random share of the targeted customers; the difference in conversion
# between sent and withheld is the **uplift** caused by the send. The table gives the customers needed **per arm** to
# detect a relative uplift over the baseline conversion (two-sided α = 5 %, power 80 %), and how many months of the
# bank's current campaign volume that takes at a 10 % and a 50 % holdout.

# %%
p0 = float(cells.conversions_ho.sum() / cells.sends_ho.sum())
months_ho = 12
vol = allc.sends_ho.sum() / months_ho  # all channels, sends a month
rows = []
for rel in [0.10, 0.25, 0.50]:
    n = NormalIndPower().solve_power(
        proportion_effectsize(p0 * (1 + rel), p0), alpha=0.05, power=0.8, ratio=1.0
    )
    rows.append(
        {
            "baseline conversion %": 100 * p0,
            "relative uplift to detect %": 100 * rel,
            "customers per arm": int(np.ceil(n)),
            "months at a 10 % holdout": n / (0.1 * vol),
            "months at a 50 % holdout": n / (0.5 * vol),
        }
    )
power = pd.DataFrame(rows)
show(power.round(1), paging=False)
display(
    Markdown(
        f"**Detecting a 25 % uplift on a {100 * p0:.2f} % baseline needs {power['customers per arm'].iloc[1]:,} "
        f"customers per arm**: {power['months at a 10 % holdout'].iloc[1]:.0f} months of the bank's whole campaign "
        f"volume at a 10 % holdout, {power['months at a 50 % holdout'].iloc[1]:.0f} at 50 %. At this volume only large "
        "uplifts are measurable within a year, so the test should pool channels and campaigns and target the "
        "decision that matters (does the contact cause conversions at all), not fine differences between cells. "
        "For Voice and WhatsApp the holdout must come with instrumentation (a tracked link or code per send), "
        "otherwise both arms report zero."
    )
)

# %% [markdown]
# ## 4 · Which findings of this series are signal?
# Every test of series II, corrected together with Benjamini–Hochberg at a 5 % false discovery rate.

# %%
sig = []
rec = pd.read_csv(OUT / "granularity_time_reconciliation.csv")
for _, r in rec[rec.clock.str.startswith("business")].iterrows():
    sig += [
        ("01 clock", f"{r['market']} holiday effect (business clock)", r["holiday p"]),
        ("01 clock", f"{r['market']} payday effect (business clock)", r["payday p"]),
    ]
dsp = pd.read_csv(OUT / "granularity_time_hour_dispersion.csv")
sig += [
    ("02 hour", f"{r.market} {r.measure}: hours vary beyond the day", r.p_value)
    for r in dsp.itertuples()
]
sq = pd.read_csv(OUT / "granularity_time_sequences.csv")
sig += [
    ("03 sequence", f"{r['sequence']} within {r['window (h)']} h", r["p_value"])
    for _, r in sq.iterrows()
    if not np.isnan(r["p_value"])
]
t_ = allc[allc.tracked & (allc.opened_fit > 0)]
for attr in ["send_channel", "promoted_product", "campaign_objective", "segment", "country_code"]:
    d = t_.groupby(attr)[["opened_fit", "conversions_fit"]].sum()
    p = stats.chi2_contingency(
        np.column_stack([d.conversions_fit, d.opened_fit - d.conversions_fit])
    ).pvalue
    sig.append(("04 cell", f"conversion after an open differs by {attr}", p))
d = t_.groupby("send_channel")[["open_tracked_fit", "opened_fit"]].sum()
sig.append(
    (
        "04 cell",
        "open rate differs by channel",
        stats.chi2_contingency(
            np.column_stack([d.opened_fit, d.open_tracked_fit - d.opened_fit])
        ).pvalue,
    )
)
for _, r in pol[pol.policy != "actual mix"].iterrows():
    sig.append(
        ("05 allocation", f"{r['policy']} beats the actual mix", max(r["p (gain ≤ 0)"], 1 / B))
    )
sig = pd.DataFrame(sig, columns=["notebook", "test", "p_value"])
sig["reject"], sig["q_value"] = g.bh_fdr(sig.p_value.to_numpy())
sig = sig.sort_values(
    ["reject", "q_value", "notebook", "test"], ascending=[False, True, True, True], kind="stable"
)
sig.to_csv(OUT / "granularity_time_signal.csv", index=False)
show(sig.round(6), paging=False)
surv = sig[sig.reject]
display(
    Markdown(
        f"**{len(surv)} of {len(sig)} tests survive the false-discovery correction:** "
        + "; ".join(f"{r.test} ({r.notebook})" for r in surv.itertuples())
        + ". Everything else in the series (holidays, paydays, intraday structure, sequences, product or segment "
        "effects after the open) is noise at this data's resolution."
    )
)

# %% [markdown]
# ## 5 · Synthesis
# ### What re-graining in time and by decision cell found
# | theme | finding | evidence |
# |---|---|---|
# | the clock | every process was generated on its delivery day: transactions, digital events and sends at UTC−6, contacts and complaints at UTC−8, the same for every market | notebook 01: 100 % of rows land on `process_date` after the shift; hour × weekday χ²/dof ≈ 1 |
# | the clock | the country series' weaker Colombian and Argentine weekends and the Argentine "Monday dip" were artefacts of legal local time | notebook 01 reconciliation: −39 % weekends everywhere on the business clock |
# | the clock | integrity rules R15 and R16 test the wrong offset for contacts and complaints (−6 h instead of −8 h) | notebook 01: their ~8 % violations are 2 of 24 hours |
# | the hour | no intraday profile, no information beyond the day, no sub-day sequences, no bursts, no velocity signal | notebooks 02 and 03 |
# | the hour | hourly monitors need negative-binomial limits (the day's level varies ~11 % beyond Poisson) | notebook 02 |
# | the cell | conversions are only attributable after an open; Voice and WhatsApp are unmeasured, not failing | notebook 04 |
# | the cell | the conversion value is a flat ~2,550 USD whatever the product: not a margin | notebook 04 |
# | the cell | cells do not differ within a channel; the channel mix is the lever | notebooks 04 and 05 |
#
# ### KPIs for these scenarios
# | KPI | definition | grain | owner |
# |---|---|---|---|
# | delivery-day conformance | share of rows whose timestamp + declared process offset equals `process_date` | process × day | data platform |
# | clock drift | best shift of the hour × weekday scan, per process and month (alert when it moves) | process × month | data platform |
# | hourly alert rate | share of hours outside negative-binomial limits (target ≈ 0.1 %) | market × process × hour | operations |
# | attribution coverage | share of sends from channels that can attribute a conversion | channel × month | marketing analytics |
# | conversions per 1,000 sends | empirical-Bayes rate per cell and channel | cell × month | marketing |
# | expected value per send | EB rate × value per conversion − cost per send (with margin once finance supplies it) | cell × month | marketing, finance |
# | holdout share and measured uplift | share of targeted customers withheld; sent minus withheld conversion | campaign × month | marketing analytics |
#
# ### Opportunities, ranked
# 1. **Instrument Voice and WhatsApp, then test them** with a holdout: about a fifth of contacts and most of the
#    measurable risk sit there (section 2).
# 2. **Shift the channel mix towards the channels that convert per contact** under a contact budget (section 1): a
#    measured, reversible change with its interval stated; run it as a holdout-backed pilot, not a big-bang move.
# 3. **Fix the clock in the platform** (ADR-014): `enrich_transactions` local-time columns, R15 and R16.
# 4. **Stream hourly monitors** with negative-binomial limits instead of storing an hourly fact.
#
# ### Downstream implications
# | layer | change | why |
# |---|---|---|
# | source contract | every timestamp declares its clock; every channel declares its attribution method | notebooks 01 and 04 |
# | silver / integrity | R15 and R16 use the −8 h contact window | notebook 01 |
# | platform macro | `enrich_transactions` derives local time and weekend from the declared business clock | notebook 01 |
# | gold | promote `fct_campaign_cell` (with `open_tracked`) as the campaign planning aggregate; do **not** promote `fct_country_hour` | notebooks 02 and 04 |
# | streaming | hourly counts per market and process with negative-binomial limits and a day-parity test | notebook 02 |
# | ML | a monthly batch table of EB cell rates and expected value per send; no hourly or sequence models | notebooks 03 and 04 |
# | agents | a campaign-planning agent may read the cell table and propose a mix within caps, always showing intervals and the uplift caveat; no intraday triggers for the service agent | notebooks 03 and 05 |
#
# ### Recommendation
# Promote the **clock** fixes (P0: ADR-014, R15/R16, the platform macro) and the **campaign cell** aggregate with its
# EB rates. Keep the hour in the streaming layer only. Treat the channel-mix gain as a pilot hypothesis to confirm
# with a randomised holdout before it becomes a standing policy.
