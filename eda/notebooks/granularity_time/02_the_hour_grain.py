# %% [markdown]
# # 02 · The hour grain: is the hour worth a fact table?
# **Granularity series II · time and cells** · grain: one market and UTC hour (`agg.fct_country_hour`, dense)
#
# **Stakeholders.** The contact-centre director (agents per hour), operations (intraday monitoring: is this hour
# normal?), the streaming platform (the hourly twin of the day KPIs), treasury (intraday cash).
#
# **The question.** An hourly fact costs 24 times the rows of a daily one. It earns its place only if the hour carries
# information the day does not: a profile within the day (a morning peak to staff for, a night trough), or hour-level
# variation a monitor should react to. Three tests:
# 1. **Does the hour add information beyond the day?** If, given a day's total D, the hours split it uniformly, then
#    each hour's count is Binomial(D, 1/24) and the statistic Σ (x − D/24)² / (D/24) over a day's 24 hours follows a
#    χ² with 23 degrees of freedom. Its ratio to 23, averaged over days, is the **dispersion index**: 1 means the hour is
#    just the day divided by 24.
# 2. **Forecast:** an hourly forecast built as the daily forecast spread flat over 24 hours, against a model that
#    learns an hour-of-day and hour-of-week profile (seasonal naive at one week, 168 hours). MASE and Diebold–Mariano.
# 3. **Staffing:** Erlang C per hour on the observed (flat) profile, and a sensitivity on a realistic peaked profile:
#    what the flat data hides.

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

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, g.SQL_DIR_TIME)
built = star.build(verbose=False)
checks = star.check()
show(built, paging=False)
show(checks, paging=False)
display(
    Markdown(
        f"**{int(checks.ok.sum())} of {len(checks)} checks pass** on the hour and cell aggregates (unique grain, exact "
        "reconciliation of every additive measure to its atomic fact, dense hour grid)."
    )
)
hr = star.q("""select * from {fct_country_hour} order by country_code, hour_start""")
hr = hr[
    (hr.delivery_day > hr.delivery_day.min()) & (hr.delivery_day < hr.delivery_day.max())
]  # whole delivery days

# %% [markdown]
# ## 1 · The profile within the day

# %%
MEAS = ["n_tx", "inbound_contacts", "sessions", "complaints_opened", "sends"]
# each measure is placed on its own process's delivery day (notebook 01): −6 h or −8 h from the UTC hour
CLOCK = {
    "n_tx": "transactions",
    "inbound_contacts": "call_center_interactions",
    "contacts": "call_center_interactions",
    "sessions": "digital_events",
    "complaints_opened": "complaints",
    "sends": "campaign_sends",
}


def on_clock(d: pd.DataFrame, m: str) -> pd.DataFrame:
    """The hours of `d` with the delivery day, hour of day and weekday of measure `m`'s process clock."""
    t = d.hour_start + pd.to_timedelta(country.PROCESS_DAY_OFFSET[CLOCK[m]], unit="h")
    out = d.assign(p_day=t.dt.normalize(), p_hour=t.dt.hour, p_weekday=t.dt.dayofweek + 1)
    return out[
        (out.p_day > out.p_day.min()) & (out.p_day < out.p_day.max())
    ]  # whole delivery days only


prof = hr.groupby("hour_of_day")[MEAS].sum()
prof = prof / prof.sum()
fig = px.line(
    (100 * prof).reset_index().melt(id_vars="hour_of_day"),
    x="hour_of_day",
    y="value",
    color="variable",
    title="Share of each process by hour of the delivery day (0 = 06:00 UTC)",
)
fig.add_hline(y=100 / 24, line_dash="dot")
fig.update_layout(height=340, yaxis_title="% of the day", yaxis_range=[3.5, 4.8])
fig.show()

# %% [markdown]
# ## 2 · Does the hour add information beyond the day?

# %%
rows = []
for cc, m in [(cc, m) for cc in sorted(hr.country_code.unique()) for m in MEAS]:
    d = on_clock(hr[hr.country_code == cc], m)
    piv = d.pivot_table(index="p_day", columns="p_hour", values=m, aggfunc="sum").fillna(0)
    piv = piv[piv.sum(axis=1) >= 24]  # days with enough events for the χ² approximation
    if len(piv) < 30:
        continue
    tot = piv.sum(axis=1).to_numpy()[:, None]
    e = tot / 24
    chi = ((piv.to_numpy() - e) ** 2 / e).sum(axis=1)
    disp = chi.mean() / 23
    # pooled test: the sum of the daily statistics is χ² with 23 × days degrees of freedom under uniform hours
    p = stats.chi2.sf(chi.sum(), 23 * len(piv))
    rows.append(
        {
            "market": cc,
            "measure": m,
            "days": len(piv),
            "mean events per hour": float(tot.mean() / 24),
            "dispersion index": disp,
            "p_value": p,
        }
    )
disp = pd.DataFrame(rows)
disp.to_csv(OUT / "granularity_time_hour_dispersion.csv", index=False)
show(disp.round(4), paging=False)
display(
    Markdown(
        f"**The dispersion index is {disp['dispersion index'].min():.3f} to {disp['dispersion index'].max():.3f} across "
        f"{len(disp)} market series (1 = the day split uniformly at random over its hours).** "
        + (
            "Given the day's total, every hour's count is a binomial draw: the hour adds no information beyond the day "
            "divided by 24. An hourly fact table would store 24 times the rows to hold the same information as the daily "
            "one plus noise."
            if disp["dispersion index"].max() < 1.1
            else "Some series vary between hours more than chance: "
            + ", ".join(
                f"{r['market']} {r['measure']} ({r['dispersion index']:.2f})"
                for _, r in disp[disp["dispersion index"] >= 1.1].iterrows()
            )
            + "; their hourly profile carries information."
        )
    )
)

# %% [markdown]
# ## 3 · Forecasting the hour
# The last 8 weeks are forecast one week ahead (origins every 7 days): **day / 24** spreads the seasonal-naive daily
# forecast (same weekday last week) flat over the hours; **seasonal naive 168 h** repeats the same hour of last week,
# which is what an hour-of-week profile model reduces to when the profile is the only structure.

# %%
fc = []
for cc, d in hr.groupby("country_code"):
    for m in ["n_tx", "inbound_contacts"]:
        dm = on_clock(d, m)
        y = dm.set_index("hour_start")[m].astype(float)
        day = dm.groupby("p_day")[m].sum()
        n = len(y)
        test = np.arange(n - 8 * 168, n)
        naive168 = y.shift(168).to_numpy()[test]
        dday = pd.Series(dm.p_day.to_numpy(), index=y.index)
        prev_week_day = day.shift(7).reindex(dday.iloc[test].to_numpy()).to_numpy()
        flat = prev_week_day / 24
        act = y.to_numpy()[test]
        ins = y.to_numpy()[: test[0]]
        ok = ~np.isnan(flat) & ~np.isnan(naive168)
        m_flat = g.mase(act[ok], flat[ok], ins, season=168)
        m_168 = g.mase(act[ok], naive168[ok], ins, season=168)
        stat, p = g.diebold_mariano(act[ok] - flat[ok], act[ok] - naive168[ok], horizon=1)
        fc.append(
            {
                "market": cc,
                "measure": m,
                "MASE day / 24": m_flat,
                "MASE seasonal naive 168 h": m_168,
                "DM stat (day/24 vs 168 h)": stat,
                "DM p": p,
            }
        )
fc = pd.DataFrame(fc)
show(fc.round(4), paging=False)
display(
    Markdown(
        f"**Spreading the daily forecast flat beats repeating last week's hour in {int((fc['MASE day / 24'] < fc['MASE seasonal naive 168 h']).sum())} "
        f"of {len(fc)} series** (MASE {fc['MASE day / 24'].mean():.3f} against {fc['MASE seasonal naive 168 h'].mean():.3f}). "
        + (
            "Last week's hour carries that hour's noise into the forecast; the day's total, divided evenly, carries "
            "none. The best hourly forecast on this data is a daily forecast."
            if (fc["MASE day / 24"] < fc["MASE seasonal naive 168 h"]).all()
            else "In some series last week's hour is better: an hourly profile exists there."
        )
    )
)

# %% [markdown]
# ## 4 · Staffing per hour: what the flat profile implies, and what it hides
# Erlang C (80 % of contacts answered within 20 s) per hour of the week on the observed inbound arrivals and handle
# time. For comparison, the same weekly volume redistributed along a **typical retail-bank contact-centre profile**
# (an assumption, stated here: night hours at 25 % of the mean, a morning peak at 170 %, a smaller afternoon peak at
# 140 %), to show the staffing a real profile would demand that this data cannot reveal.

# %%
wk = on_clock(hr, "inbound_contacts")
wk = wk.assign(how=(wk.p_weekday - 1) * 24 + wk.p_hour)
weeks = wk.p_day.nunique() / 7
arr = wk.groupby("how").agg(
    inbound=("inbound_contacts", "sum"),
    handle=("handle_seconds", "sum"),
    contacts=("contacts", "sum"),
)
arr["per_hour"] = arr.inbound / weeks
aht = float(arr.handle.sum() / arr.contacts.sum())
arr["agents_flat"] = [g.agents_needed(v, aht, 20, 0.8) for v in arr.per_hour]
shape = np.array(
    [0.25] * 2
    + [0.4, 0.7, 1.2, 1.7, 1.7, 1.5, 1.2, 1.3, 1.4, 1.4, 1.2, 1.0, 0.9, 0.7, 0.5, 0.35]
    + [0.25] * 6
)
shape = shape / shape.mean()
day_tot = arr.per_hour.groupby(arr.index // 24).sum().to_numpy()
peaked = np.concatenate([day_tot[d] / 24 * shape for d in range(7)])
arr["per_hour_peaked"] = peaked
arr["agents_peaked"] = [g.agents_needed(v, aht, 20, 0.8) for v in peaked]
# a roster sized on the flat profile, facing the peaked arrivals
arr["sl_flat_roster"] = [
    g.service_level(v, aht, int(c), 20)
    for v, c in zip(arr.per_hour_peaked, arr.agents_flat, strict=True)
]
worst = arr.loc[arr.sl_flat_roster.idxmin()]
fig = px.line(
    arr.reset_index().melt(id_vars="how", value_vars=["agents_flat", "agents_peaked"]),
    x="how",
    y="value",
    color="variable",
    title="Agents needed per hour of the week (Erlang C, 80/20): observed flat arrivals against a typical peaked profile",
)
fig.update_layout(
    height=340, xaxis_title="hour of the contact delivery week (0 = Monday 08:00 UTC)"
)
fig.show()
display(
    Markdown(
        f"**On the observed arrivals ({arr.per_hour.mean():.1f} inbound contacts an hour, handle time {aht / 60:.1f} "
        f"minutes) Erlang C needs {arr.agents_flat.min()} to {arr.agents_flat.max()} agents in every hour of the week, "
        f"{int(arr.agents_flat.sum())} agent-hours a week.** The same volume on a typical peaked profile needs "
        f"{arr.agents_peaked.min()} to {arr.agents_peaked.max()} agents and {int(arr.agents_peaked.sum())} agent-hours "
        f"({100 * (arr.agents_peaked.sum() / arr.agents_flat.sum() - 1):+.0f} %)"
        + ". The weekly total barely moves; **the schedule does**: in the peak hour of a peaked week a roster sized on "
        "the flat profile would "
        + (
            "face more work than it can serve (the queue grows without bound)"
            if worst.sl_flat_roster == 0
            else f"answer only {worst.sl_flat_roster:.0%} of contacts within 20 seconds"
        )
        + ", and "
        f"{int((arr.sl_flat_roster < 0.8).sum())} of 168 hours would miss the target of 80 % answered within 20 s. On real data the hourly profile "
        "decides **when** agents are scheduled, which is where service levels are won or lost; it must be measured on "
        "the delivery clock of the contact process (−8 h here), not on UTC."
    )
)

# %% [markdown]
# ## 5 · Intraday monitoring: limits per hour
# A streaming monitor flags an hour whose count falls outside the 99.9 % interval of its expected value. With a
# well-specified model, about 0.1 % of hours are flagged by chance. Three variants, all on the process's own clock:
# * **Poisson, static:** the weekday's mean hour over the whole period;
# * **Poisson, trailing:** the mean hour of the same weekday over the previous four weeks, which follows a drifting level;
# * **negative binomial, static:** section 2 showed the hours are binomial *given the day*, so any excess must come from
#   the day's level varying more than Poisson. If the day total L has mean E and variance E + c·E², an hour (mean
#   m = E/24) has variance m + c·m²: a negative binomial with size 1/c. c is estimated by moments from the daily totals
#   around their weekday means.

# %%
al = []
for cc, d in hr.groupby("country_code"):
    for m in ["n_tx", "contacts"]:
        dm = on_clock(d, m)
        mu_static = dm.groupby("p_weekday")[m].transform("mean")
        daily = dm.groupby("p_day")[m].sum()
        trail = (daily.shift(7) + daily.shift(14) + daily.shift(21) + daily.shift(28)) / 4 / 24
        mu_trail = dm.p_day.map(trail)
        e_wd = daily.groupby(daily.index.dayofweek).transform("mean")
        c = max(1e-9, float((((daily - e_wd) ** 2 - e_wd).mean()) / (e_wd**2).mean()))
        size = 1 / c
        for name, mu, dist in [
            ("Poisson, static", mu_static, "poisson"),
            ("Poisson, trailing 4 weeks", mu_trail, "poisson"),
            ("negative binomial, static", mu_static, "nbinom"),
        ]:
            k = mu.notna()
            if dist == "poisson":
                lo, hi = stats.poisson.ppf(0.0005, mu[k]), stats.poisson.ppf(0.9995, mu[k])
            else:
                pr = size / (size + mu[k])
                lo, hi = stats.nbinom.ppf(0.0005, size, pr), stats.nbinom.ppf(0.9995, size, pr)
            x = dm[m][k]
            al.append(
                {
                    "market": cc,
                    "measure": m,
                    "limits": name,
                    "day-level CV beyond Poisson %": 100 * np.sqrt(c),
                    "hours": int(k.sum()),
                    "flagged": int(((x < lo) | (x > hi)).sum()),
                }
            )
al = pd.DataFrame(al)
al["flagged %"] = 100 * al.flagged / al.hours
rate = al.groupby("limits").apply(
    lambda d: 100 * d.flagged.sum() / d.hours.sum(), include_groups=False
)
show(al.round(3), paging=False)
display(
    Markdown(
        f"**Poisson limits flag {rate['Poisson, static']:.2f} % of hours (static) and "
        f"{rate['Poisson, trailing 4 weeks']:.2f} % (trailing); negative-binomial limits flag "
        f"{rate['negative binomial, static']:.2f} %** (0.1 % expected by chance). The day's level varies "
        f"{al['day-level CV beyond Poisson %'].min():.0f}–{al['day-level CV beyond Poisson %'].max():.0f} % beyond "
        "Poisson, and a trailing mean adds its own estimation noise instead of removing that variation. "
        + (
            "Carrying the day-level dispersion into the limits calibrates the monitor (slightly conservatively): "
            "negative-binomial limits on a "
            "weekday baseline are the right **streaming** control, the intraday twin of the daily control charts "
            "(granularity series, notebook 04), computed in the stream rather than stored as an hourly fact."
            if rate["negative binomial, static"] < 0.25
            else "Even negative-binomial limits over-alert: the baseline itself needs a model (trend, events) before "
            "an hourly monitor is trusted."
        )
    )
)

# %% [markdown]
# ## Findings and what they mean downstream
# * **The hour adds no information beyond the day here**: no intraday profile, binomial hours given the day, and the
#   best hourly forecast is the daily one divided by 24. An hourly **fact table is not worth promoting**; the hourly
#   view belongs in the **streaming layer** (limit monitors, the intraday twin of the day KPIs), computed on the fly.
# * **Monitors need the day-level dispersion**: plain Poisson limits over-alert because the day's level varies beyond
#   Poisson; the limits must carry that dispersion (section 5).
# * **On real data the hour is the grain that schedules the contact centre** (the profile decides when agents work and
#   whether peak hours meet the service level), and it must be measured on each process's own delivery clock
#   (notebook 01).
# * **Downstream:** no new dbt model; a streaming job with hourly counts per market and process, its limits, and a
#   parity test that the 24 hourly counts of a delivery day sum to the batch day.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
