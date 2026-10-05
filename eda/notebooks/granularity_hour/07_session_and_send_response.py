# %% [markdown]
# # 07 · The session and the send response
# **Granularity series III · the bank at the hour** · grains below the hour: the digital session (`agg.fct_session`,
# minutes) and the campaign send with its response milestones (`agg.fct_send_response`, hours)
#
# **Stakeholders.** Digital product (where in a session customers fail or buy), marketing technology (when to send so
# that customers open), the data office (whether the order of events can be trusted).
#
# **Questions.**
# 1. **The session funnel.** Sessions start and end with fixed events; between them, does one event type lead to
#    another (a Markov chain of transitions against independence)?
# 2. **Errors and purchases.** Sessions with an error look more likely to end in a purchase; is that the error, or the
#    session's length (the exposure effect of series I)?
# 3. **Send-time.** The delay from send to open, click and conversion, and whether the hour a message is sent changes
#    whether it is opened within 24 hours.
# 4. **Product × hour:** why it is not a grain.
# 5. **Models, executed** (`hour_models.session_send`): a session purchase classifier on sequence features against
#    session length only, and an open-within-24 h model with the send hour against the channel only.

# %%
import sys
import time
import warnings
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
from latam_eda import hour_models as hm

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])
star.build(["fct_session", "fct_send_response"], verbose=False)
s_tests, d_tests = [], []

# %% [markdown]
# ## 1 · The session funnel

# %%
edge = star.q("""select avg(starts_with_login::int) as login_first, avg(ends_with_logout::int) as logout_last,
                        count(*) as sessions, median(n_events) as median_events, median(session_seconds) as median_seconds
                 from {fct_session}""").iloc[0]
tr = star.q("""with e as (select session_id, event_type,
                    row_number() over (partition by session_id order by event_ts_utc, event_id) as k,
                    count(*) over (partition by session_id) as n,
                    lag(event_type) over (partition by session_id order by event_ts_utc, event_id) as prev
                  from {stg_digital_events})
               select prev, event_type as next, count(*) as n from e
               where k > 2 and k < n group by all order by all""")
tm = tr.pivot_table(index="prev", columns="next", values="n", fill_value=0)
chi = stats.chi2_contingency(tm.to_numpy())
v = float(np.sqrt(chi.statistic / (tm.to_numpy().sum() * (min(tm.shape) - 1))))
s_tests.append(
    {
        "scenario": "07 session and send",
        "test": "inner event transitions depart from independence (Cramér's V)",
        "statistic": chi.statistic,
        "p_value": chi.pvalue,
        "effect": v,
        "n": int(tm.to_numpy().sum()),
        "reading": "ordered funnel" if v >= 0.1 else "events in random order",
    }
)
fig = px.imshow(
    (100 * tm.div(tm.sum(axis=1), axis=0)).round(1),
    text_auto=True,
    aspect="auto",
    color_continuous_scale="Blues",
    title="Next event given the previous one, inside sessions (% of row)",
)
fig.update_layout(height=380)
fig.show()
display(
    Markdown(
        f"**{100 * edge.login_first:.1f} % of {int(edge.sessions):,} sessions start with Login and "
        f"{100 * edge.logout_last:.1f} % end with Logout; the median session has {edge.median_events:.0f} events over "
        f"{edge.median_seconds / 60:.1f} minutes.** Between those fixed edges, the next event barely depends on the "
        f"previous one (Cramér's V {v:.3f}): every row of the transition matrix is the same mix. A real clickstream is "
        "a funnel (a product page before a form, a form before a purchase, an error followed by a retry); here the "
        "inner events are drawn independently, so no step-level funnel or drop-off model can be learned."
    )
)

# %% [markdown]
# ## 2 · Errors and purchases: the error, or the length?

# %%
ss = star.q("""select has_error::int as has_error, has_purchase::int as has_purchase,
                      n_pageviews + n_clicks + n_forms + n_errors as length
               from {fct_session} where hash(session_id) % 6 = 0 order by session_id""")
naive = ss.groupby("has_error").has_purchase.mean()
fit = smf.logit("has_purchase ~ np.log1p(length) + has_error", data=ss).fit(disp=False)
adj_or, adj_p = float(np.exp(fit.params["has_error"])), float(fit.pvalues["has_error"])
s_tests.append(
    {
        "scenario": "07 session and send",
        "test": "an error changes purchase odds, given session length (logit)",
        "statistic": adj_or,
        "p_value": adj_p,
        "effect": float(fit.params["has_error"]),
        "n": len(ss),
        "reading": "error matters" if adj_p < 0.01 else "only length matters",
    }
)
display(
    Markdown(
        f"**Sessions with an error purchase {100 * naive[1]:.1f} % of the time against {100 * naive[0]:.1f} % without; "
        f"given the session's length the error's odds ratio is {adj_or:.2f} (p = {adj_p:.2g}).** "
        + (
            "The naive gap is the exposure effect: longer sessions hold more of every event, errors and purchases "
            "alike. An error-impact KPI must be computed per event of exposure, never per session."
            if adj_or < 1.05 or adj_p > 0.01
            else "Errors change purchase odds beyond length."
        )
    )
)

# %% [markdown]
# ## 3 · Send-time: delays and the hour of the send

# %%
sr = star.q("""select send_channel, send_hour_of_day, opened, hours_to_open, hours_to_click, hours_to_convert,
                      open_hour_of_day
               from {fct_send_response} where open_tracked and was_delivered""")
op = sr[sr.opened == 1]
cnt, edges = np.histogram(op.hours_to_open, bins=42, range=(0, 168))
fig = px.bar(
    x=(edges[:-1] + edges[1:]) / 2, y=cnt, title="Hours from send to open (tracked channels)"
)
fig.update_layout(height=300, xaxis_title="hours", yaxis_title="opens")
fig.show()
ks = stats.kstest(op.hours_to_open / op.hours_to_open.max(), "uniform")
d_tests.append(
    {
        "scenario": "07 session and send",
        "test": "send-to-open delay is uniform over the window (KS)",
        "statistic": ks.statistic,
        "p_value": ks.pvalue,
        "effect": ks.statistic,
        "n": len(op),
        "reading": "uniform delay" if ks.statistic < 0.02 else "shaped delay",
    }
)
u_open = g.uniform_hours_test(op.open_hour_of_day.value_counts().sort_index())
d_tests.append(
    {
        "scenario": "07 session and send",
        "test": "opens happen at a preferred hour of day",
        "statistic": u_open["chi2"],
        "p_value": u_open["p_value"],
        "effect": u_open["cohen_w"],
        "n": int(u_open["n"]),
        "reading": "flat" if u_open["cohen_w"] < 0.1 else "open-hour profile",
    }
)
sr["open24"] = ((sr.opened == 1) & (sr.hours_to_open <= 24)).astype(int)
t24 = sr.groupby("send_hour_of_day").open24.agg(["sum", "count"])
c24 = stats.chi2_contingency(np.column_stack([t24["sum"], t24["count"] - t24["sum"]]))
d_tests.append(
    {
        "scenario": "07 session and send",
        "test": "open within 24 h depends on the send hour",
        "statistic": c24.statistic,
        "p_value": c24.pvalue,
        "effect": float(np.sqrt(c24.statistic / t24["count"].sum())),
        "n": int(t24["count"].sum()),
        "reading": "send time matters" if c24.pvalue < 0.01 else "flat",
    }
)
dq = pd.DataFrame(
    {
        "hours to open": op.hours_to_open.quantile([0.1, 0.5, 0.9]),
        "hours to click": sr.hours_to_click.dropna().quantile([0.1, 0.5, 0.9]),
        "hours to convert": sr.hours_to_convert.dropna().quantile([0.1, 0.5, 0.9]),
    }
)
show(dq.round(1), paging=False)
display(
    Markdown(
        f"**Opens arrive evenly over {op.hours_to_open.max():.0f} hours after the send (KS distance from uniform "
        f"{ks.statistic:.3f}), at no preferred hour of day (Cohen's w {u_open['cohen_w']:.3f}), and the share opened "
        f"within 24 hours does not depend on the send hour (p = {c24.pvalue:.2f}).** Real opens are front-loaded (most "
        "in the first hours) and cluster in the evening and at lunch, which is what send-time optimisation exploits. "
        "Here the delay is a uniform draw, so the send hour cannot matter, and learning it would also need randomised "
        "send times (the observed send hour is chosen by the campaign, not assigned)."
    )
)

# %% [markdown]
# ## 4 · Product × hour
# A product (account, card, loan) has 0.0004 transactions per hour (notebook 01): 99.96 % of product-hours are empty.
# No decision about a product is taken per hour (pricing, limits, collections and portfolio monitoring are daily or
# monthly), so the product stays at the month grain of series I. The one intraday product question, card velocity, is
# a sequence question answered in series II (notebook 03): no bursts.

# %% [markdown]
# ## 5 · The models, executed

# %%
rows, detail = hm.session_send(star)
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
pd.DataFrame(s_tests).to_csv(OUT / "granularity_hour_session_funnel.csv", index=False)
pd.DataFrame(d_tests).to_csv(OUT / "granularity_hour_send_delay.csv", index=False)
display(
    Markdown(
        "**Readiness:** "
        + "; ".join(
            f"*{r['model']}* is **{r['verdict']}** ({r['root_cause'] or 'ready'})" for r in rows
        )
        + ". The session's composition adds "
        f"{rows[0]['delta']:.3f} AUC to its length (significant on {rows[0]['n_test']:,} sessions, not material), and "
        "the send hour adds nothing to the channel."
    )
)

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
