# %% [markdown]
# # 06 · The case clock
# **Granularity series III · the bank at the hour** · grain: complaint case with hour milestones (`agg.fct_case_clock`)
#
# **Stakeholders.** Complaints management and compliance (regulators count response deadlines in business days:
# CONDUSEF in Mexico, the Superintendencia Financiera in Colombia, BCRA in Argentina), customer experience (time to a
# first answer), internal audit (is the SLA flag the bank reports consistent with the clock?).
#
# **Questions.**
# 1. **The milestones in hours:** created → assigned → first response → resolved, with right-censoring for cases still
#    open (Kaplan–Meier, never an average of the closed cases only).
# 2. **Business hours:** the same durations on the regulators' clock (Monday to Friday, 09:00–18:00 on the complaint
#    delivery clock, each country's holidays excluded, `granularity.business_hours_between`).
# 3. **Does the SLA flag agree with the clock?** Each case is re-judged against its country's deadline in business days
#    (Mexico 30, Colombia 15, Argentina 10; to be confirmed by compliance) and compared with `sla_breached`
#    (Cohen's κ: 1 = the same verdict, 0 = no better than chance).
# 4. **Does the hour or weekday a case arrives change how fast it is answered?**
# 5. **Models, executed** (`hour_models.case_clock`): a Cox model of time to first response, and an SLA-breach classifier
#    at creation.

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
from lifelines import KaplanMeierFitter
from lifelines.statistics import multivariate_logrank_test
from scipy import stats
from sklearn.metrics import cohen_kappa_score

from latam_eda import country, theme
from latam_eda import granularity as g
from latam_eda import hour_models as hm

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])
star.build(["fct_case_clock"], verbose=False)
c = star.q("select * from {fct_case_clock} order by created_clock, complaint_id")
DEADLINE_BD = {"MX": 30, "CO": 15, "AR": 10}
tests = []

# %% [markdown]
# ## 1 · The milestones, censoring respected

# %%
grid = np.arange(0, 24 * 60 + 1, 6)
curves = []
for name, T, E in [
    ("first response", c.hours_observed_response, c.responded_event),
    ("resolution", c.hours_observed_resolve, c.resolved_event),
]:
    ok = T > 0
    km = KaplanMeierFitter().fit(T[ok], E[ok].astype(int))
    curves.append(
        pd.DataFrame(
            {
                "hours": grid,
                "still waiting": km.survival_function_at_times(grid).to_numpy(),
                "milestone": name,
            }
        )
    )
    curves[-1]["median"] = km.median_survival_time_
fig = px.line(
    pd.concat(curves),
    x="hours",
    y="still waiting",
    color="milestone",
    title="Share of complaints still waiting for each milestone (Kaplan–Meier, censored cases kept)",
)
fig.update_layout(height=320, xaxis_title="elapsed hours since creation")
fig.show()
qa = c.hours_to_assign.quantile([0.1, 0.5, 0.9])
med_fr, med_res = curves[0]["median"].iloc[0], curves[1]["median"].iloc[0]
display(
    Markdown(
        f"**Assignment takes {qa[0.5]:.0f} hours at the median (p10 {qa[0.1]:.0f}, p90 {qa[0.9]:.0f}); half the cases "
        f"have a first response within {med_fr:.0f} hours, and "
        + (
            f"half are resolved within {med_res:.0f} hours** "
            if np.isfinite(med_res)
            else "fewer than half are ever resolved within the data, so the median time to resolution is not reached** "
        )
        + f"({100 * c.responded_event.mean():.0f} % of cases have a first response at all, "
        f"{100 * c.resolved_event.mean():.0f} % are resolved). A plain average of the resolved cases would describe the "
        "fast minority; Kaplan–Meier keeps the open ones. These are elapsed hours; the regulators count business days."
    )
)

# %% [markdown]
# ## 2 · Business hours and the regulatory deadline

# %%
cal = pd.concat(
    [
        country.calendar(cc, "2023-01-01", "2026-12-31").assign(country_code=cc)
        for cc in country.COUNTRIES
    ]
)
hol = {cc: set(d.local_date[d.is_holiday]) for cc, d in cal.groupby("country_code")}
data_end = c.created_clock.max()
c["bh_first_response"] = np.nan
c["bh_resolve"] = np.nan
c["bh_observed"] = np.nan
for cc, idx in c.groupby("country_code").groups.items():
    d = c.loc[idx]
    c.loc[idx, "bh_first_response"] = g.business_hours_between(
        d.created_clock, d.first_response_clock, hol[cc]
    )
    c.loc[idx, "bh_resolve"] = g.business_hours_between(d.created_clock, d.resolved_clock, hol[cc])
    c.loc[idx, "bh_observed"] = g.business_hours_between(
        d.created_clock, d.resolved_clock.fillna(data_end), hol[cc]
    )
c["deadline_bh"] = c.country_code.map(DEADLINE_BD) * 9
c["breach_clock"] = c.bh_observed > c.deadline_bh
known = c[c.resolved_event | c.breach_clock]  # cases whose verdict is known at the end of the data
rows = []
for cc, d in known.groupby("country_code"):
    flag = d.sla_breached.fillna(False).astype(bool)
    k = cohen_kappa_score(flag, d.breach_clock)
    agree = float((flag == d.breach_clock).mean())
    rows.append(
        {
            "country": cc,
            "deadline (business days)": DEADLINE_BD[cc],
            "cases judged": len(d),
            "breached by the flag %": 100 * flag.mean(),
            "breached by the clock %": 100 * d.breach_clock.mean(),
            "agreement %": 100 * agree,
            "kappa": k,
            "median business hours to first response": d.bh_first_response.median(),
        }
    )
    tests.append(
        {
            "scenario": "06 case clock",
            "test": f"{cc}: SLA flag agrees with the regulatory clock (κ)",
            "statistic": k,
            "p_value": stats.binomtest(int((flag == d.breach_clock).sum()), len(d), 0.5).pvalue,
            "effect": k,
            "n": len(d),
            "reading": "consistent" if k > 0.9 else "the flag does not follow the clock",
        }
    )
sla = pd.DataFrame(rows)
show(sla.round(3), paging=False)
display(
    Markdown(
        f"**The bank's SLA flag and the regulatory clock agree with Cohen's κ between {sla.kappa.min():.2f} "
        f"and {sla.kappa.max():.2f}** (1 = the same verdict, 0 = chance). "
        + (
            "The flag is not computed from the case's own timestamps and deadline: it cannot be reported to a "
            "regulator, and a breach KPI must be recomputed from the clock (deadline seed per case type and country, "
            "business-hours calendar)."
            if sla.kappa.max() < 0.5
            else "The flag broadly follows the clock."
        )
    )
)

# %% [markdown]
# ## 3 · Does arrival time change the wait?

# %%
resp = c[c.responded_event & (c.hours_to_first_response >= 0)]
kw_h = stats.kruskal(*[d.hours_to_first_response for _, d in resp.groupby("created_hour_of_day")])
kw_w = stats.kruskal(*[d.hours_to_first_response for _, d in resp.groupby("created_weekday")])
lr = multivariate_logrank_test(
    c.hours_observed_response.clip(lower=1e-3),
    c.priority.fillna("?"),
    c.responded_event.astype(int),
)
for name, r in [("created hour of day", kw_h), ("created weekday", kw_w)]:
    tests.append(
        {
            "scenario": "06 case clock",
            "test": f"elapsed hours to first response by {name} (Kruskal–Wallis)",
            "statistic": r.statistic,
            "p_value": r.pvalue,
            "effect": r.statistic / (len(resp) - 1),
            "n": len(resp),
            "reading": "arrival time matters" if r.pvalue < 0.01 else "no effect",
        }
    )
tests.append(
    {
        "scenario": "06 case clock",
        "test": "time to first response by priority (log-rank)",
        "statistic": lr.test_statistic,
        "p_value": lr.p_value,
        "effect": np.nan,
        "n": len(c),
        "reading": "priority matters"
        if lr.p_value < 0.01
        else "priority does not speed the answer",
    }
)
bh_by_w = resp.groupby("created_weekday").bh_first_response.median()
display(
    Markdown(
        f"**Elapsed hours to a first response do not depend on the hour (p = {kw_h.pvalue:.2f}) or weekday "
        f"(p = {kw_w.pvalue:.2f}) a case arrives, nor on its priority (log-rank p = {lr.p_value:.2f}).** On the "
        f"business clock, cases created on a Friday wait {bh_by_w.get(5, np.nan):.0f} business hours at the median "
        f"against {bh_by_w.get(2, np.nan):.0f} for a Tuesday: the regulatory clock stops at weekends while the "
        "simulated work does not. A real complaints desk works business hours, prioritises, and answers Friday "
        "evening cases on Monday; here the response is a random delay."
    )
)

# %% [markdown]
# ## 4 · The models, executed

# %%
rows, detail = hm.case_clock(star)
sc = pd.DataFrame(rows)
show(
    sc[
        [
            "model",
            "metric",
            "value",
            "benchmark",
            "benchmark_value",
            "delta",
            "delta_lo",
            "delta_hi",
            "mde",
            "verdict",
            "root_cause",
        ]
    ].round(4),
    paging=False,
)
pd.DataFrame(tests).to_csv(OUT / "granularity_hour_case_clock.csv", index=False)
display(
    Markdown(
        "**Readiness:** "
        + "; ".join(
            f"*{r['model']}* is **{r['verdict']}** ({r['root_cause'] or 'ready'})" for r in rows
        )
        + ". Nothing known when a complaint arrives (type, category, priority, channel, country, hour) predicts when it "
        "will be answered or whether it will breach. The case clock is still the most useful hour-grain product: the "
        "**regulatory deadline KPI** is deterministic (a calendar and a seed, no model), and it is what the bank must "
        "report."
    )
)

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
