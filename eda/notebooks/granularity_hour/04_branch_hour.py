# %% [markdown]
# # 04 · The branch hour
# **Granularity series III · the bank at the hour** · grain: branch × hour (`agg.fct_branch_hour`), read against the
# coverage dimension `agg.dim_branch_schedule` (branch × weekday × hour → open fraction)
#
# **Stakeholders.** Branch network operations (opening hours, teller staffing), cash logistics (ATM replenishment),
# internal audit and fraud (activity at a teller window when the branch is closed is either a data error or an
# operational risk event).
#
# **Questions.**
# 1. **Do teller transactions respect the branch's opening hours?** Each branch declares `opening_time` and
#    `closing_time`. If teller activity followed the schedule, almost every Branch-channel transaction would fall in an
#    open hour. If it ignored the schedule, the share in closed hours would equal the share of the week the branch is
#    closed. Both readings of the schedule are tested: Monday to Friday (assumed: the source gives no opening days) and
#    every day.
# 2. **ATMs at the hour:** ATMs legitimately work around the clock; is intraday ATM cash a usable grain for
#    replenishment, or is the day the decision grain?
# 3. **Models, executed** (`hour_models.branch`): a classifier of "teller transaction outside opening hours" from the
#    transaction's attributes, and a branch-hour ATM cash forecaster that splits the day by the branch's own hourly
#    profile, against a flat split.

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
star.build(["fct_branch_hour", "dim_branch_schedule"], verbose=False)
tests = []

# %% [markdown]
# ## 1 · Teller transactions against the schedule

# %%
bh = star.q("""select f.branch_id, b.branch_type, f.n_teller, f.n_atm, f.open_fraction, f.open_fraction_any_day,
                      f.hour_of_day, f.delivery_weekday
               from {fct_branch_hour} f join {stg_branches} b using (branch_id) order by f.branch_id, f.hour_start""")
sched = star.q("""select branch_id, avg((open_fraction > 0)::int) as open_share,
                         avg((open_fraction_any_day > 0)::int) as open_share_any_day
                  from {dim_branch_schedule} group by 1 order by 1""")
br = (
    bh.assign(
        out_wk=bh.n_teller * (bh.open_fraction == 0),
        out_any=bh.n_teller * (bh.open_fraction_any_day == 0),
    )
    .groupby(["branch_id", "branch_type"])[["n_teller", "out_wk", "out_any"]]
    .sum()
    .reset_index()
    .merge(sched, on="branch_id")
)
br = br[br.n_teller > 0]
for reading, out_col, share_col in [
    ("Monday to Friday", "out_wk", "open_share"),
    ("every day", "out_any", "open_share_any_day"),
]:
    for bt, d in [("all branches", br), *sorted(br.groupby("branch_type"))]:
        n, k = int(d.n_teller.sum()), int(d[out_col].sum())
        exp = float(np.average(1 - d[share_col], weights=d.n_teller))
        r = stats.binomtest(k, n, exp)
        tests.append(
            {
                "scenario": "04 branch",
                "test": f"teller outside hours ({reading}), {bt}: observed vs schedule-blind",
                "statistic": k / n,
                "p_value": r.pvalue,
                "effect": k / n - exp,
                "n": n,
                "reading": f"expected {100 * exp:.1f} % if hours were ignored; observed {100 * k / n:.1f} %",
            }
        )
tt = pd.DataFrame(tests)
show(tt.round(5), paging=False)
# per-branch z on the every-day reading (the one that does not mix in the weekend volume dip)
zb = (br.out_any / br.n_teller - (1 - br.open_share_any_day)) / np.sqrt(
    (1 - br.open_share_any_day) * br.open_share_any_day / br.n_teller
)
cnt, edges = np.histogram(zb.clip(-5, 5), bins=40)
fig = px.bar(
    x=(edges[:-1] + edges[1:]) / 2,
    y=cnt,
    title="Per-branch z-score: observed closed-hour teller share minus the schedule-blind expectation (every day)",
)
fig.update_layout(
    height=300, xaxis_title="z (0 = activity ignores the schedule)", yaxis_title="branches"
)
fig.show()
anyd = tt[tt.test.str.contains("every day") & tt.test.str.contains("all branches")].iloc[0]
wk = tt.iloc[0]
display(
    Markdown(
        f"**{100 * anyd.statistic:.1f} % of {int(anyd.n):,} teller transactions happen outside the branch's hours; "
        f"activity that ignored the schedule would put {100 * (anyd.statistic - anyd.effect):.1f} % there "
        f"(binomial p = {anyd.p_value:.2f}), and per branch the z-scores centre on {np.median(zb):.2f} with spread "
        f"{np.std(zb):.2f} (1 under pure noise).** **Teller activity ignores opening hours.** Read with Monday to "
        f"Friday opening days, {100 * wk.statistic:.1f} % fall in closed hours against {100 * (wk.statistic - wk.effect):.1f} % "
        "expected: the small gap is the 39 % quieter weekend (weekend hours are all 'closed' in that reading and carry "
        "less volume), not schedule-following. On real data this is a control the bank needs (a teller transaction at "
        "3 a.m. is a data error, a back-office posting mislabelled as a teller channel, or an operational risk event), "
        "and only the hour grain can run it. Proposed integrity rule: *teller transaction outside the declared "
        "schedule*, severity B, expected rate near 0 on real data."
    )
)

# %% [markdown]
# ## 2 · ATMs at the hour

# %%
atm = bh[bh.n_atm > 0]
n_br = star.q("select count(*) from {stg_branches} where has_atms").iloc[0, 0]
hours = star.q("select count(*) from {dim_hour}").iloc[0, 0]
hp = atm.groupby("hour_of_day").n_atm.sum()
u = g.uniform_hours_test(hp)
tests.append(
    {
        "scenario": "04 branch",
        "test": "ATM transactions: flat hours",
        "statistic": u["chi2"],
        "p_value": u["p_value"],
        "effect": u["cohen_w"],
        "n": int(u["n"]),
        "reading": "flat" if u["cohen_w"] < 0.1 else "intraday profile",
    }
)
display(
    Markdown(
        f"**ATM activity occupies {100 * len(atm) / (n_br * hours):.1f} % of branch-hours with an ATM, "
        f"{atm.n_atm.mean():.2f} transactions per occupied hour, and is flat over the day (Cohen's w {u['cohen_w']:.3f}).** "
        "An intraday replenishment decision (when in the day the truck comes) needs an intraday withdrawal profile and "
        "terminal-level dispense events; here the day remains the replenishment grain (series I, notebook 05)."
    )
)

# %% [markdown]
# ## 3 · The models, executed

# %%
rows, detail = hm.branch(star)
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
pd.DataFrame(tests).to_csv(OUT / "granularity_hour_branch_hours.csv", index=False)
display(
    Markdown(
        "**Readiness:** "
        + "; ".join(
            f"*{r['model']}* is **{r['verdict']}** ({r['root_cause'] or 'ready'})" for r in rows
        )
        + ". Nothing about a teller transaction (amount, type, customer, branch type) tells whether it fell in a closed "
        "hour: the out-of-hours activity is not a population that can be profiled but a defect of the schedule data "
        "or of the generator. The branch's own hourly ATM profile splits the day no better than a flat split."
    )
)

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
