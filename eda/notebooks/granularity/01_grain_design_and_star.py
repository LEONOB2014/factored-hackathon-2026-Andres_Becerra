# %% [markdown]
# # 01 · Grain design and the aggregate star
# **Granularity series** · re-grain the platform and look for value at each grain
#
# Every earlier analysis worked at the grain the source delivers: one row per transaction, contact, event or send. At
# that grain only dormancy carried predictive signal (`docs/strategy/12_development_path.md`, ADR-012). But a bank
# rarely decides per transaction. A retention team acts on a **customer**, operations staff a **day**, treasury fills
# a **branch's** cash for a day, the contact centre schedules **agents**, risk reviews a **product** each month,
# marketing paces a **campaign**, and compliance tracks a **case** to its deadline. This series rebuilds the star
# schema at those grains and asks, grain by grain:
# 1. which business decision lives at this grain, and who owns it;
# 2. what the aggregate reveals that the atomic rows hid (and what it destroys);
# 3. whether any target at this grain is predictable, and whether a model, a rule or an agent should serve it;
# 4. what it would cost the pipelines downstream to promote the grain to the platform.
#
# | notebook | grain | decision |
# |---|---|---|
# | 01 | all | the bus matrix, the star, its tests |
# | 02 | customer × month | engagement, retention, cost to serve |
# | 03 | customer (lifetime) | value, attrition timing |
# | 04 | market × day, channel × day | capacity, liquidity, operational monitoring |
# | 05 | branch × day | cash logistics |
# | 06 | agent × day, complaint case | staffing, coaching, SLA compliance |
# | 07 | product × month | portfolio, vintage, credit early warning |
# | 08 | category × month, campaign × day | spend mix, campaign ROI, contact fatigue |
# | 09 | synthesis | which grain earns a model, an agent or a KPI |

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme
from latam_eda import granularity as g

OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl)

# %% [markdown]
# ## 1 · The bus matrix: business processes × conformed dimensions
# Kimball's bus matrix lists each business process (a fact) against the dimensions it can be sliced by. A dimension
# shared by several processes is **conformed**: the same keys and the same meaning everywhere, which is what lets a
# number from the contact centre sit next to a number from payments on one report. The matrix below is the design of
# this experiment; ✚ marks the dimensions created for it.

# %%
DIMS = [
    "date / local day ✚",
    "month ✚",
    "market",
    "customer",
    "behaviour band ✚",
    "channel ✚",
    "branch",
    "agent",
    "product",
    "merchant category",
    "campaign",
    "case type ✚",
]
BUS = {
    "fct_customer_month": [
        "month ✚",
        "market",
        "customer",
        "behaviour band ✚",
    ],
    "fct_customer_snapshot": ["market", "customer"],
    "fct_country_day": ["date / local day ✚", "market"],
    "fct_channel_day": ["date / local day ✚", "market", "channel ✚"],
    "fct_branch_day": ["date / local day ✚", "market", "branch"],
    "fct_agent_day": ["date / local day ✚", "agent"],
    "fct_product_month": ["month ✚", "customer", "product"],
    "fct_category_month": ["month ✚", "market", "merchant category"],
    "fct_campaign_day": ["date / local day ✚", "campaign"],
    "fct_case": ["date / local day ✚", "market", "customer", "case type ✚"],
}
bus = pd.DataFrame(
    [{d: ("●" if d in dims else "") for d in DIMS} for dims in BUS.values()], index=list(BUS)
)
show(bus, paging=False)

# %% [markdown]
# ## 2 · The star, grain by grain
# ```mermaid
# erDiagram
#   dim_customer ||--o{ fct_customer_month : customer_id
#   dim_month ||--o{ fct_customer_month : month_start
#   dim_customer_band ||--o{ fct_customer_month : band_key
#   dim_customer ||--|| fct_customer_snapshot : customer_id
#   dim_data_day ||--o{ fct_country_day : "country_code, local_date"
#   dim_data_day ||--o{ fct_channel_day : "country_code, local_date"
#   dim_channel ||--o{ fct_channel_day : channel
#   dim_branch ||--o{ fct_branch_day : branch_id
#   dim_data_day ||--o{ fct_branch_day : local_date
#   dim_agent ||--o{ fct_agent_day : agent_id
#   dim_product ||--o{ fct_product_month : product_id
#   dim_month ||--o{ fct_product_month : month_start
#   dim_merchant_category ||--o{ fct_category_month : category
#   dim_campaign ||--o{ fct_campaign_day : campaign_id
#   dim_case_type ||--o{ fct_case : case_type_key
#   dim_customer ||--o{ fct_case : customer_id
# ```
#
# **Design decisions, and why.**
# * **Periodic snapshots, dense where time matters.** A customer-month with no transaction is a row of zeros, not a
#   missing row: rolling windows ("transactions in the last 6 months"), inactivity labels and averages over customers
#   all need the zeros. The cost is size (150,000 customers × 36 months = 5.4 M rows, most of them quiet), paid once in
#   storage instead of in every query that would otherwise rebuild the grid.
# * **Accumulating snapshots for things with a lifecycle.** A complaint case moves through milestones; one row per
#   case with one column per milestone answers "how long until …" directly, and marks the cases still open, which
#   must be treated as **censored** (notebook 06).
# * **A mini-dimension for fast-changing behaviour.** Activity, value, digital and service tiers change every month;
#   versioning them in the SCD2 customer dimension would multiply its rows by 36. The behaviour band is a separate
#   96-row dimension keyed from the monthly fact (Kimball's mini-dimension).
# * **Local days for operations, UTC for agents.** A customer's day is local to the customer's market (holidays,
#   paydays, the evening rush); an agent works one contact-centre shift whatever the customer's market.
# * **Additive measures only.** Every measure is a count or a sum. Rates (resolution rate, average sentiment, NPS) are
#   stored as numerator and denominator and derived at query time as a **ratio of sums**: the mean of daily rates
#   weights a quiet day like a busy one and is wrong for any roll-up.
# * **Current-state attributes stay attributes.** Balance, limit and days past due exist only as today's snapshot; they
#   are attached to the product, never stored as monthly measures that would look like history.

# %%
models = pd.DataFrame(
    [
        {"model": m.name, "grain": ", ".join(m.grain), "description": m.doc[:220]}
        for m in star.models.values()
    ]
)
show(models, paging=False)

# %% [markdown]
# ## 3 · Build, and the three tests every aggregate must pass
# * **Grain uniqueness:** exactly one row per declared key. A duplicated key double-counts every measure.
# * **Additive reconciliation:** each additive measure, summed per month (or in total), equals the same aggregate
#   computed on the atomic fact. An aggregate that loses or invents rows is caught here, which is the test the
#   pipeline walkthrough found missing (19 % of transactions silently losing their keys passed 107 green tests).
# * **Dense completeness:** every cell of the declared cross product exists.

# %%
built = star.build(verbose=False)
show(built, paging=False)
checks = star.check()
checks.to_csv(OUT / "granularity_build_checks.csv", index=False)
show(checks, paging=False)
fails = checks[~checks.ok]
display(
    Markdown(
        f"**{len(checks)} checks on {len(built)} models: {int(checks.ok.sum())} pass, {len(fails)} fail.** "
        + (
            "Every grain is unique, every additive measure reconciles exactly to its atomic fact and every dense "
            "grid is complete: the aggregate star loses nothing the atomic star holds."
            if not len(fails)
            else "Failures: "
            + "; ".join(f"{r.model} {r.check} ({r.detail})" for r in fails.itertuples())
        )
    )
)

# %% [markdown]
# ## 4 · What aggregation does to the data: zeros, dispersion and information
# Two properties of each grain decide which statistics are valid on it:
# * **Zero inflation:** the share of rows with no activity. A grain that is mostly zeros needs models for counts with
#   excess zeros (hurdle or zero-inflated), and its averages are dominated by the quiet rows.
# * **Overdispersion:** the variance-to-mean ratio of the main count. A Poisson process has ratio 1; above 1, the counts
#   vary more than chance between units (heterogeneous customers, branches or days), and a negative binomial model or
#   a unit effect is needed. Overdispersion at a grain is also its **opportunity**: it is variation between units that
#   a model or a decision can exploit.

# %%
PROFILE = [
    ("fct_customer_month", "customer × month", "n_tx"),
    ("fct_customer_month", "customer × month", "contacts"),
    ("fct_customer_month", "customer × month", "sessions"),
    ("fct_customer_month", "customer × month", "complaints_opened"),
    ("fct_product_month", "product × month", "n_tx"),
    ("fct_country_day", "market × day", "n_tx"),
    ("fct_country_day", "market × day", "contacts"),
    ("fct_country_day", "market × day", "complaints_opened"),
    ("fct_channel_day", "channel × day", "n_tx"),
    ("fct_branch_day", "branch × day", "n_withdrawals"),
    ("fct_agent_day", "agent × day", "contacts"),
    ("fct_campaign_day", "campaign × day", "sends"),
]
rows = []
for fact, grain, m in PROFILE:
    r = star.q(f"""select count(*) as n_rows, avg(({m} = 0)::int) as zero_share,
                          avg({m}) as mean, var_samp({m}) as variance from {{{fact}}}""").iloc[0]
    rows.append(
        {
            "grain": grain,
            "measure": m,
            "rows": int(r.n_rows),
            "zero share %": round(100 * r.zero_share, 1),
            "mean": round(r["mean"], 3),
            "variance / mean": round(r.variance / r["mean"], 2) if r["mean"] else np.nan,
        }
    )
prof = pd.DataFrame(rows)
show(prof, paging=False)
fig = px.scatter(
    prof,
    x="zero share %",
    y="variance / mean",
    text=prof.grain + " · " + prof.measure,
    log_y=True,
    title="Each grain's main counts: zero inflation against overdispersion",
)
fig.add_hline(y=1, line_dash="dot", annotation_text="Poisson (variance = mean)")
fig.update_traces(textposition="top center")
fig.update_layout(height=520)
fig.show()
over = prof[prof["variance / mean"] > 1.5]
zeroy = prof[prof["zero share %"] > 50]
display(
    Markdown(
        f"**{len(zeroy)} of {len(prof)} measures are zero in more than half of their rows** "
        f"({', '.join(zeroy.grain + ' ' + zeroy.measure)}), and **{len(over)} are overdispersed** (variance above 1.5 × "
        "the mean). "
        + (
            f"The zero-heavy grains are {', '.join(sorted(set(zeroy.grain)))}: most units do nothing in most periods. "
            if len(zeroy)
            else ""
        )
        + "The market-day counts have no zeros (zero share "
        + f"{prof.loc[prof.grain == 'market × day', 'zero share %'].max():.1f} %) and are large, so their relative "
        "noise is small: the grain where forecasting can work if any structure exists (notebook 04)."
    )
)

# %% [markdown]
# ## 5 · The information trade-off of aggregation
# Aggregating removes noise (a month of transactions is a steadier signal of a customer's activity than any single
# transaction) and removes information (the order and timing of events inside the month). Two consequences frame the
# rest of the series:
# * **The ecological fallacy:** a relationship between two measures at an aggregate grain (market-days with more
#   digital errors have more contacts) need not hold for the units inside it (the customers with errors are not
#   necessarily the ones who call). Notebook 09 measures it.
# * **Timing inside the window:** a label built at the month grain ("dormant next month") cannot use what happens
#   inside the month it predicts, and features computed over a month must end before the target month starts. Every
#   model in the series respects that boundary.
#
# ## Findings and what to do
# The computed statements above. The design (dense periodic snapshots, accumulating snapshots for lifecycles, a
# behaviour mini-dimension, additive measures, rates as ratios of sums, snapshot attributes kept as attributes) is the
# proposal for `platform/dbt/models/gold/aggregates`; its three test families are the tests that should come with it.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
