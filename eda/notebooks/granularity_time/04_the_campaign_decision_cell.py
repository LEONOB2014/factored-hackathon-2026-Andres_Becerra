# %% [markdown]
# # 04 · The campaign decision cell
# **Granularity series II · time and cells** · grain: one send channel, promoted product, campaign objective, customer
# segment, market and delivery month (`agg.fct_campaign_cell`)
#
# **Stakeholders.** The chief marketing officer and campaign managers (where the next month's sends go), finance (what
# the campaign budget returns), the data-governance office (what the conversion figure actually measures).
#
# **Why this grain.** The first granularity series found the only decision-relevant signal of the whole star at the
# campaign grain: campaigns differ, launch attributes rank them. But marketing does not allocate budget to past
# campaigns; it allocates the next month's sends to **cells**: which channel, promoting what, for which objective, to
# which segment, in which market. A cell recurs month after month, so its past can predict its future.
#
# **The questions.**
# 1. **What does a conversion measure?** The funnel (delivered → opened → clicked → converted) per channel, and whether
#    every channel can attribute a conversion at all.
# 2. **Do cells differ beyond their channel?** Homogeneity tests at each funnel stage.
# 3. **How well does a cell's past predict its future?** Out-of-time: the earlier two-thirds of months fit, the last
#    third is scored. Candidates: the global rate, the channel rate, the cell's raw rate, and **empirical-Bayes
#    beta-binomial shrinkage** (each cell's rate pulled towards a prior fitted on all cells, by an amount that depends
#    on how many sends the cell has). Proper scoring rules: log loss and Brier per send, a calibration curve, and a
#    rank correlation (what an allocation needs).
# 4. **What is each cell worth?** Return on send cost per cell with a posterior distribution, not a point estimate.

# %%
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show
from scipy import stats

from latam_eda import country, theme
from latam_eda import granularity as g

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
rng = np.random.default_rng(14)
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, g.SQL_DIR_TIME)
star.build(["fct_campaign_cell"], verbose=False)
checks = star.check(["fct_campaign_cell"])
show(checks, paging=False)
KEY = ["send_channel", "promoted_product", "campaign_objective", "segment", "country_code"]
cm = star.q("select * from {fct_campaign_cell} order by all")
months = sorted(cm.month_start.unique())
n_fit = round(2 * len(months) / 3)
FIT_END = months[n_fit - 1]
cm["period"] = np.where(cm.month_start <= FIT_END, "fit", "held_out")
display(
    Markdown(
        f"**{int(checks.ok.sum())} of {len(checks)} checks pass.** {cm.groupby(KEY).ngroups:,} cells over "
        f"{len(months)} delivery months ({pd.Timestamp(months[0]):%Y-%m} to {pd.Timestamp(months[-1]):%Y-%m}), "
        f"{int(cm.sends.sum()):,} sends. The first {n_fit} months (to {pd.Timestamp(FIT_END):%Y-%m}) fit, the last "
        f"{len(months) - n_fit} are held out."
    )
)

# %% [markdown]
# ## 1 · What does a conversion measure?

# %%
ch = cm.groupby("send_channel")[
    [
        "sends",
        "delivered",
        "open_tracked",
        "opened",
        "clicked",
        "conversions",
        "conversion_value",
        "send_cost",
    ]
].sum()
ch["delivery %"] = 100 * ch.delivered / ch.sends
ch["open tracking %"] = 100 * ch.open_tracked / ch.delivered
ch["open % of tracked"] = 100 * ch.opened / ch.open_tracked.replace(0, np.nan)
ch["conversion % of sends"] = 100 * ch.conversions / ch.sends
ch["conversion % of opens"] = 100 * ch.conversions / ch.opened.replace(0, np.nan)
ch["conversion % of clicks"] = 100 * ch.conversions / ch.clicked.replace(0, np.nan)
ch["cost per send"] = ch.send_cost / ch.sends
ch["value per conversion"] = ch.conversion_value / ch.conversions.replace(0, np.nan)
show(ch.round(4), paging=False)
tr = ch[ch.opened > 0]
untracked = ch[ch.open_tracked == 0]
chi_open = stats.chi2_contingency(np.column_stack([tr.conversions, tr.opened - tr.conversions]))
chi_click = stats.chi2_contingency(np.column_stack([tr.conversions, tr.clicked - tr.conversions]))
conv_wo_open = int(cm.conversions.sum() - cm[cm.send_channel.isin(tr.index)].conversions.sum())
display(
    Markdown(
        f"**A conversion is only ever recorded after an open: {conv_wo_open} conversions come from channels without "
        f"open tracking.** {', '.join(untracked.index)} record no opens at all ({int(untracked.sends.sum()):,} sends, "
        f"{untracked.send_cost.sum():,.0f} USD), so they cannot record a conversion: their zero is a **measurement "
        'gap, not a measured failure**. The first granularity series read it as "Voice and WhatsApp never convert" and '
        "pointed at stopping them; the right decision is to instrument them first (tracked links, promo codes, or a "
        "randomised holdout). "
        f"Among the tracked channels, conversion given an open is {tr.conversions.sum() / tr.opened.sum():.2%} and "
        f"given a click {tr.conversions.sum() / tr.clicked.sum():.1%}, "
        + (
            "the same in every channel "
            if chi_open.pvalue > 0.01 and chi_click.pvalue > 0.01
            else "different between channels "
        )
        + f"(χ² p = {chi_open.pvalue:.2g} and {chi_click.pvalue:.2g}). The channels differ in **how often a send is "
        "opened** and **what a send costs**, not in what happens after the open."
    )
)

# %% [markdown]
# ## 2 · Do cells differ beyond their channel?
# Within each tracked channel, a chi-square of homogeneity across cells at each funnel stage (fit period): opens out
# of delivered, conversions out of opens. A stage where cells do not differ beyond binomial noise is a stage where
# the cell's identity carries no information, and its best prediction is the channel mean.

# %%
fit = (
    cm[cm.period == "fit"]
    .groupby(KEY)[
        [
            "sends",
            "delivered",
            "open_tracked",
            "opened",
            "clicked",
            "conversions",
            "conversion_value",
            "send_cost",
        ]
    ]
    .sum()
)
ho = (
    cm[cm.period == "held_out"]
    .groupby(KEY)[["sends", "opened", "conversions", "conversion_value", "send_cost"]]
    .sum()
)
rows = []
for c_, d in fit[fit.open_tracked > 0].groupby(level="send_channel"):
    d = d[d.open_tracked > 0]
    for stage, s, n in [
        ("open | delivered", d.opened, d.open_tracked),
        ("conversion | open", d.conversions, d.opened),
        ("conversion | send", d.conversions, d.sends),
    ]:
        k = n > 0
        x = np.column_stack([s[k], n[k] - s[k]])
        x = x[x.sum(axis=1) > 0]
        r_ = stats.chi2_contingency(x)
        rows.append(
            {
                "channel": c_,
                "stage": stage,
                "cells": len(x),
                "chi2": r_.statistic,
                "dof": r_.dof,
                "chi2 / dof": r_.statistic / r_.dof,
                "p_value": r_.pvalue,
            }
        )
het = pd.DataFrame(rows)
for attr in ["promoted_product", "campaign_objective", "segment", "country_code"]:
    d = fit[fit.opened > 0].groupby(level=attr)[["opened", "conversions"]].sum()
    r_ = stats.chi2_contingency(np.column_stack([d.conversions, d.opened - d.conversions]))
    rows.append(
        {
            "channel": "all tracked",
            "stage": f"conversion | open, by {attr}",
            "cells": len(d),
            "chi2": r_.statistic,
            "dof": r_.dof,
            "chi2 / dof": r_.statistic / r_.dof,
            "p_value": r_.pvalue,
        }
    )
het = pd.DataFrame(rows)
show(het.round(4), paging=False)
open_het = het[het.stage == "open | delivered"]
conv_het = het[het.stage.str.startswith("conversion | open")]
display(
    Markdown(
        f"**Opens: cells differ within {int((open_het.p_value < 0.01).sum())} of {len(open_het)} channels; conversion "
        f"after an open: {int((conv_het.p_value < 0.01).sum())} of {len(conv_het)} tests reject homogeneity "
        "(p < 0.01).** "
        + (
            (
                "Within a channel, product, objective, segment and market change neither how often a send is opened "
                "nor what happens after the open: **the decision cell collapses to its channel** on this data."
                if (open_het.p_value > 0.01).all()
                else "Product, objective, segment and market do not change what happens after the open; what "
                "separates cells inside a channel is their open rate, in the channels where the test rejects."
            )
            if (conv_het.p_value > 0.01).all()
            else "Some attributes move conversion after the open; the cell carries information beyond its channel."
        )
    )
)

# %% [markdown]
# ## 3 · How well does a cell's past predict its future?
# Each candidate predicts a cell's held-out conversion rate per send from fit-period data only. Scored on the cells of
# the tracked channels seen in both periods, weighted by held-out sends.
#
# **Empirical Bayes.** The cells' true rates are assumed to come from a Beta(α, β) prior; α and β are the
# maximum-likelihood fit of the beta-binomial to the fit-period cells. A cell with s conversions out of n sends then has
# posterior mean (s + α) / (n + α + β). The prior's concentration α + β is the number of "pseudo-sends" of evidence the
# prior is worth: a cell with far fewer sends than that keeps mostly the prior; one with far more keeps its own rate.
# The **channel-anchored** variant keeps that concentration but centres each cell's prior on its channel's rate.

# %%
cells = fit.join(ho, rsuffix="_ho", how="inner").reset_index()
cells = cells[cells.send_channel.isin(tr.index) & (cells.sends_ho > 0)].reset_index(drop=True)
alpha, beta_ = g.beta_binomial_fit(cells.conversions, cells.sends)
kappa = alpha + beta_
glob = cells.conversions.sum() / cells.sends.sum()
chan_rate = cells.groupby("send_channel").apply(
    lambda d: d.conversions.sum() / d.sends.sum(), include_groups=False
)
cr = cells.send_channel.map(chan_rate)
EPS = 1e-5
pred = pd.DataFrame(
    {
        "global rate": glob,
        "channel rate": cr,
        "raw cell rate": cells.conversions / cells.sends,
        "EB, global prior": (cells.conversions + alpha) / (cells.sends + kappa),
        "EB, channel-anchored prior": (cells.conversions + kappa * cr) / (cells.sends + kappa),
    }
).clip(EPS, 1 - EPS)
y_c, y_n = cells.conversions_ho.to_numpy(), cells.sends_ho.to_numpy()
y_r = y_c / y_n


def scores(p: np.ndarray, idx: np.ndarray | None = None) -> tuple[float, float]:
    """Log loss and Brier per held-out send of a predicted rate per cell."""
    i = slice(None) if idx is None else idx
    p, c, n = p[i], y_c[i], y_n[i]
    ll = -(c * np.log(p) + (n - c) * np.log(1 - p)).sum() / n.sum()
    br = (c * (1 - p) ** 2 + (n - c) * p**2).sum() / n.sum()
    return ll, br


rows = []
ll0 = scores(pred["global rate"].to_numpy())[0]
for name in pred:
    ll, br = scores(pred[name].to_numpy())
    rho = stats.spearmanr(pred[name], y_r).statistic
    rows.append(
        {
            "predictor": name,
            "log loss per send": ll,
            "Brier per send": br,
            "skill vs global (1 − LL / LL_global)": 1 - ll / ll0,
            "Spearman with held-out rate": rho,
        }
    )
score = pd.DataFrame(rows)
B = 500
boot = {k: [] for k in ["EB channel − raw", "EB channel − channel", "EB channel − EB global"]}
P = {k: v.to_numpy() for k, v in pred.items()}
for _ in range(B):
    i = rng.integers(0, len(cells), len(cells))
    s_ = {k: scores(v, i)[0] for k, v in P.items()}
    boot["EB channel − raw"].append(s_["EB, channel-anchored prior"] - s_["raw cell rate"])
    boot["EB channel − channel"].append(s_["EB, channel-anchored prior"] - s_["channel rate"])
    boot["EB channel − EB global"].append(s_["EB, channel-anchored prior"] - s_["EB, global prior"])
ci = {k: np.quantile(v, [0.025, 0.975]) for k, v in boot.items()}
show(score.round(6), paging=False)
show(
    pd.DataFrame(
        [{"log-loss difference": k, "2.5 %": v[0], "97.5 %": v[1]} for k, v in ci.items()]
    ).round(7),
    paging=False,
)
cal = pd.DataFrame({"p": P["EB, channel-anchored prior"], "c": y_c, "n": y_n})
cal["bin"] = pd.qcut(cal.p.rank(method="first"), 10, labels=False)
cal = cal.groupby("bin").apply(
    lambda d: pd.Series(
        {
            "predicted %": 100 * np.average(d.p, weights=d.n),
            "observed %": 100 * d.c.sum() / d.n.sum(),
        }
    ),
    include_groups=False,
)
fig = px.scatter(
    cal,
    x="predicted %",
    y="observed %",
    title="Calibration of the channel-anchored EB rate (held-out deciles)",
)
mx = float(cal.max().max()) * 1.05
fig.add_shape(type="line", x0=0, y0=0, x1=mx, y1=mx, line={"dash": "dot"})
fig.update_layout(height=340)
fig.show()
best = score.loc[score["log loss per send"].idxmin(), "predictor"]
typ = cells.sends.median()
display(
    Markdown(
        f"**{len(cells):,} cells of the tracked channels are scored. The fitted prior is Beta({alpha:.2f}, {beta_:.0f}): "
        f"mean {alpha / kappa:.3%}, concentration {kappa:,.0f} pseudo-sends, against a median cell of {typ:,.0f} "
        f"fit-period sends.** The best predictor by log loss is **{best}**. "
        f"The channel-anchored shrinkage beats the raw cell rate by {-np.mean(boot['EB channel − raw']):.2e} nats per send "
        f"(95 % interval {-ci['EB channel − raw'][1]:.2e} to {-ci['EB channel − raw'][0]:.2e}) and "
        + (
            "is indistinguishable from the plain channel rate"
            if ci["EB channel − channel"][0] < 0 < ci["EB channel − channel"][1]
            else (
                "beats the plain channel rate"
                if ci["EB channel − channel"][1] < 0
                else "is worse than the plain channel rate"
            )
        )
        + f" (interval {ci['EB channel − channel'][0]:.2e} to {ci['EB channel − channel'][1]:.2e}). "
        "Shrinkage is the safe default whatever the data: it never pays to trust a small cell's raw rate, and it costs "
        "nothing when cells really differ. Here it tells the business the cell adds "
        + (
            "little beyond the channel: a month of a cell's history does not out-predict knowing its channel."
            if ci["EB channel − channel"][1] > 0
            else "real information beyond the channel, which the shrunk estimate captures without overfitting."
        )
    )
)

# %% [markdown]
# ## 4 · What is a send worth?
# A cell's expected value per send is EV = rate × value per conversion − cost per send, and its return on send cost is
# ROI = EV / cost per send. The rate comes from its posterior Beta(s + κ·m_channel, n − s + κ·(1 − m_channel)) (2,000
# draws). The value per conversion is the cell's mean shrunk towards its product's mean with 5 pseudo-conversions. The
# cost per send is measured exactly. Only the rate's uncertainty is propagated. P(ROI > 0) is the probability the cell
# pays back its send cost; the **break-even margin** is the share of the conversion value the bank must keep for a send
# to pay (cost per send / (rate × value per conversion)). All of it is correlation, not uplift (notebook 05).

# %%
# every cell of either period: a cell new in the held-out year has no fit-period sends and gets its channel's prior
allc = fit.reset_index()
allc = allc.merge(ho.reset_index(), on=KEY, how="outer", suffixes=("", "_ho")).fillna(
    {
        **dict.fromkeys(fit.columns, 0),
        "sends_ho": 0,
        "opened_ho": 0,
        "conversions_ho": 0,
        "conversion_value_ho": 0,
        "send_cost_ho": 0,
    }
)
allc["tracked"] = allc.send_channel.isin(tr.index)
m_ch = allc.send_channel.map(chan_rate).fillna(0)
prod = allc[allc.tracked].groupby("promoted_product")[["conversion_value", "conversions"]].sum()
prod_vpc = (prod.conversion_value / prod.conversions).reindex(allc.promoted_product).to_numpy()
K_V = 5
allc["value_per_conv"] = (allc.conversion_value + K_V * np.nan_to_num(prod_vpc)) / (
    allc.conversions + K_V
)
allc["cost_per_send"] = (allc.send_cost / allc.sends.replace(0, np.nan)).fillna(
    allc.send_cost_ho / allc.sends_ho
)
allc["rate_eb"] = (allc.conversions + kappa * m_ch) / (allc.sends + kappa)
a_post = (allc.conversions + kappa * m_ch).to_numpy()
b_post = (allc.sends - allc.conversions + kappa * (1 - m_ch)).to_numpy()
draws = rng.beta(np.maximum(a_post, 1e-9)[:, None], b_post[:, None], size=(len(allc), 2000))
roi = (
    draws * allc.value_per_conv.to_numpy()[:, None] - allc.cost_per_send.to_numpy()[:, None]
) / allc.cost_per_send.to_numpy()[:, None]
allc["roi_median"] = np.median(roi, axis=1)
allc["roi_p05"], allc["roi_p95"] = np.quantile(roi, [0.05, 0.95], axis=1)
allc["p_roi_pos"] = (roi > 0).mean(axis=1)
allc["break_even_rate"] = allc.cost_per_send / allc.value_per_conv
ev = draws * allc.value_per_conv.to_numpy()[:, None] - allc.cost_per_send.to_numpy()[:, None]
allc["ev_per_send"] = ev.mean(axis=1)
allc["ev_p05"], allc["ev_p95"] = np.quantile(ev, [0.05, 0.95], axis=1)
allc["break_even_margin"] = allc.cost_per_send / (allc.rate_eb * allc.value_per_conv)
for c_ in [
    "rate_eb",
    "roi_median",
    "roi_p05",
    "roi_p95",
    "p_roi_pos",
    "ev_per_send",
    "ev_p05",
    "ev_p95",
    "break_even_margin",
]:
    allc.loc[~allc.tracked, c_] = np.nan  # not measurable: no attribution
allc["rate_ho"] = allc.conversions_ho / allc.sends_ho.replace(0, np.nan)
allc["value_per_conv_ho"] = (
    allc.conversion_value_ho / allc.conversions_ho.replace(0, np.nan)
).fillna(allc.value_per_conv)
allc["cost_per_send_ho"] = (allc.send_cost_ho / allc.sends_ho.replace(0, np.nan)).fillna(
    allc.cost_per_send
)
allc = allc.rename(
    columns={
        "sends": "sends_fit",
        "delivered": "delivered_fit",
        "open_tracked": "open_tracked_fit",
        "opened": "opened_fit",
        "clicked": "clicked_fit",
        "conversions": "conversions_fit",
        "conversion_value": "value_fit",
        "send_cost": "cost_fit",
    }
).sort_values(KEY)
allc.to_csv(OUT / "granularity_time_cells.csv", index=False)
pv = (
    allc[allc.tracked]
    .groupby("promoted_product")[["conversions_fit", "value_fit"]]
    .sum()
    .assign(value_per_conversion=lambda d: d.value_fit / d.conversions_fit)
)
show(pv.round(1), paging=False)
show(
    allc[allc.tracked]
    .sort_values("ev_per_send", ascending=False)[
        KEY
        + [
            "sends_fit",
            "rate_eb",
            "value_per_conv",
            "cost_per_send",
            "ev_per_send",
            "ev_p05",
            "ev_p95",
            "p_roi_pos",
            "break_even_margin",
        ]
    ]
    .round(5),
    paging=True,
)
fig = px.box(
    allc[allc.tracked],
    x="send_channel",
    y="ev_per_send",
    points="all",
    title="Expected conversion value per send by cell, tracked channels (USD, fit period, EB rate)",
)
fig.update_layout(height=340)
fig.show()
t_ = allc[allc.tracked]
win = t_[t_.p_roi_pos > 0.9]
by_ch = t_.groupby("send_channel").apply(
    lambda d: pd.Series(
        {
            "EV per send": np.average(d.ev_per_send, weights=d.sends_fit),
            "cost per send": d.cost_fit.sum() / d.sends_fit.sum(),
            "break-even margin %": 100 * np.average(d.break_even_margin, weights=d.sends_fit),
        }
    ),
    include_groups=False,
)
show(by_ch.round(5), paging=False)
u_ = allc[~allc.tracked].groupby("send_channel")[["sends_fit", "cost_fit"]].sum()
u_["break-even conversion %"] = 100 * allc[~allc.tracked].groupby("send_channel").apply(
    lambda d: (
        d.cost_fit.sum() / d.sends_fit.sum() / np.average(d.value_per_conv, weights=d.sends_fit)
    ),
    include_groups=False,
)
tracked_pct = 100 * tr.conversions.sum() / tr.sends.sum()
u_["tracked channels' conversion % of sends"] = tracked_pct
show(u_.round(4), paging=False)
cover = ho.reset_index().merge(fit.reset_index()[KEY], on=KEY, how="left", indicator=True)
cover = cover[cover.send_channel.isin(tr.index)]
cov = cover[cover._merge == "both"].sends.sum() / cover.sends.sum()
best_ch, worst_ch = by_ch["EV per send"].idxmax(), by_ch["EV per send"].idxmin()
display(
    Markdown(
        f"**{len(win):,} of {len(t_):,} tracked cells pay back their send cost with probability above 0.9.** A "
        f"conversion is worth {pv.value_per_conversion.min():,.0f}–{pv.value_per_conversion.max():,.0f} USD whatever "
        f"the product (a mortgage and a savings account alike), while a send costs {by_ch['cost per send'].min():.4f}–"
        f"{by_ch['cost per send'].max():.3f} USD: the bank would break even keeping "
        f"{by_ch['break-even margin %'].min():.3f}–{by_ch['break-even margin %'].max():.2f} % of the conversion value. "
        "Two consequences. **The conversion value is not a margin** (it does not depend on the product, so it is a "
        "generic attributed value, and ROI on it overstates the return by orders of magnitude); finance must supply the "
        "product margin before any ROI is reported. **Money is not the constraint; customer attention is**: every send "
        "pays, so the decision is where a fixed number of contacts produces the most conversions. "
        f"{best_ch} yields {by_ch['EV per send'].max():.1f} USD of expected value per send against "
        f"{by_ch['EV per send'].min():.1f} for {worst_ch}, and since cells do not differ within a channel (section 2) "
        "the allocation is a channel-mix decision. "
        f"The untracked channels would pay back at {', '.join(f'{v:.3f} % ({k})' for k, v in u_['break-even conversion %'].items())} "
        f"conversion per send, against {tracked_pct:.3f} % in the tracked channels; whether they reach it is unknown "
        f"until they are instrumented. {100 * cov:.0f} % of the held-out tracked sends fall in cells already seen in the "
        "fit period, so a cell-level policy covers most of next year's volume."
    )
)

# %% [markdown]
# ## Findings and what they mean downstream
# * **The conversion metric is defined by open tracking.** Channels without opens cannot attribute a conversion. Every
#   campaign KPI, mart (`mart_campaign_compliance_uplift`) and model that reads `had_conversion` inherits this blind
#   spot, so the source contract must say how each channel attributes conversions, and the gold layer should carry an
#   `attribution_method` per send. The first granularity series' "stop Voice and WhatsApp" is withdrawn: instrument first.
# * **The conversion value is not a margin**, and with it every send pays. Campaign ROI needs the product margin from
#   finance; until then the KPI is conversions (and expected value) per send, under a contact budget.
# * **The decision cell collapses to the channel here**: within a channel, product, objective, segment and market do not
#   move the open or the conversion rate. Empirical-Bayes shrinkage finds this on its own (the channel-anchored rate
#   equals the channel rate), which is why it is the safe estimator to deploy: on real data, where cells do differ, the
#   same code keeps the difference.
# * **A model at this grain is a small table, not a service**: a monthly batch refits α, β and the channel means, and
#   publishes per cell the posterior rate, the expected value per send and the break-even margin.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
