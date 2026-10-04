# %% [markdown]
# # 09 · Synthesis: which grain earns a model, an agent or a KPI
# **Granularity series** · reads the tables written by notebooks 01–08 and the scratch star
#
# Eight grains were built and tested. This notebook asks the questions across them:
# 1. **Does aggregation create or destroy signal?** The ecological fallacy, measured on this data, and the information
#    lost or gained by moving from the atomic grain to the customer-month.
# 2. **What is real?** Every target and every test of the series in one table, with the **Benjamini–Hochberg** control
#    of the false discovery rate: with dozens of tests, some p-values below 0.05 are expected by chance alone.
# 3. **What should be built?** A KPI catalogue per grain, the opportunities per stakeholder with the evidence behind each,
#    the impact on every downstream pipeline, and which aggregates to promote to the platform.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
import statsmodels.formula.api as smf
from IPython.display import Markdown, display
from itables import show
from scipy import stats

from latam_eda import country, theme
from latam_eda import granularity as g

OUT = Path("../../reports/tables")
T = OUT
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)
star.build(
    [
        "fct_customer_month",
        "fct_customer_snapshot",
        "fct_country_day",
        "dim_data_day",
        "fct_product_month",
    ],
    verbose=False,
)
FULL = star.q("select month_start from {dim_month} where not is_partial order by 1").month_start
FIRST, LAST = FULL.min(), FULL.max()

# %% [markdown]
# ## 1 · The ecological fallacy, measured
# The same pair of measures (digital errors and contacts) is correlated at four grains. If the correlation at an
# aggregate grain were read as a statement about customers ("customers with errors call more"), would it be true?

# %%
eco = []
cmx = star.q(f"""select digital_errors, contacts from {{fct_customer_month}}
                 where month_start between '{FIRST}' and '{LAST}' and hash(customer_id) % 10 = 0""")
eco.append(
    ("customer × month", stats.spearmanr(cmx.digital_errors, cmx.contacts).statistic, len(cmx))
)
cs = star.q(
    "select lifetime_sessions, lifetime_contacts, active_months from {fct_customer_snapshot}"
)
eco.append(
    (
        "customer (lifetime)",
        stats.spearmanr(cs.lifetime_sessions, cs.lifetime_contacts).statistic,
        len(cs),
    )
)
cd = star.q("""select f.country_code, f.local_date, f.digital_errors, f.contacts, d.iso_weekday, d.is_holiday
               from {fct_country_day} f join {dim_data_day} d using (country_code, local_date) where not d.is_edge""")
eco.append(
    ("market × day (raw)", stats.spearmanr(cd.digital_errors, cd.contacts).statistic, len(cd))
)
res = []
for cc, d in cd.groupby("country_code"):
    a = smf.ols("np.log1p(digital_errors) ~ C(iso_weekday) + is_holiday", data=d).fit().resid
    b = smf.ols("np.log1p(contacts) ~ C(iso_weekday) + is_holiday", data=d).fit().resid
    res.append(pd.DataFrame({"a": a, "b": b}))
res = pd.concat(res)
eco.append(("market × day (calendar removed)", stats.spearmanr(res.a, res.b).statistic, len(res)))
# partial correlation at the lifetime grain, controlling for how long the customer was active
pr = smf.ols("np.log1p(lifetime_sessions) ~ active_months", data=cs).fit().resid
pc = smf.ols("np.log1p(lifetime_contacts) ~ active_months", data=cs).fit().resid
eco.append(
    (
        "customer (lifetime, controlling for active months)",
        stats.spearmanr(pr, pc).statistic,
        len(cs),
    )
)
eco = pd.DataFrame(
    eco, columns=["grain", "Spearman correlation: digital errors vs contacts", "rows"]
)
eco.to_csv(OUT / "granularity_ecological.csv", index=False)
show(eco.round(4), paging=False)
fig = px.bar(
    eco,
    x="Spearman correlation: digital errors vs contacts",
    y="grain",
    orientation="h",
    title="One pair of measures, five grains",
)
fig.update_layout(height=320, yaxis_title=None)
fig.show()
e = eco.set_index("grain").iloc[:, 0]
display(
    Markdown(
        f"**At the customer-month grain the correlation is {e['customer × month']:.3f}; across market-days it is "
        f"{e['market × day (raw)']:.3f} raw and {e['market × day (calendar removed)']:.3f} once the weekday is removed; "
        f"across customers' lifetimes it is {e['customer (lifetime)']:.3f}, and {e['customer (lifetime, controlling for active months)']:.3f} "
        "after controlling for how long they were active.** "
        "The aggregate correlations are made by a common driver (busy days are busy for every process; long relationships "
        "accumulate everything), not by any link between errors and calls. Reading them as customer behaviour is the "
        "ecological fallacy. **Rule for every dashboard and agent built on aggregates:** a co-movement at an aggregate "
        "grain is a hypothesis about units, to be tested at the unit grain after removing common drivers."
    )
)

# %% [markdown]
# ## 2 · Information: what moving from atomic rows to aggregates did to the one learnable target
# Dormancy is the one target the earlier series found learnable. Its AUC at each grain and horizon:

# %%
cnt = pd.read_csv(T / "country_all_learnability.csv")
cm_t = pd.read_csv(T / "granularity_targets_customer_month.csv")
pr_t = pd.read_csv(T / "granularity_targets_product.csv")
cu_t = pd.read_csv(T / "granularity_targets_customer.csv")
info = pd.DataFrame(
    [
        {
            "grain and horizon": "customer × quarter cutoff, next 90 days (country series)",
            "AUC": cnt.loc[cnt.name.str.startswith("dormant"), "auc"].iloc[0],
        },
        {
            "grain and horizon": "customer × month, next month",
            "AUC": cm_t.loc[cm_t.target.str.startswith("dormant"), "value"].iloc[0],
        },
        {
            "grain and horizon": "product × month, next 3 months",
            "AUC": pr_t.loc[pr_t.target.str.startswith("product dormant"), "value"].iloc[0],
        },
        {
            "grain and horizon": "customer lifetime, time to first 90-day lapse (concordance)",
            "AUC": cu_t.value.iloc[0],
        },
    ]
)
show(info.round(3), paging=False)
display(
    Markdown(
        f"**The horizon matters more than the grain.** Next-month dormancy ({info.AUC.iloc[1]:.3f}) is harder than 90-day "
        f"dormancy ({info.AUC.iloc[0]:.3f}) because a single empty month is mostly noise (the Markov chain of notebook 02: "
        "a dormant month is followed by activity more often than not); three empty months are a state. The product grain "
        f"({info.AUC.iloc[2]:.3f}) and the lifetime grain ({info.AUC.iloc[3]:.3f}) carry the same signal: a unit's own "
        "recent activity rate. Aggregation neither created nor destroyed it; the right horizon revealed it."
    )
)

# %% [markdown]
# ### Where the one signal comes from: exposure
# The product grain finds no dormancy signal (each product is used in about a quarter of months, notebook 07), yet the
# customer grain does. If each product is used independently with probability p in a month, a customer holding k
# products makes no transaction with probability (1 − p)^k. If the observed dormant share by number of products
# follows that curve, the customer-level "signal" is the arithmetic of exposure, not behaviour.

# %%
ex = star.q(f"""select least(products_held, 8) as products_held, avg((n_tx = 0)::int) as dormant, count(*) as months
                from {{fct_customer_month}} where month_start between '{FIRST}' and '{LAST}' and products_held > 0
                group by 1 order by 1""")
pm = star.q(f"""select avg((n_tx > 0)::int) as p from {{fct_product_month}}
                where not before_opening and month_start between '{FIRST}' and '{LAST}'""").p.iloc[
    0
]
# fit log P(dormant | k) = log c + k log(1 - p): the slope is the per-product non-use rate, c absorbs activity on
# products the customer does not hold in the month (transactions dated before their product opened, R01)
fit = smf.wls("np.log(dormant) ~ products_held", data=ex, weights=ex.months).fit()
ratio = float(np.exp(fit.params["products_held"]))
c0 = float(np.exp(fit.params["Intercept"]))
ex["fitted c·r^k"] = c0 * ratio**ex.products_held
ex["independent (1 - p)^k"] = (1 - pm) ** ex.products_held
ex.to_csv(OUT / "granularity_exposure.csv", index=False)
show(ex.round(4), paging=False)
fig = px.line(
    ex.melt(
        id_vars="products_held", value_vars=["dormant", "fitted c·r^k", "independent (1 - p)^k"]
    ),
    x="products_held",
    y="value",
    color="variable",
    markers=True,
    log_y=True,
    title="Dormant share of customer-months by products held (log scale): a straight line is a geometric law",
)
fig.update_layout(height=360)
fig.show()
gap = (ex.dormant - ex["fitted c·r^k"]).abs().max()
r01 = star.q(
    "select avg(dq_r01_before_product_open::int) as r from {int_transactions_enriched}"
).r.iloc[0]
exposure_law = abs(ratio - (1 - pm)) < 0.02 and fit.rsquared > 0.99
display(
    Markdown(
        f"**The dormant share falls geometrically with the number of products held: each extra product multiplies it "
        f"by {ratio:.3f} (R² {fit.rsquared:.4f} on the log scale, largest gap to the fitted law {100 * gap:.2f} points), "
        f"and a product taken alone is unused in {100 * (1 - pm):.1f} % of months.** "
        + (
            f"The two agree: each product independently goes unused with probability about {1 - pm:.2f} a month, and a "
            f"customer is dormant only when all of them are. The constant c = {c0:.2f} says that about "
            f"{100 * (1 - c0):.0f} % of the activity arrives through products the customer does not yet hold that month: "
            f"the transactions dated before their product opened (the R01 defect, {100 * r01:.1f} % of transactions), "
            "which the count of products held cannot see. **The customer-level dormancy signal "
            "is the arithmetic of exposure**: how many products a customer holds, each used independently. A real "
            "retention model must beat this one-parameter law before it can claim any behavioural signal; on this data "
            "the law is the model."
            if exposure_law
            else "Dormancy departs from independent product use: there is behaviour beyond exposure."
        )
    )
)

# %% [markdown]
# ## 3 · Every target and test of the series, with false-discovery control

# %%
parts = []
for f in [
    "granularity_targets_customer_month.csv",
    "granularity_targets_customer.csv",
    "granularity_targets_day.csv",
    "granularity_targets_branch.csv",
    "granularity_targets_contact.csv",
    "granularity_targets_product.csv",
    "granularity_targets_marketing.csv",
]:
    parts.append(
        pd.read_csv(T / f).assign(
            source=f.removeprefix("granularity_targets_").removesuffix(".csv")
        )
    )
lif = pd.read_csv(T / "granularity_lifts.csv")
parts.append(
    pd.DataFrame(
        {
            "grain": "customer × month",
            "target": "early warning: " + lif.signal,
            "kind": "association",
            "metric": "relative risk",
            "value": lif["relative risk"],
            "ci_low": lif.rr_low,
            "ci_high": lif.rr_high,
            "baseline": 1.0,
            "p_value": lif.p_value,
            "verdict": np.where(
                (lif.rr_low > 1.1) | (lif.rr_high < 0.9),
                "material association",
                "no material association",
            ),
            "source": "lifts",
        }
    )
)
gr = pd.read_csv(T / "granularity_granger.csv")
parts.append(
    pd.DataFrame(
        {
            "grain": "market × day (" + gr.market + ")",
            "target": "Granger: " + gr.cause + " → " + gr.effect,
            "kind": "association",
            "metric": "best lag (days)",
            "value": gr["best lag (days)"],
            "p_value": (gr.p_value * 7).clip(upper=1),
            "verdict": np.where(gr["significant (FDR 5 %)"], "leads", "no lead"),
            "source": "granger",
        }
    )
)
sig = pd.concat(parts, ignore_index=True)
ok = sig.p_value.notna()
sig["significant (FDR 5 %)"] = False
sig["p_adjusted"] = np.nan
rej, adj = g.bh_fdr(sig.loc[ok, "p_value"].to_numpy(), 0.05)
sig.loc[ok, "significant (FDR 5 %)"] = rej
sig.loc[ok, "p_adjusted"] = adj
material = (
    sig["significant (FDR 5 %)"]
    & sig.verdict.str.contains(
        "learnable|forecastable|marginal|moderate|weak|material|leads|differ|fatigue|shifting",
        regex=True,
    )
    & ~sig.verdict.str.contains("no ", regex=False)
)
sig["actionable"] = material
sig.to_csv(OUT / "granularity_signal.csv", index=False)
show(
    sig[
        [
            "grain",
            "target",
            "kind",
            "metric",
            "value",
            "baseline",
            "p_adjusted",
            "significant (FDR 5 %)",
            "verdict",
            "actionable",
        ]
    ].round(4),
    paging=True,
)
by = sig.groupby("grain").agg(
    tested=("target", "size"),
    significant=("significant (FDR 5 %)", "sum"),
    actionable=("actionable", "sum"),
)
show(by, paging=False)
display(
    Markdown(
        f"**{len(sig)} targets and tests across {sig.grain.nunique()} grains; {int(sig['significant (FDR 5 %)'].sum())} "
        f"survive the false-discovery control and {int(sig.actionable.sum())} are both significant and material.** "
        "The actionable ones: "
        + "; ".join(
            f"{r.grain}: {r.target} ({r.verdict})" for r in sig[sig.actionable].itertuples()
        )
        + "."
    )
)

# %% [markdown]
# ## 4 · KPI catalogue
# One KPI per business question, each defined as a ratio of additive sums on one fact (never an average of ratios),
# with its owner, cadence and the alerting rule that turns it into a control. The current value is computed on the last
# full month or the last 28 days.

# %%
KPIS = [
    (
        "customer × month",
        "active customer rate",
        "share of customers with a transaction in the month",
        "retention",
        "monthly",
        f"select avg((n_tx > 0)::int) from {{fct_customer_month}} where month_start = '{LAST}'",
        "control chart on the monthly rate",
    ),
    (
        "customer × month",
        "dormant-to-active return rate",
        "P(active next month | dormant this month), Markov chain",
        "retention",
        "monthly",
        f"""select avg((n2 > 0)::int) from (select n_tx, lead(n_tx) over (partition by customer_id order by month_start) as n2,
         month_start from {{fct_customer_month}}) where n_tx = 0 and month_start = '{LAST}'::date - interval 1 month""",
        "drop of 2 points",
    ),
    (
        "customer × month",
        "digital adoption",
        "share of customers with a digital session in the month",
        "digital",
        "monthly",
        f"select avg((sessions > 0)::int) from {{fct_customer_month}} where month_start = '{LAST}'",
        "trend test quarterly",
    ),
    (
        "customer × month",
        "contacts per 100 customers",
        "100 × Σ contacts / customers",
        "service",
        "monthly",
        f"select 100.0 * sum(contacts) / count(*) from {{fct_customer_month}} where month_start = '{LAST}'",
        "control chart",
    ),
    (
        "customer × month",
        "complaints per 10,000 transactions",
        "10,000 × Σ complaints / Σ transactions",
        "compliance",
        "monthly",
        f"select 1e4 * sum(complaints_opened) / sum(n_tx) from {{fct_customer_month}} where month_start = '{LAST}'",
        "regulatory threshold per market",
    ),
    (
        "customer (lifetime)",
        "top-decile share of spend",
        "spend of the top 10 % of customers / total spend",
        "retail head",
        "quarterly",
        "select sum(v) filter (where r > 0.9) / sum(v) from (select lifetime_outflow_usd as v, percent_rank() over (order by lifetime_outflow_usd) as r from {fct_customer_snapshot})",
        "none (structural)",
    ),
    (
        "market × day",
        "decline rate",
        "Σ declined / Σ transactions",
        "operations",
        "daily",
        "select sum(n_declined)::double / sum(n_tx) from {fct_country_day} where local_date > (select max(local_date) - 28 from {fct_country_day})",
        "p-chart, 3σ",
    ),
    (
        "market × day",
        "escalation rate",
        "Σ escalations / Σ contacts",
        "contact centre",
        "daily",
        "select sum(escalations)::double / sum(contacts) from {fct_country_day} where local_date > (select max(local_date) - 28 from {fct_country_day})",
        "p-chart, 3σ",
    ),
    (
        "market × day",
        "average wait (s)",
        "Σ wait seconds / Σ contacts",
        "contact centre",
        "daily",
        "select sum(wait_seconds)::double / sum(contacts) from {fct_country_day} where local_date > (select max(local_date) - 28 from {fct_country_day})",
        "service-level target (80/20)",
    ),
    (
        "branch × day",
        "cash service level",
        "share of branch-days without a stock-out (notebook 05 policy)",
        "treasury",
        "daily",
        None,
        "below target service level",
    ),
    (
        "branch × day",
        "cash per withdrawal (USD)",
        "Σ withdrawals USD / Σ withdrawals",
        "treasury",
        "daily",
        "select sum(withdrawals_usd) / sum(n_withdrawals) from {fct_branch_day} where local_date > (select max(local_date) - 28 from {fct_branch_day})",
        "control chart",
    ),
    (
        "agent × day",
        "first-contact resolution",
        "Σ resolved / Σ contacts",
        "contact centre",
        "weekly",
        "select sum(resolved)::double / sum(contacts) from {fct_agent_day} where work_date > (select max(work_date) - 28 from {fct_agent_day})",
        "team level only (agent level unreliable)",
    ),
    (
        "complaint case",
        "median days to resolution (Kaplan–Meier)",
        "survival median, open cases censored",
        "compliance",
        "weekly",
        None,
        "per market regulatory clock",
    ),
    (
        "complaint case",
        "SLA breach rate",
        "Σ breached / Σ cases closed in period",
        "compliance",
        "weekly",
        "select avg(sla_breached::int) from {fct_case} where resolved_event",
        "regulatory threshold",
    ),
    (
        "product × month",
        "active product rate",
        "share of open products used in the month",
        "product",
        "monthly",
        f"select avg((n_tx > 0)::int) from {{fct_product_month}} where month_start = '{LAST}' and not before_opening",
        "per family trend",
    ),
    (
        "campaign × day",
        "conversion per send",
        "Σ conversions / Σ sends",
        "marketing",
        "per campaign",
        "select sum(conversions)::double / sum(sends) from {fct_campaign_day}",
        "only with a holdout",
    ),
    (
        "campaign × day",
        "return on campaign spend",
        "(Σ conversion value − Σ cost) / Σ cost",
        "marketing",
        "per campaign",
        "select (sum(conversion_value) - sum(send_cost)) / sum(send_cost) from {fct_campaign_day}",
        "interval must exclude 0",
    ),
    (
        "customer × month",
        "sends without current consent",
        "share of sends to customers without consent (marts)",
        "compliance",
        "daily",
        "select avg(sent_without_current_consent::int) from {mart_campaign_compliance_uplift}",
        "target 0 %",
    ),
]
star.build(
    ["fct_branch_day", "fct_agent_day", "fct_case", "fct_product_month", "fct_campaign_day"],
    verbose=False,
)
pl.ensure(pl.key("mart_campaign_compliance_uplift"))
rows = []
for grain, name, definition, owner, cadence, sql, alert in KPIS:
    val = float(star.q(sql).iloc[0, 0]) if sql else np.nan
    rows.append(
        {
            "grain": grain,
            "KPI": name,
            "definition": definition,
            "owner": owner,
            "cadence": cadence,
            "current value": val,
            "alert rule": alert,
        }
    )
kpis = pd.DataFrame(rows)
cash = pd.read_csv(T / "granularity_cash.csv")
pol = cash[cash.table == "policy"]
kpis.loc[kpis.KPI == "cash service level", "current value"] = pol.iloc[3]["service level %"] / 100
cases = pd.read_csv(T / "granularity_survival_cases.csv")
kpis.loc[kpis.KPI.str.startswith("median days"), "current value"] = cases[
    "median days to resolve (KM)"
].median()
kpis.to_csv(OUT / "granularity_kpis.csv", index=False)
show(kpis.round(4), paging=False)

# %% [markdown]
# ## 5 · Opportunities: what each stakeholder can have, and on what evidence
# Each opportunity names the decision it serves, the grain, the solution type (a model only where §3 found signal; a
# deterministic service or a rule otherwise), the agent that would expose it, and its readiness.


# %%
def verdict_of(pattern: str) -> str:
    m = sig[sig.target.str.contains(pattern, regex=False)]
    return "; ".join(sorted(set(m.verdict))) if len(m) else "not tested"


OPP = [
    (
        "Retention team",
        "whom to contact before they lapse",
        "customer × quarter / month",
        "transparent rate model (90-day dormancy) + monthly Markov KPIs",
        "relationship-manager assistant",
        verdict_of("dormant next month"),
        "build now (ADR-012)",
        "retained activity × value proxy",
    ),
    (
        "Head of retail",
        "where value sits and how long customers stay engaged",
        "customer (lifetime)",
        "KPIs: value concentration, Kaplan–Meier lapse curves, RMST",
        "none (dashboard)",
        verdict_of("time to first 90-day lapse"),
        "build now",
        "value-based retention budget",
    ),
    (
        "COO / operations",
        "is today normal, and where not",
        "market × day, channel × day",
        "calendar-adjusted control charts + 7-day forecast",
        "operations copilot (explains KPI movements from the facts)",
        verdict_of("n_tx"),
        "build now",
        "faster detection of outages, fraud waves, data gaps",
    ),
    (
        "Treasury",
        "how much cash to load per branch per day",
        "branch × day",
        "deterministic cash planner: market forecast × branch share + newsvendor buffer",
        "cash planner",
        verdict_of("cash withdrawn"),
        "build now; replace cost assumptions with real ones",
        "idle cash and emergency runs",
    ),
    (
        "Contact-centre director",
        "how many agents per hour",
        "market × day → hour",
        "forecast → Erlang C → shifts",
        "staffing advisor",
        verdict_of("contacts"),
        "build after hourly arrivals are real",
        "service level at lower cost",
    ),
    (
        "Team leaders",
        "whom to coach",
        "agent × day",
        "nothing until agent KPIs are reliable",
        "none",
        "agent KPIs unreliable (notebook 06)",
        "do not build",
        "avoids rewarding noise",
    ),
    (
        "Compliance",
        "which complaints will miss their deadline",
        "complaint case",
        "deadline rule per market (regulatory clocks seed) + survival reporting",
        "SLA triage alerts",
        verdict_of("SLA breached"),
        "build the rule now; no score",
        "regulatory sanctions avoided",
    ),
    (
        "Credit risk",
        "which products will roll into delinquency",
        "product × month",
        "blocked: no DPD history; accumulate snapshots",
        "none",
        verdict_of("30 days past due"),
        "after 12 months of snapshots",
        "IFRS 9 staging, collections priority",
    ),
    (
        "Marketing",
        "which campaigns to run, on which channel, for which product",
        "campaign × day",
        "stop channels that never convert; budget by channel × product (campaign-level GLM or rule); consent gate; "
        "randomised holdout for uplift",
        "campaign budget advisor (explains each allocation from the campaign facts)",
        verdict_of("campaign conversion from launch attributes")
        + " / "
        + verdict_of("campaigns differ"),
        "build now",
        "campaign spend with no return, consent compliance",
    ),
]
opp = pd.DataFrame(
    OPP,
    columns=[
        "stakeholder",
        "decision",
        "grain",
        "solution",
        "agent",
        "evidence (verdict)",
        "readiness",
        "value lever",
    ],
)
opp.to_csv(OUT / "granularity_opportunities.csv", index=False)
show(opp, paging=False)

# %% [markdown]
# ## 6 · What promoting each grain costs the pipelines downstream
#
# | pipeline | what changes | pros | cons / risks |
# |---|---|---|---|
# | **dbt** | a `gold/aggregates` layer with the 17 models of notebook 01, each with its grain contract and the three test families (unique grain, additive reconciliation, dense completeness) | one definition of each business number; aggregates reconcile to atomic facts by test, so a lost row fails the build | more models to maintain; dense facts are large (`fct_product_month` 12.4 M rows); needs incremental materialisation by month |
# | **Airflow** | an `aggregates` task group after gold; month-grain facts also run at month close | the forward-dependency defect (eligibility before features) cannot recur if aggregates read only gold | month-close timing must wait for late-arriving facts (the breaker's holds) |
# | **streaming** | intraday twins of the day-grain KPIs (hourly counts per market and channel) with a parity test against the batch day | the operations copilot sees today, not yesterday | a second implementation of each KPI, kept honest only by the parity test |
# | **serving** | grain-keyed serving tables (`serving_customer_month`, `serving_country_day`, `serving_branch_cash_plan`) with dbt contracts, tokens only | agents read narrow, typed, pre-aggregated tables: cheap, fast, auditable | each new serving table is a new contract to version |
# | **privacy** | aggregates lower re-identification risk, but small cells (a branch-day with one withdrawal, an agent-day) identify people | external releases can use aggregates with suppression or differential privacy (ADR-009) | agent-day is employee personal data; branch-day small cells need suppression before any release |
# | **audit and lineage** | aggregates join the lineage graph; their checks become audit evidence | reconciliation tests are themselves controls an auditor can read | none material |
# | **BI / semantic layer** | measures declared additive, semi-additive (balances: never summed over time) or derived (ratios of sums) | prevents the mean-of-ratios and summed-balance errors that plague bank dashboards | semantic-layer tooling needed (dbt metrics or equivalent) |
# | **cost** | storage of dense facts and their monthly growth | small for all but the product-month and customer-month facts | rebuild time grows with history: incremental builds required |

# %% [markdown]
# ## 7 · Recommendation: what to promote to the platform (v0.3.x)
#
# | aggregate | promote? | why |
# |---|---|---|
# | `fct_customer_month` (+ `dim_customer_band`, `dim_month`) | **yes, first** | feeds retention, the relationship-manager assistant, the Markov KPIs and every customer model; extends the existing `int_customer_month_tx` |
# | `fct_customer_snapshot` | **yes** | cheap; the "summarise this customer" input for agents; lifetime KPIs |
# | `fct_country_day`, `fct_channel_day` (+ `dim_country_day`, `dim_data_day`) | **yes** | the operations KPIs and control charts; tiny; the calendar becomes a governed seed (ADR-011) |
# | `fct_branch_day` | **yes** | the cash planner: a deterministic service with measurable money attached |
# | `fct_case` (+ `dim_case_type`) | **yes** | regulatory reporting with survival methods; SLA rules per market |
# | `fct_campaign_day` | **yes** | campaign economics with intervals, budget allocation by channel × product, and the holdout design |
# | `fct_agent_day` | **internal only** | staffing inputs are useful; agent-level KPIs are unreliable and are employee personal data |
# | `fct_product_month` | **later** | wait until days past due has monthly history (snapshots), then promote with DPD as a true monthly measure |
# | `fct_category_month` | **no** | six categories carry a KPI at most; revisit with MCC codes |
#
#
# ## Findings and what they mean for the project

# %%
learnable = sig[sig.actionable & sig.kind.isin(["classification", "survival", "model", "count"])]
fc = sig[sig.kind.eq("forecast")]
display(
    Markdown(
        "\n".join(
            [
                (
                    "* **Predictive signal at the unit grains is exposure, not behaviour.** Of "
                    if exposure_law
                    else "* **Predictive signal at the unit grains.** Of "
                )
                + f"{int(sig.kind.isin(['classification', 'count', 'survival']).sum())} unit-level targets, the ones that "
                "survive false-discovery control and are material: "
                + (", ".join(f"{r.target} ({r.grain})" for r in learnable.itertuples()) or "none")
                + (
                    ". Customer dormancy and lapse follow the geometric law of products held (section 2); every "
                    if exposure_law
                    else ". Every "
                )
                + "behavioural target (contacts, complaints, digital adoption, conversion per send, delinquency, SLA "
                "breach) stays at chance at every grain. The generator draws each process independently, and no grain "
                "can join what was never linked.",
                f"* **The aggregate grains carry decisions with money attached.** {int(fc.verdict.str.startswith('forecastable').sum())} "
                f"of {len(fc)} day-grain series are forecastable beyond the weekly naive; cash loading (newsvendor), "
                "staffing (Erlang C), calendar-adjusted control charts, survival-based SLA reporting and campaign "
                "economics are deterministic services an agent can explain and an auditor can verify.",
                "* **The campaign grain is the one place where re-graining reveals a real, actionable difference**: "
                "campaigns differ in conversion beyond chance, channels exist that never convert, and launch attributes "
                f"rank campaigns ({verdict_of('campaign conversion from launch attributes')}).",
                "* **What must not be built**: an agent-coaching league table (no agent KPI is reliable), a roll-rate model "
                "(no delinquency history), contact or complaint triggers (no cross-process lead at any grain), and any "
                "dashboard reading an aggregate correlation as customer behaviour (the ecological fallacy, section 1).",
            ]
        )
    )
)

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
