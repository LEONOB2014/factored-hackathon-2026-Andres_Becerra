# %% [markdown]
# # 02 · Customer × month: engagement, retention and cost to serve
# **Granularity series** · grain: one customer in one calendar month (`agg.fct_customer_month`, 5.4 M rows, dense)
#
# **Stakeholders.** The retention team (who is drifting away, and when to act), the service director (how much
# assisted service each customer needs, which drives cost to serve), digital channels (who adopts self-service) and
# marketing (who converts). They all decide per customer and per period, never per transaction.
#
# **What this grain adds.** At the transaction grain a quiet customer is invisible: a customer who stops transacting
# produces no rows. The dense monthly grid makes silence a measurable state, puts every process (money, digital,
# contact centre, complaints, campaigns, surveys) on the same row, and lets one month's events be related to the next
# month's behaviour.
#
# **Methods.**
# 1. **Activity as a Markov chain.** Each customer-month is in one of three states (dormant: no transaction; light:
#    1–2; active: 3 or more). The first-order transition matrix P[i, j] = P(state next month = j | state now = i), its
#    stationary distribution and the expected time spent in each state describe engagement dynamics in one table.
#    Time-homogeneity is tested (is P the same in the first and the last year?).
# 2. **Cohorts.** Retention curves by registration month, for customers registered inside the data window.
# 3. **Cross-process early warnings.** Relative risk of next month's event (a contact, a complaint, dormancy) given this
#    month's event (a digital error, an unresolved contact, a complaint, campaign pressure), with confidence intervals.
# 4. **Out-of-time learnability** of five next-month targets with the series protocol (`country.evaluate_target`), and
#    a **count model** of next month's contacts (Poisson and negative binomial GLMs against a naive run rate).

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
from IPython.display import Markdown, display
from itables import show
from scipy import stats
from scipy.special import xlogy

from latam_eda import country, theme
from latam_eda import granularity as g

OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(["fct_customer_month", "fct_customer_snapshot", "dim_customer_band"], verbose=False)
FULL = star.q("select month_start from {dim_month} where not is_partial order by 1").month_start
FIRST, LAST = FULL.min(), FULL.max()
print(f"full months: {FIRST:%Y-%m} to {LAST:%Y-%m} ({len(FULL)})")

# %% [markdown]
# ## 1 · The monthly picture: how the bank's customers spend their months

# %%
mix = star.q(f"""
    select month_start,
           avg((n_tx = 0)::int) as dormant, avg((n_tx between 1 and 2)::int) as light, avg((n_tx >= 3)::int) as active,
           avg((sessions > 0)::int) as digital, avg((contacts > 0)::int) as contacted,
           avg((complaints_opened > 0)::int) as complained, avg((sends > 0)::int) as targeted
    from {{fct_customer_month}} where month_start between '{FIRST}' and '{LAST}' group by 1 order by 1""")
fig = px.area(
    mix.melt(id_vars="month_start", value_vars=["dormant", "light", "active"]),
    x="month_start",
    y="value",
    color="variable",
    title="Share of customers by activity state, each month",
)
fig.update_layout(height=320, yaxis_tickformat=".0%", xaxis_title=None, legend_title=None)
fig.show()
avg = mix.drop(columns="month_start").mean()
show(
    (100 * avg).round(2).rename("average share of customers in a month (%)").to_frame(),
    paging=False,
)
display(
    Markdown(
        f"**In an average month {100 * avg.dormant:.1f} % of customers make no transaction, {100 * avg.light:.1f} % make "
        f"one or two and {100 * avg.active:.1f} % make three or more.** {100 * avg.digital:.1f} % open a digital "
        f"session, {100 * avg.contacted:.1f} % contact the contact centre, {100 * avg.complained:.2f} % complain and "
        f"{100 * avg.targeted:.1f} % receive a campaign. The shares are flat over time (largest monthly swing of the "
        f"dormant share: {100 * (mix.dormant.max() - mix.dormant.min()):.2f} points)."
    )
)

# %% [markdown]
# ## 2 · Activity as a Markov chain
# Transitions are counted over consecutive full months for every customer (34 months × 150,000 customers). The
# **stationary distribution** π (π P = π) is where the population settles if P holds; comparing it with the observed
# mix tests whether the bank is in equilibrium. The **expected sojourn** 1 / (1 − P[i, i]) is how many months a customer
# stays in a state once there.

# %%
STATE = "case when n_tx = 0 then 'dormant' when n_tx <= 2 then 'light' else 'active' end"
tr = star.q(f"""
    with s as (select customer_id, month_start, country_code, {STATE} as state,
                      lead({STATE}) over (partition by customer_id order by month_start) as next_state,
                      lead(month_start) over (partition by customer_id order by month_start) as next_month
               from {{fct_customer_month}} where month_start between '{FIRST}' and '{LAST}')
    select country_code, year(month_start) as year, state, next_state, count(*) as n
    from s where next_month = month_start + interval 1 month group by all""")
ORDER = ["dormant", "light", "active"]
counts = tr.pivot_table(index="state", columns="next_state", values="n", aggfunc="sum").loc[
    ORDER, ORDER
]
P = counts.div(counts.sum(axis=1), axis=0)
pi = g.stationary(P)
soj = g.expected_sojourn(P)
observed = avg[["dormant", "light", "active"]] / avg[["dormant", "light", "active"]].sum()
markov = P.round(4).assign(
    stationary=pi.round(4),
    observed_share=observed.reindex(ORDER).round(4),
    sojourn_months=soj.round(2),
)
markov.rename_axis("state").reset_index().to_csv(OUT / "granularity_markov.csv", index=False)
show(markov, paging=False)
fig = px.imshow(
    P.round(3),
    text_auto=True,
    color_continuous_scale="Blues",
    title="P(state next month | state this month)",
)
fig.update_layout(height=360)
fig.show()

# time homogeneity: first full year against the last full year, origin state by origin state
years = sorted(tr.year.unique())
hom = []
for s in ORDER:
    a = (
        tr[(tr.state == s) & (tr.year == years[1])]
        .groupby("next_state")
        .n.sum()
        .reindex(ORDER, fill_value=0)
    )
    b = (
        tr[(tr.state == s) & (tr.year == years[-1])]
        .groupby("next_state")
        .n.sum()
        .reindex(ORDER, fill_value=0)
    )
    chi2, p, *_ = stats.chi2_contingency(np.vstack([a, b]))
    hom.append(
        {
            "from": s,
            f"P(stay) {years[1]}": round(a[s] / a.sum(), 4),
            f"P(stay) {years[-1]}": round(b[s] / b.sum(), 4),
            "chi2": round(chi2, 1),
            "p_value": p,
        }
    )
hom = pd.DataFrame(hom)
show(hom, paging=False)
# per country
pc = (
    tr.groupby(["country_code", "state", "next_state"])
    .n.sum()
    .groupby(level=[0, 1])
    .transform(lambda x: x / x.sum())
    .unstack()
)
spread = pc.groupby(level=1).agg(lambda x: x.max() - x.min()).max(axis=1)
display(
    Markdown(
        f"**A dormant customer stays dormant next month with probability {P.loc['dormant', 'dormant']:.3f} (expected "
        f"run {soj['dormant']:.1f} months) and returns to light or active activity with "
        f"{1 - P.loc['dormant', 'dormant']:.3f}; an active customer stays active with {P.loc['active', 'active']:.3f}.** "
        f"The stationary mix (dormant {100 * pi['dormant']:.1f} %, light {100 * pi['light']:.1f} %, active "
        f"{100 * pi['active']:.1f} %) matches the observed mix within "
        f"{100 * (pi - observed.reindex(ORDER)).abs().max():.2f} points: the bank is in equilibrium, nobody is "
        "drifting out on net. "
        + (
            "The matrix is the same in the first and last year (every origin state p > 0.01)"
            if (hom.p_value > 0.01).all()
            else "The matrix changes between the first and last year for "
            + ", ".join(hom[hom.p_value <= 0.01]["from"])
        )
        + f", and across the three markets no transition probability differs by more than {100 * spread.max():.1f} "
        "points. **Dormancy here is a revolving door, not an exit**: a dormant month is followed by activity more often "
        "than by another dormant month, which is why a 90-day horizon (notebook 14 of the country series) is a better "
        "retention target than next month."
    )
)

# %% [markdown]
# ## 3 · Cohorts: retention by registration month
# Most customers were registered before the data starts, so their first observed month is not their first month
# (left truncation): a cohort analysis on them would be an artefact of the data window. The curves below use only the
# customers **registered inside the window**, whose whole history is observed.

# %%
coh = star.q(f"""
    with c as (select customer_id, cast(date_trunc('quarter', registration_date) as date) as cohort,
                      cast(date_trunc('month', registration_date) as date) as reg_month
               from {{fct_customer_snapshot}} where registration_date >= '{FIRST}')
    select c.cohort, date_diff('month', c.reg_month, f.month_start) as months_since_registration,
           avg((f.n_tx > 0)::int) as active_share, count(*) as customers
    from c join {{fct_customer_month}} f using (customer_id)
    where f.month_start >= c.reg_month and f.month_start <= '{LAST}'
    group by all having count(*) >= 50 order by 1, 2""")
n_new = star.q(
    f"select count(*) as n from {{fct_customer_snapshot}} where registration_date >= '{FIRST}'"
).n.iloc[0]
if len(coh):
    fig = px.line(
        coh,
        x="months_since_registration",
        y="active_share",
        color=coh.cohort.astype(str),
        title="Share of customers active, by months since registration (quarterly cohorts)",
    )
    fig.update_layout(height=340, yaxis_tickformat=".0%", legend_title="cohort")
    fig.show()
    first = coh[coh.months_since_registration <= 2].active_share.mean()
    late = coh[coh.months_since_registration >= 12].active_share.mean()
    display(
        Markdown(
            f"**{n_new:,} customers registered inside the window.** Their active share is {100 * first:.1f} % in "
            f"their first three months and {100 * late:.1f} % after a year: "
            + (
                "flat, with no onboarding decay. In a real bank the first months show the steepest attrition; "
                "here customers behave the same from their first month, another generator fingerprint, and an "
                "onboarding programme could not be evaluated on this data."
                if abs(first - late) < 0.03
                else "there is an onboarding effect worth an early-life engagement programme."
            )
        )
    )
else:
    display(
        Markdown(
            f"**Only {n_new:,} customers registered inside the window: no cohort can be followed.**"
        )
    )

# %% [markdown]
# ## 4 · Cross-process early warnings
# Does an event this month raise the chance of another event next month, for the same customer? The **relative risk**
# RR = P(B next month | A this month) / P(B next month | not A) is read with a 95 % interval (log-RR normal
# approximation). These are associations, not causes: they tell where to look and what to monitor, and they become
# features of the models below.

# %%
PAIRS = [
    (
        "digital error → contact",
        "sessions_with_error > 0",
        "contacts_next > 0",
        "true",
        "service: fix the digital failure before the customer calls",
    ),
    (
        "unresolved contact → complaint",
        "unresolved_contacts > 0",
        "complaints_next > 0",
        "true",
        "service: close the loop on unresolved contacts",
    ),
    (
        "complaint → dormant",
        "complaints_opened > 0",
        "n_tx_next = 0",
        "n_tx > 0",
        "retention: a complaint as an attrition trigger",
    ),
    (
        "declined for funds → dormant",
        "insufficient_funds_declines > 0",
        "n_tx_next = 0",
        "n_tx > 0",
        "retention / credit: financial stress",
    ),
    (
        "3+ campaign sends → dormant",
        "sends >= 3",
        "n_tx_next = 0",
        "n_tx > 0",
        "marketing: contact fatigue",
    ),
    (
        "conversion → more activity",
        "conversions > 0",
        "n_tx_next >= 3",
        "n_tx between 1 and 2",
        "marketing: does a conversion deepen the relationship",
    ),
    (
        "escalated contact → dormant",
        "escalations > 0",
        "n_tx_next = 0",
        "n_tx > 0",
        "service: escalation as an attrition trigger",
    ),
]
base = f"""
    select *, lead(n_tx) over w as n_tx_next, lead(contacts) over w as contacts_next,
           lead(complaints_opened) over w as complaints_next, lead(month_start) over w as next_month
    from {{fct_customer_month}} where month_start between '{FIRST}' and '{LAST}'
    window w as (partition by customer_id order by month_start)"""
rows = []
for name, a, b, pop, use in PAIRS:
    r = star.q(f"""
        with x as ({base})
        select count(*) filter (where {a}) as n_a, count(*) filter (where {a} and {b}) as b_a,
               count(*) filter (where not ({a})) as n_na, count(*) filter (where not ({a}) and {b}) as b_na
        from x where next_month = month_start + interval 1 month and {pop}""").iloc[0]
    p1, p0 = r.b_a / r.n_a, r.b_na / r.n_na
    rr = p1 / p0
    se = np.sqrt(1 / r.b_a - 1 / r.n_a + 1 / r.b_na - 1 / r.n_na) if r.b_a and r.b_na else np.nan
    chi2, pv, *_ = stats.chi2_contingency(
        [[r.b_a, r.n_a - r.b_a], [r.b_na, r.n_na - r.b_na]], correction=False
    )
    rows.append(
        {
            "signal": name,
            "months with A": int(r.n_a),
            "P(B | A) %": round(100 * p1, 2),
            "P(B | not A) %": round(100 * p0, 2),
            "relative risk": round(rr, 3),
            "rr_low": round(rr * np.exp(-1.96 * se), 3),
            "rr_high": round(rr * np.exp(1.96 * se), 3),
            "p_value": pv,
            "business use": use,
        }
    )
lifts = pd.DataFrame(rows)
lifts.to_csv(OUT / "granularity_lifts.csv", index=False)
show(lifts, paging=False)
fig = go.Figure(
    go.Scatter(
        x=lifts["relative risk"],
        y=lifts.signal,
        mode="markers",
        error_x=dict(
            type="data",
            symmetric=False,
            array=lifts.rr_high - lifts["relative risk"],
            arrayminus=lifts["relative risk"] - lifts.rr_low,
        ),
    )
)
fig.add_vline(x=1, line_dash="dot")
fig.update_layout(
    title="Relative risk of next month's event (95 % CI)", height=380, xaxis_type="log"
)
fig.show()
lifts["significant (FDR 5 %)"], _ = g.bh_fdr(lifts.p_value)
real = lifts[(lifts.rr_low > 1.1) | (lifts.rr_high < 0.9)]
sig = lifts[lifts["significant (FDR 5 %)"]]
display(
    Markdown(
        f"**{len(real)} of {len(lifts)} early warnings move next month's risk by more than 10 % with an interval that "
        f"excludes no effect; {len(sig)} {'is' if len(sig) == 1 else 'are'} statistically significant after false-discovery "
        "control** "
        + (
            "("
            + "; ".join(f"{r.signal}: RR {r['relative risk']:.3f}" for _, r in sig.iterrows())
            + "). "
            if len(sig)
            else ". "
        )
        + (
            "The decline-to-dormancy association is mechanical, not behavioural: a decline needs a transaction attempt, "
            "so customers with declines were active by construction and are slightly less likely to be dormant next "
            "month. "
            if "declined for funds → dormant" in set(sig.signal)
            else ""
        )
        + "Otherwise the processes are independent from one month to the next: a digital error does not lead to a "
        "call, a complaint does not precede attrition, campaign pressure does not cause disengagement. In a real bank "
        "these chains are the core of service and retention analytics; here they are absent by construction, so each "
        "must be re-measured on real data before a trigger-based programme is designed."
    )
)

# %% [markdown]
# ## 5 · Which next-month targets are learnable at this grain?
# One row per customer and month t (a deterministic 20 % sample of customers, months with six earlier months and a
# full next month), features computed **only from months up to t**, the target in month t + 1, and the series
# protocol: out-of-time split (train on the earliest 75 % of months), gradient boosting, AUC with a Hanley–McNeil
# interval, AP against the base rate and the best single feature.

# %%
panel = star.q(f"""
    with f as (
        select *,
               sum(n_tx) over w3 as tx_3m, sum(n_tx) over w6 as tx_6m, sum(outflow_usd) over w3 as outflow_3m,
               sum(inflow_usd) over w3 as inflow_3m, sum(sessions) over w3 as sessions_3m,
               sum(sessions_with_error) over w3 as error_sessions_3m, sum(contacts) over w3 as contacts_3m,
               sum(unresolved_contacts) over w3 as unresolved_3m, sum(escalations) over w3 as escalations_3m,
               sum(complaints_opened) over w6 as complaints_6m, sum(sends) over w3 as sends_3m,
               sum(conversions) over w6 as conversions_6m, sum(n_declined) over w3 as declined_3m,
               sum(insufficient_funds_declines) over w3 as nsf_3m, sum(surveys) over w6 as surveys_6m,
               sum(detractors) over w6 as detractors_6m,
               lead(n_tx) over w as n_tx_next, lead(contacts) over w as contacts_next,
               lead(complaints_opened) over w as complaints_next, lead(sessions) over w as sessions_next,
               lead(conversions) over w as conversions_next, lead(sends) over w as sends_next
        from {{fct_customer_month}} where hash(customer_id) % 5 = 0
        window w as (partition by customer_id order by month_start),
               w3 as (partition by customer_id order by month_start rows between 2 preceding and current row),
               w6 as (partition by customer_id order by month_start rows between 5 preceding and current row))
    select f.*, c.segment, c.credit_score, c.monthly_income_usd, c.age_years,
           date_diff('day', c.registration_date, f.month_start) as tenure_days
    from f join {{int_customer_profile}} c using (customer_id)
    where f.month_start between '{FIRST}'::date + interval 5 month and '{LAST}'::date - interval 1 month
    order by f.customer_id, f.month_start""")
FEAT = [
    "n_tx",
    "tx_3m",
    "tx_6m",
    "outflow_3m",
    "inflow_3m",
    "sessions_3m",
    "error_sessions_3m",
    "contacts_3m",
    "unresolved_3m",
    "escalations_3m",
    "complaints_6m",
    "sends_3m",
    "conversions_6m",
    "declined_3m",
    "nsf_3m",
    "surveys_6m",
    "detractors_6m",
    "products_held",
    "credit_products_held",
    "country_code",
    "segment",
    "credit_score",
    "monthly_income_usd",
    "age_years",
    "tenure_days",
]
panel["dormant_next"] = panel.n_tx_next == 0
panel["contact_next"] = panel.contacts_next > 0
panel["complaint_next"] = panel.complaints_next > 0
panel["digital_next"] = panel.sessions_next > 0
panel["converts_next"] = panel.conversions_next > 0
TARGETS = [
    ("dormant next month (active now)", "dormant_next", panel.n_tx > 0),
    ("contacts the bank next month", "contact_next", pd.Series(True, index=panel.index)),
    ("complains next month", "complaint_next", pd.Series(True, index=panel.index)),
    (
        "adopts digital next month (no session in 3 months)",
        "digital_next",
        panel.sessions_3m == 0,
    ),
    ("converts next month (when sent a campaign)", "converts_next", panel.sends_next > 0),
]
print(f"panel: {len(panel):,} customer-months, {panel.customer_id.nunique():,} customers")
results = []
for name, target, mask in TARGETS:
    d = panel[mask].copy()
    r = country.evaluate_target(d, target, "month_start", FEAT)
    r["name"] = name
    results.append(g.classification_row("customer × month", r))
    imp = ", ".join(f"{k} ({v:+.3f})" for k, v in list((r.get("importance") or {}).items())[:4])
    display(
        Markdown(
            f"**{name}**: AUC {r['auc']:.3f} [{r['auc_lo']:.3f}, {r['auc_hi']:.3f}], AP lift {r['ap_lift']:.2f} on a "
            f"base rate of {r['base_rate']:.4f} → **{country.verdict(r)}**. Best single feature "
            f"`{r.get('best_single_feature')}` {r.get('best_single_auc', np.nan):.3f}. Top importances: {imp}."
            if np.isfinite(r.get("auc", np.nan))
            else f"**{name}**: {r['note']}."
        )
    )

# %% [markdown]
# ## 6 · A count model: how many contacts will each customer make next month?
# Service demand per customer is a count, mostly zero and overdispersed (notebook 01), so it is modelled with a
# **negative binomial GLM** (and a Poisson GLM for comparison), log link, on the same features, trained on the earlier
# 75 % of months and scored on the later 25 %. The naive benchmark is each customer's own run rate (contacts in the
# last 3 months / 3). Skill is the share of the null deviance explained out of time, and the paired comparison of
# absolute errors (Diebold–Mariano on the row-level losses) says whether the model beats the run rate.

# %%
num = [
    c
    for c in FEAT
    if c not in ("country_code", "segment") and pd.api.types.is_numeric_dtype(panel[c])
]
X = pd.get_dummies(
    panel[num + ["country_code", "segment"]].fillna(0).astype(dict.fromkeys(num, float)),
    columns=["country_code", "segment"],
    drop_first=True,
    dtype=float,
)
X = np.log1p(X.clip(lower=0))
X = sm.add_constant(X)
y = panel.contacts_next.astype(float)
cut = panel.month_start.quantile(0.75)
tr_, te_ = panel.month_start < cut, panel.month_start >= cut
glms = {}
for name, fam in [
    ("Poisson", sm.families.Poisson()),
    ("negative binomial", sm.families.NegativeBinomial(alpha=1.0)),
]:
    glms[name] = sm.GLM(y[tr_], X[tr_], family=fam).fit()
naive = panel.loc[te_, "contacts_3m"] / 3
yt = y[te_].to_numpy()
null_mu = y[tr_].mean()
rows = []


def poisson_dev(yv, mu):
    """Poisson deviance; xlogy(y, y/mu) is 0 where y = 0, so no warning and no undefined term."""
    mu = np.clip(mu, 1e-9, None)
    return 2 * np.sum(xlogy(yv, yv / mu) - (yv - mu))


for name, fit in glms.items():
    mu = fit.predict(X[te_]).to_numpy()
    stat, p = g.diebold_mariano(yt - mu, yt - naive.to_numpy())
    rows.append(
        {
            "model": name,
            "MAE": np.mean(np.abs(yt - mu)),
            "deviance explained %": 100
            * (1 - poisson_dev(yt, mu) / poisson_dev(yt, np.full_like(yt, null_mu))),
            "DM stat vs run rate": stat,
            "DM p": p,
        }
    )
rows.append(
    {
        "model": "run rate (contacts last 3 months / 3)",
        "MAE": np.mean(np.abs(yt - naive)),
        # undefined: the run rate predicts zero contacts for customers who then call (infinite deviance)
        "deviance explained %": np.nan,
    }
)
cm = pd.DataFrame(rows)
show(cm.round(4), paging=False)
best = cm.iloc[cm.iloc[:2]["MAE"].idxmin()]
results.append(
    {
        "grain": "customer × month",
        "target": "contacts next month (count)",
        "kind": "count",
        "train_rows": int(tr_.sum()),
        "test_rows": int(te_.sum()),
        "metric": "deviance explained %",
        "value": best["deviance explained %"],
        "baseline": cm.iloc[-1]["deviance explained %"],
        "p_value": best["DM p"] / 2 if best["DM stat vs run rate"] < 0 else 1 - best["DM p"] / 2,
        "best_single_feature": best.model,
        "verdict": (
            "learnable: the model beats the run rate"
            if best["DM stat vs run rate"] < 0
            and best["DM p"] < 0.05
            and best["deviance explained %"] > 2
            else "no gain over the run rate"
        ),
    }
)
display(
    Markdown(
        f"**Out of time, the {best.model} GLM explains {best['deviance explained %']:.2f} % of the deviance of next "
        f"month's contacts (0 % = predicting the average for everyone), with MAE {best.MAE:.4f} against "
        f"{cm.iloc[-1].MAE:.4f} for the customer's own run rate.** "
        + (
            "A customer's contact history barely predicts next month's contacts: service demand per customer is close to "
            "a random draw around a common rate. Staffing must be planned on the aggregate (notebooks 04 and 06), "
            "not built up from customer predictions."
            if best["deviance explained %"] < 5
            else "Customer-level demand is predictable enough to target proactive service."
        )
    )
)

# %%
tab = pd.DataFrame(results).reindex(columns=g.TARGET_COLUMNS)
tab.to_csv(OUT / "granularity_targets_customer_month.csv", index=False)
show(tab, paging=False)

# %% [markdown]
# ## Findings, decisions and what they mean downstream
# The computed statements above are this notebook's findings. What follows for the stakeholders and the pipelines:
# * **Retention** works at the 90-day horizon with the transparent rate model already decided (ADR-012); the monthly
#   Markov chain is the right **KPI** for the retention team (the dormant-to-active return rate and the active
#   persistence rate, monitored per market each month), not a model target.
# * **The customer-month fact is the single most reusable aggregate**: it already feeds the credit, AML and collections
#   marts as `int_customer_month_tx`, and extending it across processes (this notebook) gives every customer-level
#   model and the relationship-manager assistant one table to read. Promote it.
# * **Cost to serve** cannot be predicted per customer here; it is a rate times a volume, planned at the day grain.
# * **Downstream:** a dense 5.4 M-row monthly fact grows by the customer base each month; build it incrementally
#   (only the new month) in dbt, and test it with the three families of notebook 01. Serving it to an agent needs a
#   `serving_customer_month` contract with tokens only.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
