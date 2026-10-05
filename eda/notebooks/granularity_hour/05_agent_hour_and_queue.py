# %% [markdown]
# # 05 · The agent hour and the queue
# **Granularity series III · the bank at the hour** · grains: agent × hour (`agg.fct_agent_hour`, joined to the shift
# bridge `agg.dim_agent_shift`) and market × contact channel × hour (`agg.fct_contact_queue_hour`)
#
# **Stakeholders.** The contact-centre director and workforce management (rosters, shift adherence, occupancy), HR
# (working-time compliance), service quality (waiting time per hour).
#
# **Questions.**
# 1. **Shift adherence.** Each agent has a declared `work_shift`. If agents worked their shifts, a Morning agent's
#    contacts would fall in the morning hours; if the shift label were unrelated to the work, each shift would hold
#    its share of the day (8 of 24 hours for Morning, Afternoon, Night).
# 2. **The working day of an agent.** How many distinct hours does an agent handle contacts in, per day, against an
#    8-hour shift?
# 3. **Occupancy per agent-hour** (handle time / 3,600 s) and the queue: Erlang C agents required per hour of the week
#    against the agents actually active.
# 4. **Models, executed** (`hour_models.agent`): handle time per agent-hour from shift, hour, load and agent attributes
#    against the agent's own mean, and hourly contact arrivals per queue against the weekday mean spread flat.

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
from latam_eda import hour_models as hm

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])
star.build(["fct_agent_hour", "fct_contact_queue_hour"], verbose=False)
ah = star.q("select * from {fct_agent_hour} order by agent_id, hour_start")
tests = []

# %% [markdown]
# ## 1 · Shift adherence

# %%
sh = ah.groupby("work_shift").agg(contacts=("contacts", "sum"), in_shift=("contacts", lambda x: 0))
sh["in_shift"] = ah[ah.in_shift].groupby("work_shift").contacts.sum()
cover = star.q(
    "select work_shift, avg(in_shift::int) as share_of_day from {dim_agent_shift} group by 1"
)
sh = sh.join(cover.set_index("work_shift"))
sh["in-shift %"] = 100 * sh.in_shift / sh.contacts
for ws, r in sh.iterrows():
    if r.share_of_day >= 1:
        continue
    bt = stats.binomtest(int(r.in_shift), int(r.contacts), r.share_of_day)
    tests.append(
        {
            "scenario": "05 agent and queue",
            "test": f"{ws} agents: contacts inside their shift vs the shift's share of the day",
            "statistic": r.in_shift / r.contacts,
            "p_value": bt.pvalue,
            "effect": r.in_shift / r.contacts - r.share_of_day,
            "n": int(r.contacts),
            "reading": "shifts are worked"
            if r.in_shift / r.contacts > 0.9
            else "shift label unrelated to the work",
        }
    )
show(sh.round(3), paging=False)
prof = ah.groupby(["work_shift", "contact_hour_of_day"]).contacts.sum().unstack(0)
fig = px.line(
    (100 * prof / prof.sum()).reset_index().melt(id_vars="contact_hour_of_day"),
    x="contact_hour_of_day",
    y="value",
    color="work_shift",
    title="Share of each shift's contacts by hour of the contact day (a worked shift would be a block of 8 hours)",
)
fig.update_layout(height=320, yaxis_title="% of the shift's contacts", yaxis_range=[0, 15])
fig.show()
mor = sh.loc["Morning"]
display(
    Markdown(
        f"**Morning agents handle {mor['in-shift %']:.1f} % of their contacts inside the morning shift, the shift's "
        f"share of the day is {100 * mor.share_of_day:.1f} %; Afternoon and Night agents likewise.** The shift label "
        "has no relation to when an agent works: every agent takes contacts in every hour. Occupancy, adherence and "
        "roster planning cannot be measured from this data; a workforce system's rostered hours and agent state logs "
        "are a prerequisite (notebook 08)."
    )
)

# %% [markdown]
# ## 2 · The working day of an agent

# %%
wd = ah.groupby(["agent_id", "contact_day"]).agg(
    hours=("hour_start", "nunique"), contacts=("contacts", "sum")
)
q = wd.hours.quantile([0.1, 0.5, 0.9])
span = (
    ah.groupby(["agent_id", "contact_day"])
    .contact_hour_of_day.agg(lambda x: x.max() - x.min() + 1)
    .rename("span")
)
n_agents = star.q("select count(*) from {dim_agent}").iloc[0, 0]
n_days = ah.contact_day.nunique()
per_agent_day = ah.contacts.sum() / (n_agents * n_days)
display(
    Markdown(
        f"**{n_agents:,} agents share {ah.contacts.sum() / n_days:,.0f} contacts a day: {per_agent_day:.2f} contacts "
        f"per agent per day.** On a day an agent works at all, the median is {wd.contacts.median():.0f} contact in "
        f"{q[0.5]:.0f} hour (p90 {q[0.9]:.0f} hours). The contact log describes a workforce sized for many times its "
        "volume, or contacts assigned to agents at random: either way, the agent-hour cannot measure productivity, "
        "occupancy or adherence, and an 8-hour working day is invisible in it."
    )
)

# %% [markdown]
# ## 3 · Occupancy and the queue

# %%
occ = g.occupancy(ah.handle_seconds)
cnt, edges = np.histogram(occ, bins=20, range=(0, 1))
fig = px.bar(
    x=(edges[:-1] + edges[1:]) / 2,
    y=cnt,
    title="Occupancy per agent-hour with at least one contact",
)
fig.update_layout(height=280, xaxis_title="handle time / 3,600 s", yaxis_title="agent-hours")
fig.show()
qh = star.q("""select contact_weekday, contact_hour_of_day, sum(inbound) as inbound, sum(arrivals) as arrivals,
                      sum(handle_seconds) as handle_seconds, count(distinct contact_day) as days
               from {fct_contact_queue_hour} group by all order by all""")
aht = float(qh.handle_seconds.sum() / qh.arrivals.sum())
qh["per_hour"] = qh.inbound / qh.days
qh["agents_required"] = [g.agents_needed(v, aht, 20, 0.8) for v in qh.per_hour]
act = (
    ah.assign(contact_weekday=pd.to_datetime(ah.contact_day).dt.dayofweek + 1)
    .groupby(["contact_weekday", "contact_hour_of_day", "contact_day"])
    .agent_id.nunique()
    .groupby(["contact_weekday", "contact_hour_of_day"])
    .mean()
    .rename("agents_active")
)
qh = qh.join(act, on=["contact_weekday", "contact_hour_of_day"])
rho, p_rho = stats.spearmanr(qh.agents_required, qh.agents_active)
tests.append(
    {
        "scenario": "05 agent and queue",
        "test": "active agents follow the Erlang requirement across hours of the week (Spearman)",
        "statistic": rho,
        "p_value": p_rho,
        "effect": rho,
        "n": len(qh),
        "reading": "mechanical: an agent is active only when given a contact",
    }
)
display(
    Markdown(
        f"**Median occupancy of an active agent-hour is {100 * np.median(occ):.0f} %; Erlang C (80 % in 20 s, handle "
        f"time {aht / 60:.1f} min) needs {qh.agents_required.min()}–{qh.agents_required.max()} agents per hour of the "
        f"week, and {qh.agents_active.min():.0f}–{qh.agents_active.max():.0f} agents are active (Spearman "
        f"{rho:.2f}, p = {p_rho:.2g}).** "
        + "The correlation is mechanical: an agent counts as active only when given a contact, and with about one "
        "contact per active agent-hour the number of active agents is the number of contacts. The comparison a "
        "contact centre runs (required against rostered against logged-in agents per interval) needs the rostered "
        "and logged-in hours this data does not have."
    )
)

# %% [markdown]
# ## 4 · The models, executed

# %%
rows, detail = hm.agent(star)
show(detail["variants"].round(4), paging=False)
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
pd.DataFrame(tests).to_csv(OUT / "granularity_hour_agent_shift.csv", index=False)
display(
    Markdown(
        "**Readiness:** "
        + "; ".join(
            f"*{r['model']}* is **{r['verdict']}** ({r['root_cause'] or 'ready'})" for r in rows
        )
        + ". Handle time is not explained by shift, hour, load or experience beyond each agent's own mean (a gain of "
        f"{100 * rows[0]['delta']:.2f} % of the error, real but immaterial), and hourly arrivals are no more "
        "forecastable than the weekday mean spread flat."
    )
)

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
