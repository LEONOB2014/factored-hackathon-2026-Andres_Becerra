# %% [markdown]
# # 06 · The contact centre: agent × day, and the complaint case
# **Granularity series** · grains: one agent and working day (`agg.fct_agent_day`), one complaint case
# (`agg.fct_case`, accumulating snapshot)
#
# **Stakeholders.** The contact-centre director (how many agents per hour, at what service level), team leaders (which
# agents to coach, on what), the customer-experience lead (fairness of service across accents) and compliance (complaint
# cases against their regulatory deadlines).
#
# **Methods.**
# 1. **Staffing with Erlang C.** Hourly arrival rates by weekday and hour, and the average handle time, give the agents
#    needed for a service level of 80 % of contacts answered within 20 seconds (M/M/c queue). Compared with the agents
#    actually working each day.
# 2. **Are agent KPIs real?** A team leader coaches an agent whose resolution rate or sentiment is low. That only makes
#    sense if the KPI measures the agent and not chance. **Split-half reliability**: each agent's KPI on odd months is
#    correlated with the same KPI on even months (Spearman–Brown corrected); a mixed model with a random intercept per
#    agent gives the **intraclass correlation** (the share of variance that belongs to agents). Near zero means the
#    league table is noise.
# 3. **Fairness:** do contacts where the agent's accent matches the customer's resolve better?
# 4. **Complaint cases as survival.** About 70 % of cases are still open at the end of the data. Averaging the
#    resolution time of closed cases would describe only the fast ones; Kaplan–Meier and Cox models use the open cases
#    as right-censored. An **SLA-breach classifier at assignment time** asks whether a case's breach can be foreseen
#    when it is assigned.

# %%
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import statsmodels.formula.api as smf
from IPython.display import Markdown, display
from itables import show
from lifelines import CoxPHFitter, KaplanMeierFitter
from lifelines.statistics import multivariate_logrank_test
from scipy import stats

from latam_eda import country, theme
from latam_eda import granularity as g

warnings.filterwarnings(
    "ignore"
)  # mixed-model convergence notices on a near-zero variance component
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(["fct_agent_day", "fct_case"], verbose=False)

# %% [markdown]
# ## 1 · Staffing: arrivals, handle time and Erlang C

# %%
arr = star.q("""
    select isodow(interaction_ts_utc) as weekday, hour(interaction_ts_utc) as hour,
           count(*) / count(distinct cast(interaction_ts_utc as date)) as contacts_per_hour,
           avg(duration_seconds) as aht_seconds, avg(wait_time_seconds) as observed_wait_seconds
    from {fct_interaction} where interaction_type in ('Inbound Call', 'Chat') group by all order by 1, 2""")
arr["agents_needed"] = [
    g.agents_needed(r.contacts_per_hour, r.aht_seconds, target_seconds=20, service=0.8)
    for r in arr.itertuples()
]
arr["erlang_wait_prob"] = [
    g.erlang_c(r.contacts_per_hour, r.aht_seconds, int(r.agents_needed)) for r in arr.itertuples()
]
fig = px.line(
    arr,
    x="hour",
    y="agents_needed",
    color=arr.weekday.astype(str),
    title="Agents needed for 80 % of contacts answered within 20 s (Erlang C), by UTC hour and weekday",
)
fig.update_layout(height=340, legend_title="weekday")
fig.show()
working = star.q("""select work_date, count(distinct agent_id) as agents, sum(contacts) as contacts,
                           sum(handle_seconds) / 3600.0 as handled_hours
                    from {fct_agent_day} where contacts > 0 group by 1""")
need_hours = arr.groupby("weekday").agents_needed.sum().mean()
hourly_cv = arr.contacts_per_hour.std() / arr.contacts_per_hour.mean()
show(
    pd.DataFrame(
        {
            "contacts per hour (mean)": [arr.contacts_per_hour.mean()],
            "hourly arrival CV": [hourly_cv],
            "AHT (s)": [arr.aht_seconds.mean()],
            "agent-hours needed per day (Erlang C)": [need_hours],
            "agents working per day (observed, median)": [working.agents.median()],
            "handled hours per day (observed, median)": [working.handled_hours.median()],
        }
    ).round(2),
    paging=False,
)
display(
    Markdown(
        f"**Inbound contacts arrive at {arr.contacts_per_hour.mean():.1f} an hour with a handle time of "
        f"{arr.aht_seconds.mean() / 60:.1f} minutes; Erlang C needs {need_hours:.0f} agent-hours a day for an 80/20 "
        f"service level, while a median of {working.agents.median():.0f} agents work each day handling "
        f"{working.handled_hours.median():.0f} hours (an implied occupancy of "
        f"{100 * working.handled_hours.median() / (8 * working.agents.median()):.1f} % of 8-hour shifts).** "
        "The synthetic roster spreads a day's work over hundreds of agents, so it cannot be benchmarked; the Erlang C "
        "figure is the requirement a real roster would be planned against. The hourly arrival profile is "
        + (
            "flat (coefficient of variation "
            f"{hourly_cv:.2f}): in UTC, every hour looks alike, with no morning peak or night trough, so a real "
            "rostering exercise cannot be calibrated here. The method stands: forecast (notebook 04) → hourly arrivals → "
            "Erlang C → shifts."
            if hourly_cv < 0.15
            else f"uneven (coefficient of variation {hourly_cv:.2f}): shifts should follow it."
        )
    )
)

# %% [markdown]
# ## 2 · Are agent KPIs real? Reliability of the league table

# %%
ag = star.q("""
    select agent_id, month(work_date) % 2 as half,
           sum(contacts) as contacts, sum(resolved) as resolved, sum(escalated) as escalated,
           sum(handle_seconds) as handle_seconds, sum(sentiment_sum) as sentiment_sum, sum(sentiment_n) as sentiment_n,
           sum(survey_score_sum) as score_sum, sum(survey_score_n) as score_n
    from {fct_agent_day} group by all""")
ag["resolution rate"] = ag.resolved / ag.contacts
ag["escalation rate"] = ag.escalated / ag.contacts
ag["handle time (s)"] = ag.handle_seconds / ag.contacts
ag["sentiment"] = ag.sentiment_sum / ag.sentiment_n
ag["survey score"] = ag.score_sum / ag.score_n
KPIS = ["resolution rate", "escalation rate", "handle time (s)", "sentiment", "survey score"]
wide = ag[ag.contacts >= 50].pivot(index="agent_id", columns="half", values=KPIS).dropna()
rel = []
for k in KPIS:
    r_half = stats.spearmanr(wide[(k, 0)], wide[(k, 1)]).statistic
    sb = 2 * r_half / (1 + r_half) if r_half > -1 else np.nan
    rel.append(
        {"KPI": k, "agents": len(wide), "split-half r": r_half, "Spearman–Brown reliability": sb}
    )
rel = pd.DataFrame(rel)
# intraclass correlation from a random-intercept model on contacts (a deterministic sample)
ct = star.q("""select agent_id, was_resolved::int as resolved, sentiment_score, contact_reason, channel
               from {fct_interaction} where agent_id is not null and hash(interaction_id) % 20 = 0""")
icc = {}
for yname in ["resolved", "sentiment_score"]:
    d = ct.dropna(subset=[yname])
    m = smf.mixedlm(f"{yname} ~ C(contact_reason) + C(channel)", d, groups=d.agent_id).fit(
        reml=True
    )
    va = float(m.cov_re.iloc[0, 0])
    icc[yname] = va / (va + m.scale)
rel["ICC (random intercept)"] = rel.KPI.map(
    {"resolution rate": icc["resolved"], "sentiment": icc["sentiment_score"]}
)
rel.to_csv(OUT / "granularity_agent_effects.csv", index=False)
show(rel.round(4), paging=False)
fig = px.scatter(
    x=wide[("resolution rate", 0)],
    y=wide[("resolution rate", 1)],
    labels={"x": "resolution rate, odd months", "y": "resolution rate, even months"},
    title="Each agent's resolution rate in odd against even months",
)
fig.update_layout(height=380)
fig.show()
display(
    Markdown(
        f"**The most reliable agent KPI is {rel.loc[rel['Spearman–Brown reliability'].idxmax(), 'KPI']} "
        f"(reliability {rel['Spearman–Brown reliability'].max():.2f}); agents explain "
        f"{100 * icc['resolved']:.2f} % of the variance in resolution and {100 * icc['sentiment_score']:.2f} % in "
        "sentiment.** "
        + (
            "Agent league tables are noise: an agent ranked low this month is as likely to rank high next month. "
            "Coaching or performance pay tied to these KPIs would reward luck. The contact-centre data was generated "
            "without agent effects; on real data, measure reliability before using any agent KPI for decisions (a "
            "reliability below about 0.7 is not fit for individual decisions)."
            if rel["Spearman–Brown reliability"].max() < 0.3
            else "Some agent KPIs are stable enough to coach on."
        )
    )
)

# %% [markdown]
# ## 3 · Fairness: does a matching accent change the outcome?

# %%
fa = star.q("""select accent_matched, count(*) as contacts, avg(was_resolved::int) as resolved,
                      avg(sentiment_score) as sentiment, avg(was_escalated::int) as escalated
               from {fct_interaction} where accent_matched is not null group by 1""")
show(fa.round(4), paging=False)
a, b = fa[fa.accent_matched].iloc[0], fa[~fa.accent_matched].iloc[0]
z = (a.resolved - b.resolved) / np.sqrt(
    a.resolved * (1 - a.resolved) / a.contacts + b.resolved * (1 - b.resolved) / b.contacts
)
p_acc = 2 * stats.norm.sf(abs(z))
display(
    Markdown(
        f"**Resolution with a matching accent {100 * a.resolved:.2f} %, without {100 * b.resolved:.2f} % "
        f"(difference {100 * (a.resolved - b.resolved):+.2f} points, p = {p_acc:.3g}).** "
        + (
            "No measurable difference: routing by accent would not improve outcomes, and no customer group is "
            "disadvantaged by the current routing on this data."
            if p_acc > 0.01 or abs(a.resolved - b.resolved) < 0.005
            else "A material difference: review routing and its fairness implications."
        )
    )
)

# %% [markdown]
# ## 4 · Complaint cases: time to resolution, with censoring

# %%
case = star.q("select * from {fct_case} order by complaint_id")
case = case[case.hours_observed > 0].copy()
case["days_observed"] = case.hours_observed / 24
GRID = np.arange(0, 120.5, 0.5)
km_rows = []
fig = go.Figure()
for pr_, d in case.groupby("priority"):
    km = KaplanMeierFitter().fit(d.days_observed, d.resolved_event, label=pr_)
    fig.add_trace(
        go.Scatter(
            x=GRID,  # a half-day grid: the step function at 65,000 distinct times would bloat the output
            y=1 - km.survival_function_at_times(GRID).to_numpy(),
            name=pr_,
            line_shape="hv",
        )
    )
    km_rows.append(
        {
            "group": "priority",
            "value": pr_,
            "cases": len(d),
            "resolved %": 100 * d.resolved_event.mean(),
            "median days to resolve (KM)": km.median_survival_time_,
            "naive mean of resolved cases (days)": d.loc[d.resolved_event, "days_observed"].mean(),
            "P(resolved within 30 days)": 1 - float(km.predict(30)),
        }
    )
fig.update_layout(
    title="Kaplan–Meier: share of cases resolved, by days since creation and priority",
    xaxis_title="days",
    yaxis_title="resolved",
    height=380,
    xaxis_range=[0, 120],
)
fig.show()
lr = multivariate_logrank_test(case.days_observed, case.priority, case.resolved_event)
kmc = pd.DataFrame(km_rows)
kmc.to_csv(OUT / "granularity_survival_cases.csv", index=False)
show(kmc.round(3), paging=False)
display(
    Markdown(
        f"**{100 * case.resolved_event.mean():.1f} % of cases are resolved; the rest are censored.** Averaging only the "
        f"resolved cases gives {kmc['naive mean of resolved cases (days)'].mean():.1f} days, while "
        + (
            "the Kaplan–Meier median is **not reached**: fewer than half of all cases are ever resolved within the "
            f"data, and only {100 * kmc['P(resolved within 30 days)'].mean():.0f} % within 30 days. "
            if not np.isfinite(kmc["median days to resolve (KM)"]).any()
            else f"the Kaplan–Meier median is {kmc['median days to resolve (KM)'].median():.1f} days. "
        )
        + "The naive figure describes only the fast cases; the slow ones are still open."
        + f" Priority {'does' if lr.p_value < 0.01 else 'does not'} change the resolution curve (log-rank p = "
        f"{lr.p_value:.3g}): "
        + (
            "a critical case is resolved no faster than a low-priority one, which is itself a compliance finding."
            if lr.p_value >= 0.01
            else "the queue honours priorities."
        )
    )
)

# %%
linked = int(case.from_contact.sum())
display(
    Markdown(
        f"**{linked:,} of {len(case):,} complaints carry the contact they originated from** (`origin_interaction_id`). "
        + (
            "None does: a complaint cannot be traced back to the call or chat that raised it, so contact-to-complaint "
            "journeys, first-contact-resolution failures that escalate, and the agent who handled the origin are all "
            "invisible. This is the complaint–contact key in the data requests of strategy §12.7, now confirmed."
            if linked == 0
            else "The link exists and is used below."
        )
    )
)
cx = case.copy()
cx = pd.get_dummies(
    cx[
        [
            "days_observed",
            "resolved_event",
            "priority",
            "reception_channel",
            "category",
            "country_code",
            "prior_contacts_30d",
            "prior_complaints_365d",
        ]
    ],
    columns=["priority", "reception_channel", "category", "country_code"],
    drop_first=True,
    dtype=float,
)
cph = CoxPHFitter(penalizer=0.01).fit(cx, "days_observed", "resolved_event")
hr = cph.summary[["exp(coef)", "p"]].rename(columns={"exp(coef)": "hazard ratio of resolution"})
show(hr.sort_values("p").head(12).round(4), paging=False)
display(
    Markdown(
        f"**Cox model of the resolution hazard: concordance {cph.concordance_index_:.3f}** (0.5 = no ranking). "
        + (
            "Nothing known about a case at creation tells how fast it will be resolved."
            if cph.concordance_index_ < 0.55
            else "Case attributes rank resolution speed."
        )
    )
)

# %% [markdown]
# ## 5 · Can an SLA breach be foreseen at assignment?
# For assigned cases, using only what is known when the case is assigned (priority, category, channel, market, whether
# it came from a contact, the customer's recent contacts and complaints, and the hours it waited for assignment),
# predict `sla_breached`. Out-of-time split by creation date, series protocol.

# %%
sl = case[case.assigned_ts_utc.notna()].copy()
FEAT = [
    "priority",
    "category",
    "subcategory",
    "reception_channel",
    "country_code",
    "prior_contacts_30d",
    "prior_complaints_365d",
    "hours_to_assign",
]
r = country.evaluate_target(sl, "sla_breached", "created_ts_utc", FEAT)
r["name"] = "SLA breached (at assignment)"
sig = pd.DataFrame([g.classification_row("complaint case", r)]).reindex(columns=g.TARGET_COLUMNS)
cox_row = {
    "grain": "complaint case",
    "target": "time to resolution",
    "kind": "survival",
    "metric": "concordance (in-sample)",
    "value": cph.concordance_index_,
    "baseline": 0.5,
    "p_value": float(np.min(cph.summary.p)) * len(cph.summary),  # Bonferroni over the covariates
    "verdict": "no evidence of signal"
    if cph.concordance_index_ < 0.55
    else "weak: rules, not models",
}
sig = pd.concat([sig, pd.DataFrame([cox_row])]).reindex(columns=g.TARGET_COLUMNS)
sig["p_value"] = sig.p_value.clip(upper=1)
sig.to_csv(OUT / "granularity_targets_contact.csv", index=False)
show(sig, paging=False)
display(
    Markdown(
        f"**SLA breach at assignment: AUC {r['auc']:.3f} [{r['auc_lo']:.3f}, {r['auc_hi']:.3f}] on a base rate of "
        f"{r['base_rate']:.3f} → {country.verdict(r)}.** "
        + (
            "A breach cannot be foreseen from the case: SLA risk triage must be a deadline rule (alert at a share of "
            "the regulatory clock), not a predictive score."
            if r["auc_lo"] <= 0.55
            else "Breaches can be ranked at assignment: an SLA-risk triage score is justified."
        )
    )
)

# %% [markdown]
# ## Findings, decisions and what they mean downstream
# * **Staffing advisor:** forecast → hourly arrivals → Erlang C → shifts is a deterministic pipeline with a clear KPI
#   (service level, occupancy); an agent can explain a roster, but the numbers come from the queueing formula.
# * **Coaching:** before any agent KPI is used for coaching or pay, its reliability must be measured as above; on this
#   data no KPI is reliable, so a "coaching agent" would rank noise.
# * **Complaint SLAs:** resolution times must be reported with survival methods (the open cases are the slow ones);
#   SLA-risk triage is a deadline rule per market (CONDUSEF, Superfinanciera, BCRA clocks from a compliance seed).
# * **Downstream:** `fct_agent_day` and `fct_case` are small and cheap; `fct_case` must be rebuilt as cases move
#   through milestones (an accumulating snapshot is updated, not appended). Agent-day figures are personal data about
#   employees: internal use only, with the same access controls as HR data.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
