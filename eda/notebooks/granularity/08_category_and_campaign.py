# %% [markdown]
# # 08 · Category × month and campaign × day: spend mix, campaign economics and contact fatigue
# **Granularity series** · grains: one merchant category, market and month (`agg.fct_category_month`); one campaign and
# send day (`agg.fct_campaign_day`)
#
# **Stakeholders.** Card issuing and merchant partnerships (where customers spend, and whether the mix shifts), the
# marketing director (which campaigns pay back, how fast customers respond, whether more contact means less response)
# and compliance (contact pressure on customers).
#
# **Methods.**
# 1. **Spend mix:** category shares per market and month, concentration (Herfindahl–Hirschman index), a mix-shift test
#    (population stability index between the first and last six months, and a chi-square test of independence between
#    month and category), decline and flagged-fraud rates per category with Wilson intervals.
# 2. **Campaign economics:** the funnel (sent → delivered → opened → clicked → converted) per campaign, conversion with
#    Wilson intervals, return on spend with a cluster bootstrap over send days.
# 3. **Do campaigns differ?** If all campaigns converted at the same rate, the spread of their observed rates would be
#    binomial noise; a chi-square test of homogeneity across campaigns says whether choosing between campaigns can
#    matter at all.
# 4. **Time to convert and fatigue:** the delay from send to conversion, the response by day of a campaign's life, and
#    the conversion of a send as a function of how many sends the customer received in the previous 30 days.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import statsmodels.api as sm
import statsmodels.formula.api as smf
from IPython.display import Markdown, display
from itables import show
from scipy import stats
from statsmodels.stats.proportion import proportion_confint

from latam_eda import country, theme
from latam_eda import granularity as g

OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(["fct_category_month", "fct_campaign_day", "dim_merchant_category"], verbose=False)
pl.ensure(pl.key("mart_campaign_compliance_uplift"))
FULL = star.q("select month_start from {dim_month} where not is_partial order by 1").month_start
FIRST, LAST = FULL.min(), FULL.max()
targets = []

# %% [markdown]
# ## 1 · Spend mix by category

# %%
cm = star.q(f"""select * from {{fct_category_month}} where month_start between '{FIRST}' and '{LAST}'
                and category <> 'no merchant' order by 1, 2, 3""")
cm["share"] = cm.approved_usd / cm.groupby(["country_code", "month_start"]).approved_usd.transform(
    "sum"
)
fig = px.area(
    cm[cm.country_code == "MX"],
    x="month_start",
    y="share",
    color="category",
    title="Mexico: share of card spend by merchant category",
)
fig.update_layout(height=320, yaxis_tickformat=".0%", xaxis_title=None)
fig.show()
hhi = cm.groupby(["country_code", "month_start"]).share.apply(g.hhi).reset_index(name="HHI")
cat_rows = []
for cc, d in cm.groupby("country_code"):
    first6 = (
        d[d.month_start < FIRST + pd.DateOffset(months=6)].groupby("category").approved_usd.sum()
    )
    last6 = d[d.month_start > LAST - pd.DateOffset(months=6)].groupby("category").approved_usd.sum()
    a, b = first6 / first6.sum(), last6 / last6.sum()
    psi = float(((b - a) * np.log(b / a)).sum())
    ct = d.pivot_table(index="month_start", columns="category", values="n_tx", aggfunc="sum")
    chi2, p, dof, _ = stats.chi2_contingency(ct.to_numpy())
    cat_rows.append(
        {
            "market": cc,
            "mean HHI": hhi[hhi.country_code == cc].HHI.mean(),
            "PSI first vs last 6 months": psi,
            "chi2 month × category": chi2,
            "dof": dof,
            "p_value": p,
        }
    )
cats = pd.DataFrame(cat_rows)
show(cats.round(4), paging=False)
rates = cm.groupby("category")[["n_tx", "n_declined", "n_flagged_fraud"]].sum()
for c, k in [("decline", "n_declined"), ("flagged fraud", "n_flagged_fraud")]:
    lo, hi = proportion_confint(rates[k], rates.n_tx, method="wilson")
    rates[f"{c} rate %"] = 100 * rates[k] / rates.n_tx
    rates[f"{c} 95 % CI"] = [
        f"{100 * a_:.3f}–{100 * b_:.3f}" for a_, b_ in zip(lo, hi, strict=True)
    ]
chi_dec = stats.chi2_contingency(np.column_stack([rates.n_declined, rates.n_tx - rates.n_declined]))
show(rates, paging=False)
cats.assign(table="mix").to_csv(OUT / "granularity_categories.csv", index=False)
for _, r in cats.iterrows():
    psi_ = r["PSI first vs last 6 months"]
    targets.append(
        {
            "grain": "category × month",
            "target": f"spend mix shift ({r.market})",
            "kind": "test",
            "metric": "PSI",
            "value": psi_,
            "baseline": 0.1,
            "p_value": r.p_value,
            "verdict": "mix shifting" if r.p_value < 0.01 and psi_ > 0.1 else "stable mix",
        }
    )
targets.append(
    {
        "grain": "category × month",
        "target": "decline rate differs by category",
        "kind": "test",
        "metric": "chi2",
        "value": chi_dec.statistic,
        "p_value": chi_dec.pvalue,
        "verdict": "rates differ" if chi_dec.pvalue < 0.01 else "same rate in every category",
    }
)
display(
    Markdown(
        f"**Spend is spread evenly over {cm.category.nunique()} categories (HHI {cats['mean HHI'].mean():,.0f}; an even "
        f"split would be {10_000 / cm.category.nunique():,.0f}) and the mix does "
        + ("not " if cats["PSI first vs last 6 months"].max() < 0.1 else "")
        + f"shift (largest PSI {cats['PSI first vs last 6 months'].max():.4f}).** Decline rates "
        + (
            f"are the same in every category (p = {chi_dec.pvalue:.2g})"
            if chi_dec.pvalue >= 0.01
            else f"differ by category (p = {chi_dec.pvalue:.2g})"
        )
        + ". With 6 categories and 24 merchants, this grain can carry a spend-mix KPI and nothing a partnership team "
        "could act on: real merchant analytics needs merchant category codes (MCC) and merchant identifiers at scale."
    )
)

# %% [markdown]
# ## 2 · Campaign economics: funnel, conversion and return

# %%
cd = star.q("select * from {fct_campaign_day} order by campaign_id, send_date")
camp = (
    cd.groupby(
        ["campaign_id", "campaign_type", "campaign_objective", "promoted_product"], dropna=False
    )
    .agg(
        days=("send_date", "nunique"),
        sends=("sends", "sum"),
        delivered=("delivered", "sum"),
        opened=("opened", "sum"),
        clicked=("clicked", "sum"),
        conversions=("conversions", "sum"),
        value=("conversion_value", "sum"),
        cost=("send_cost", "sum"),
    )
    .reset_index()
)
lo, hi = proportion_confint(camp.conversions, camp.sends, method="wilson")
camp["conversion %"] = 100 * camp.conversions / camp.sends
camp["conv_lo %"], camp["conv_hi %"] = 100 * lo, 100 * hi
camp["ROI"] = (camp.value - camp.cost) / camp.cost
rng = np.random.default_rng(7)
roi_ci = {}
for cid, d in cd.groupby("campaign_id"):
    v, c = d.conversion_value.to_numpy(), d.send_cost.to_numpy()
    bs = []
    for _ in range(300):
        i = rng.integers(0, len(d), len(d))
        bs.append((v[i].sum() - c[i].sum()) / c[i].sum() if c[i].sum() else np.nan)
    roi_ci[cid] = np.nanquantile(bs, [0.025, 0.975])
camp["ROI_lo"] = camp.campaign_id.map(lambda c: roi_ci[c][0])
camp["ROI_hi"] = camp.campaign_id.map(lambda c: roi_ci[c][1])
funnel = camp[["sends", "delivered", "opened", "clicked", "conversions"]].sum()
fig = go.Figure(go.Funnel(y=funnel.index, x=funnel.values, textinfo="value+percent initial"))
fig.update_layout(title="The campaign funnel, all campaigns", height=320)
fig.show()
camp.to_csv(OUT / "granularity_campaigns.csv", index=False)
show(
    camp.sort_values("ROI", ascending=False)[
        [
            "campaign_id",
            "campaign_type",
            "promoted_product",
            "sends",
            "conversion %",
            "conv_lo %",
            "conv_hi %",
            "ROI",
            "ROI_lo",
            "ROI_hi",
        ]
    ].round(3),
    paging=True,
)
chi2, p_het, dof, _ = stats.chi2_contingency(
    np.column_stack([camp.conversions, camp.sends - camp.conversions])
)
pos = camp[camp.ROI_lo > 0]
neg = camp[camp.ROI_hi < 0]
targets.append(
    {
        "grain": "campaign × day",
        "target": "campaigns differ in conversion",
        "kind": "test",
        "metric": "chi2",
        "value": chi2,
        "p_value": p_het,
        "verdict": "campaigns differ" if p_het < 0.01 else "all campaigns convert alike",
    }
)
display(
    Markdown(
        f"**{len(camp)} campaigns, {int(funnel.sends):,} sends, {int(funnel.conversions):,} conversions "
        f"({100 * funnel.conversions / funnel.sends:.2f} %).** "
        + (
            f"Conversion rates differ between campaigns beyond chance (χ² = {chi2:,.0f}, {dof} df, p = {p_het:.2g}). "
            if p_het < 0.01
            else f"Conversion rates do not differ between campaigns beyond binomial noise (χ² = {chi2:,.0f}, {dof} df, "
            f"p = {p_het:.2g}): every campaign converts at the same underlying rate, whatever its type, channel or "
            "product, so ranking campaigns by observed conversion would rank noise. "
        )
        + f"{len(pos)} campaigns pay back with a bootstrap interval above zero and {len(neg)} lose money with an "
        f"interval below zero ({len(camp) - len(pos) - len(neg)} undetermined). The losing campaigns cost "
        f"{-(neg.value - neg.cost).sum():,.0f} USD net over the period."
    )
)

# %% [markdown]
# ### What makes a campaign convert?
# If campaigns differ, the next question is whether the difference is predictable from what is known **before** a
# campaign is launched (its channel, objective, promoted product and market). A binomial GLM at the campaign grain
# (conversions out of sends) is fitted on those attributes; a likelihood-ratio test says whether they matter, and a
# 5-fold out-of-fold prediction (campaigns held out) says whether they would rank a new campaign correctly.

# %%
ch_rate = camp.groupby("campaign_type")[["sends", "conversions", "value", "cost"]].sum()
lo, hi = proportion_confint(ch_rate.conversions, ch_rate.sends, method="wilson")
ch_rate["conversion %"] = 100 * ch_rate.conversions / ch_rate.sends
ch_rate["95 % CI"] = [f"{100 * a_:.3f}–{100 * b_:.3f}" for a_, b_ in zip(lo, hi, strict=True)]
ch_rate["net USD"] = ch_rate.value - ch_rate.cost
show(ch_rate.round(3), paging=False)
cg = camp.dropna(subset=["campaign_type", "campaign_objective", "promoted_product"]).reset_index(
    drop=True
)
cg["fails"] = cg.sends - cg.conversions

FORM = "C(campaign_type) + C(campaign_objective) + C(promoted_product)"
full = smf.glm(f"conversions + fails ~ {FORM}", data=cg, family=sm.families.Binomial()).fit()
null = smf.glm("conversions + fails ~ 1", data=cg, family=sm.families.Binomial()).fit()
lr = 2 * (full.llf - null.llf)
p_lr = stats.chi2.sf(lr, full.df_model)
dev_expl = 1 - full.deviance / null.deviance
fold = pd.util.hash_pandas_object(cg.campaign_id, index=False).to_numpy() % 5
oof = np.full(len(cg), np.nan)
for k in range(5):
    tr = fold != k
    m_ = smf.glm(f"conversions + fails ~ {FORM}", data=cg[tr], family=sm.families.Binomial()).fit()
    try:
        oof[~tr] = m_.predict(cg[~tr])
    except Exception as exc:  # a level unseen in the training folds cannot be scored
        print(f"fold {k}: {type(exc).__name__}, {int((~tr).sum())} campaigns left unscored")
ok = ~np.isnan(oof)
rho, p_rho = stats.spearmanr(oof[ok], (cg.conversions / cg.sends)[ok])
targets.append(
    {
        "grain": "campaign × day",
        "target": "campaign conversion from launch attributes",
        "kind": "model",
        "train_rows": len(cg),
        "metric": "out-of-fold Spearman",
        "value": rho,
        "baseline": 0.0,
        "p_value": p_rho / 2 if rho > 0 else 1 - p_rho / 2,
        "best_single_feature": "campaign_type",
        "verdict": (
            "learnable: rank campaigns before launch"
            if rho > 0.5 and p_rho < 0.01
            else "moderate signal: a model may help, validate further"
            if rho > 0.3 and p_rho < 0.01
            else "no evidence of signal"
        ),
    }
)
zero = ch_rate[ch_rate.conversions == 0]
# the zero channels record no opens, so they cannot attribute a conversion (granularity_time notebook 04): rank again
# without them to see how much of the ranking is that measurement gap
tracked_c = ok & ~cg.campaign_type.isin(zero.index).to_numpy()
rho_t, p_rho_t = stats.spearmanr(oof[tracked_c], (cg.conversions / cg.sends)[tracked_c])
display(
    Markdown(
        f"**Launch attributes explain {100 * dev_expl:.0f} % of the deviance between campaigns (likelihood-ratio "
        f"p = {p_lr:.2g}), and rank held-out campaigns with a Spearman correlation of {rho:.2f} (p = {p_rho:.2g}).** "
        + (
            f"The campaign channel dominates: {', '.join(zero.index)} campaigns record no conversion "
            f"({int(zero.sends.sum()):,} sends, {zero.cost.sum():,.0f} USD of cost), but these channels record no "
            "opens either, and a conversion is only ever attributed after an open: their zero is a **tracking gap, not "
            "a measured failure** (granularity_time notebook 04). Without them the ranking falls to a Spearman of "
            f"{rho_t:.2f} (p = {p_rho_t:.2g}). The tracked channels differ by open rate, "
            if len(zero)
            else "The campaign channel matters most, "
        )
        + "and the promoted product moves conversion by a factor of "
        f"{cg.groupby('promoted_product').apply(lambda d: d.conversions.sum() / d.sends.sum(), include_groups=False).pipe(lambda x: x.max() / x.min()):.1f} "
        "between the best and the worst. **This is a campaign-grain decision with money attached**: instrument the "
        "untracked channels before judging them, and allocate sends by channel before launch, which a transparent rule "
        "or a small model can do (granularity_time notebooks 04 and 05). Uplift (whether the send causes the conversion) "
        "still needs a randomised holdout."
    )
)

# %% [markdown]
# ## 3 · Time to convert, campaign life and contact fatigue

# %%
ttc = star.q("""select date_diff('minute', send_ts_utc, conversion_ts_utc) / 60.0 as hours
                from {fct_campaign_send} where had_conversion and conversion_ts_utc is not null""")
q = ttc.hours.quantile([0.5, 0.9, 0.99])
fig = px.histogram(
    ttc[ttc.hours < ttc.hours.quantile(0.99)],
    x="hours",
    nbins=60,
    title="Hours from send to conversion",
)
fig.update_layout(height=300)
fig.show()
life = cd.groupby(cd.days_since_start.clip(upper=60)).agg(
    sends=("sends", "sum"), conversions=("conversions", "sum")
)
life["conversion %"] = 100 * life.conversions / life.sends
fat = star.q("""select least(prior_sends_30d, 8) as prior_sends_30d, count(*) as sends,
                       avg(outcome_converted::int) as conversion
                from {mart_campaign_compliance_uplift} where treatment_delivered group by 1 order by 1""")
lo, hi = proportion_confint(fat.conversion * fat.sends, fat.sends, method="wilson")
fig = go.Figure(
    go.Scatter(
        x=fat.prior_sends_30d,
        y=100 * fat.conversion,
        mode="markers+lines",
        error_y=dict(
            type="data",
            symmetric=False,
            array=100 * (hi - fat.conversion),
            arrayminus=100 * (fat.conversion - lo),
        ),
    )
)
fig.update_layout(
    title="Conversion of a send by the customer's sends in the previous 30 days (8 = 8 or more)",
    xaxis_title="sends in the previous 30 days",
    yaxis_title="conversion %",
    height=340,
)
fig.show()
fsend = star.q("""select prior_sends_30d, outcome_converted::int as y from {mart_campaign_compliance_uplift}
                  where treatment_delivered and hash(send_id) % 4 = 0""")
logit = smf.logit("y ~ prior_sends_30d", data=fsend).fit(disp=False)
slope, p_slope = logit.params["prior_sends_30d"], logit.pvalues["prior_sends_30d"]
targets.append(
    {
        "grain": "campaign × day",
        "target": "contact fatigue (prior sends lower conversion)",
        "kind": "test",
        "metric": "logit slope per prior send",
        "value": slope,
        "p_value": p_slope / 2 if slope < 0 else 1 - p_slope / 2,
        "verdict": "fatigue" if slope < 0 and p_slope < 0.01 else "no fatigue effect",
    }
)
display(
    Markdown(
        f"**Half of all conversions happen within {q[0.5]:.0f} hours of the send and 90 % within {q[0.9]:.0f} hours.** "
        f"Conversion over a campaign's life moves from {life['conversion %'].iloc[:7].mean():.2f} % in the first week to "
        f"{life['conversion %'].iloc[-7:].mean():.2f} % in its last tracked week. Each additional send in the previous 30 "
        f"days changes the odds of converting by {100 * (np.exp(slope) - 1):+.1f} % (p = {p_slope:.2g}): "
        + (
            "**contact fatigue is real** and a pacing rule (a cap on sends per customer per 30 days) protects conversion."
            if slope < 0 and p_slope < 0.01
            else "**no fatigue**: response does not fall with contact pressure, so a pacing cap is a consent and "
            "customer-experience control (compliance), not a conversion lever."
        )
    )
)

# %%
tab = pd.DataFrame(targets).reindex(columns=g.TARGET_COLUMNS)
tab.to_csv(OUT / "granularity_targets_marketing.csv", index=False)
show(tab, paging=False)

# %% [markdown]
# ## Findings, decisions and what they mean downstream
# * **Marketing KPIs** at the campaign grain: funnel rates with intervals, return on spend with intervals, time to
#   convert, and the share of sends to customers without current consent (50 %, the compliance finding of the marts).
#   A campaign is judged only when its interval excludes zero.
# * **A campaign pacing agent** needs two things this data does not give: campaigns that differ in conversion, and a
#   response that falls with pressure. Without them, pacing is a compliance rule (consent gate, frequency cap), and the
#   value lever is the randomised holdout that would finally measure uplift (ADR-012).
# * **Spend mix** is a KPI, not a model: report category shares per market monthly; real merchant analytics needs MCC
#   codes from the card processor.
# * **Downstream:** both facts are tiny (hundreds and thousands of rows) and serve dashboards directly; campaign ROI must
#   be computed from additive sums (value and cost), never averaged across campaigns.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
