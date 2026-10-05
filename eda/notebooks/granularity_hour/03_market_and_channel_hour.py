# %% [markdown]
# # 03 · Market and channel at the hour
# **Granularity series III · the bank at the hour** · grain: market × transaction channel × hour (`agg.fct_channel_hour`,
# dense)
#
# **Stakeholders.** Channel owners (ATM network, cards and POS, app and web, branches): capacity per hour, maintenance
# windows, intraday incident detection; operations (is this hour normal for this channel?).
#
# **Questions.**
# 1. **Does any channel have an intraday profile?** A uniform-hours χ² per market × channel, with Cohen's w as the effect
#    size (it does not grow with volume; w < 0.1 is a small effect).
# 2. **Does the decline rate depend on the hour?** Per channel, a χ² of declines against approvals over the 24 hours.
# 3. **Hourly monitors per channel:** Poisson and negative-binomial limits (series II, notebook 02), now per channel.
# 4. **Models, executed** (`hour_models.channel`): an hourly forecast per market × channel (Poisson GLM on hour-of-week,
#    boosting with weekly lags) against the weekday's mean day spread flat, the same information without the hour.

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
star.build(["fct_channel_hour"], verbose=False)
ch = star.q("""select * from {fct_channel_hour}
               where delivery_day > (select min(delivery_day) from {dim_hour})
                 and delivery_day < (select max(delivery_day) from {dim_hour})
               order by country_code, channel, hour_start""")
tests = []

# %% [markdown]
# ## 1 · The intraday profile per channel

# %%
prof = ch.groupby(["channel", "hour_of_day"]).n_tx.sum().unstack(0)
idx = 100 * prof / prof.mean()
fig = px.imshow(
    idx.T.round(1),
    aspect="auto",
    color_continuous_scale="RdBu_r",
    zmin=90,
    zmax=110,
    title="Hourly volume index per channel (100 = the channel's mean hour; business clock)",
)
fig.update_layout(height=320, xaxis_title="hour of the delivery day")
fig.show()
for (cc, c_), d in ch.groupby(["country_code", "channel"], sort=True):
    u = g.uniform_hours_test(d.groupby("hour_of_day").n_tx.sum())
    tests.append(
        {
            "scenario": "03 market and channel",
            "test": f"{cc} {c_}: flat hours",
            "statistic": u["chi2"],
            "p_value": u["p_value"],
            "effect": u["cohen_w"],
            "n": int(u["n"]),
            "reading": "intraday profile"
            if u["p_value"] < 0.01 and u["cohen_w"] >= 0.1
            else "flat",
        }
    )
for c_, d in ch.groupby("channel", sort=True):
    t = d.groupby("hour_of_day")[["n_declined", "n_tx"]].sum()
    r = stats.chi2_contingency(np.column_stack([t.n_declined, t.n_tx - t.n_declined]))
    tests.append(
        {
            "scenario": "03 market and channel",
            "test": f"{c_}: decline rate by hour",
            "statistic": r.statistic,
            "p_value": r.pvalue,
            "effect": float(np.sqrt(r.statistic / t.n_tx.sum())),
            "n": int(t.n_tx.sum()),
            "reading": "hour matters" if r.pvalue < 0.01 else "flat",
        }
    )
tt = pd.DataFrame(tests)
show(tt.round(5), paging=False)
display(
    Markdown(
        f"**{int((tt.reading != 'flat').sum())} of {len(tt)} channel tests find an hourly effect; the largest Cohen's w "
        f"is {tt.effect.max():.3f}.** "
        + (
            "No channel has an intraday rhythm or an hour-dependent decline rate: ATM, POS, app, web, transfers and "
            "branch tellers all spread their volume evenly over the 24 hours of the business day. A real network "
            "peaks at lunch and in the evening and is near-silent at night; capacity and maintenance windows are "
            "planned on exactly that profile."
            if (tt.reading == "flat").all()
            else "Some channels have hourly structure."
        )
    )
)

# %% [markdown]
# ## 2 · Hourly monitors per channel
# The negative-binomial limit carries the day-level dispersion (series II): if the day's total varies with variance
# E + c·E², an hour has variance m + c·m².

# %%
al = []
for (cc, c_), d in ch.groupby(["country_code", "channel"], sort=True):
    mu = d.groupby("delivery_weekday").n_tx.transform("mean")
    daily = d.groupby("delivery_day").n_tx.sum()
    wd = d.groupby("delivery_day").delivery_weekday.first()
    e_wd = daily.groupby(wd).transform("mean")
    c = max(1e-9, float((((daily - e_wd) ** 2 - e_wd).mean()) / (e_wd**2).mean()))
    pr = (1 / c) / (1 / c + mu)
    for name, lo, hi in [
        ("Poisson", stats.poisson.ppf(0.0005, mu), stats.poisson.ppf(0.9995, mu)),
        (
            "negative binomial",
            stats.nbinom.ppf(0.0005, 1 / c, pr),
            stats.nbinom.ppf(0.9995, 1 / c, pr),
        ),
    ]:
        al.append(
            {
                "market": cc,
                "channel": c_,
                "limits": name,
                "hours": len(d),
                "flagged %": 100 * float(((d.n_tx < lo) | (d.n_tx > hi)).mean()),
                "day CV beyond Poisson %": 100 * np.sqrt(c),
            }
        )
al = pd.DataFrame(al)
show(al.round(3), paging=True)
rate = al.groupby("limits")["flagged %"].mean()
display(
    Markdown(
        f"**Poisson limits flag {rate['Poisson']:.2f} % of channel-hours and negative-binomial limits "
        f"{rate['negative binomial']:.2f} %** (0.1 % expected). "
        + (
            "At channel level Poisson limits are already calibrated: an hour of one channel holds few events, so "
            "Poisson noise dwarfs the day-level swing that made market-total monitors over-alert (series II). The "
            "dispersion factor matters for large aggregates and can be dropped for small ones; "
            if 0.05 <= rate["Poisson"] <= 0.2
            else "Poisson limits are miscalibrated at channel level and need the dispersion factor; "
        )
        + "the smallest channels (transfers, branch tellers) have so few events per hour that their limits are wide, "
        "and a monitor there should run on 4-hour or daily windows."
    )
)

# %% [markdown]
# ## 3 · The models, executed

# %%
rows, detail = hm.channel(star)
show(detail["variants"].round(4), paging=False)
sc = pd.DataFrame(rows)
show(
    sc[
        [
            "model",
            "best_variant",
            "metric",
            "value",
            "benchmark",
            "benchmark_value",
            "delta",
            "delta_lo",
            "delta_hi",
            "verdict",
            "root_cause",
        ]
    ].round(4),
    paging=False,
)
tt.to_csv(OUT / "granularity_hour_channel_hour.csv", index=False)
v = detail["variants"]["pooled MASE"]
display(
    Markdown(
        f"**Across {detail['series']} market × channel series, the weekday's mean day spread flat scores MASE "
        f"{v['weekday mean / 24']:.3f}; the best hourly model ({rows[0]['best_variant']}) {rows[0]['value']:.3f}; last "
        f"week's day spread flat {v['day/24']:.3f}.** The readiness gate is **{rows[0]['verdict']}** "
        f"({rows[0]['root_cause'] or 'ready'}): an hourly model only re-learns the weekday level, with noise. The "
        "hourly models do beat last week's single day spread flat, but only because they average many weeks; the "
        "fair benchmark, with the same weeks and no hour, is as good or better."
    )
)

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
