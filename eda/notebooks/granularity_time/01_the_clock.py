# %% [markdown]
# # 01 · The clock: in which time were the data's days drawn?
# **Granularity series II · time and cells** · grain: the hour, read straight from lossless bronze
#
# **Why this matters.** Every daily figure of the platform depends on where a day starts: a weekend, a holiday, a
# payday, a month end, a daily control chart, the `is_weekend` and `local_hour` fraud features. The source never states
# the timezone of its timestamps (`docs/strategy/12_development_path.md` lists "explicit time zones" as a data request),
# and the platform assumed each country's legal local time. This notebook asks the data itself.
#
# **Method: the weekly rhythm as a clock.** If days are drawn in some clock with a weekly rhythm (fewer events at the
# weekend) and the time within the day is drawn independently of the weekday, then **only in that clock** is hour of day
# independent of weekday: in any other clock the weekend boundary cuts through the hours (Saturday's last hours spill
# into Sunday, and so on). For each shift k of −12 to +12 hours added to the raw timestamps, the chi-square test of
# independence between weekday and hour is computed (`granularity.clock_scan`). The minimising shift is the clock; at
# the right shift the statistic falls to about its degrees of freedom (138 = 6 × 23), the value expected under
# independence.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import statsmodels.formula.api as smf
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme
from latam_eda import granularity as g
from latam_eda import pipeline as pipe

OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
LAKE = pipe.default_lake(pipe.repo_root(Path.cwd())) / "bronze_raw"
con = duckdb.connect()
con.sql("SET threads = 4")
con.sql("SET memory_limit = '4GB'")


def raw(table: str) -> str:
    return f"read_parquet('{LAKE}/{table}/*/*.parquet', union_by_name = true, hive_partitioning = false)"


PROCESSES = {
    "transactions": "transaction_date",
    "call_center_interactions": "interaction_date",
    "digital_events": "event_date",
    "complaints": "creation_date",
    "campaign_sends": "send_date",
    "satisfaction_surveys": "survey_date",
}
MARKET = {"México": "MX", "Colombia": "CO", "Argentina": "AR"}
con.sql(f"create table cust as select customer_id, country from {raw('customers')}")
# hourly counts per process and market (raw clock, hour-floored): the only input of everything below
parts = []
for t, c in PROCESSES.items():
    parts.append(
        con.sql(f"""
        select '{t}' as process, k.country, date_trunc('hour', try_cast(r.{c} as timestamp)) as hour_start, count(*) as n
        from {raw(t)} r join cust k using (customer_id)
        where try_cast(r.{c} as timestamp) is not null group by all""").df()
    )
hourly = pd.concat(parts, ignore_index=True)
hourly["market"] = hourly.country.map(MARKET)
print(f"{len(hourly):,} (process, market, hour) cells, {int(hourly.n.sum()):,} events")

# %% [markdown]
# ## 1 · Hour of day, as delivered

# %%
prof = hourly.assign(h=hourly.hour_start.dt.hour).groupby(["process", "h"]).n.sum().reset_index()
prof["share %"] = 100 * prof.n / prof.groupby("process").n.transform("sum")
fig = px.line(
    prof, x="h", y="share %", color="process", title="Share of events by hour of the raw timestamp"
)
fig.add_hline(y=100 / 24, line_dash="dot", annotation_text="uniform (4.17 %)")
fig.update_layout(height=360, xaxis_title="hour of day (raw clock)", yaxis_range=[3.5, 4.8])
fig.show()
cv = prof.groupby("process").n.agg(lambda x: x.std() / x.mean())
display(
    Markdown(
        "**Every process is flat over the 24 hours** (coefficient of variation of the hourly counts: "
        + ", ".join(f"{k} {v:.3f}" for k, v in cv.items())
        + "). There is no morning peak, lunchtime or night trough in any clock: an hour is an hour. A real bank's "
        "transactions peak around midday and fall to a few percent of the peak at night, and its contact centre has a "
        "pronounced morning peak; neither exists here, so the intraday shape cannot be modelled on this data."
    )
)

# %% [markdown]
# ## 2 · The clock scan

# %%
scans = []
for (proc, mk), d in hourly.groupby(["process", "market"]):
    s = g.clock_scan(d.hour_start, counts=d.n.to_numpy())
    s["process"], s["market"] = proc, mk
    scans.append(s)
scan = pd.concat(scans, ignore_index=True)
fig = px.line(
    scan[scan.process == "transactions"],
    x="shift_hours",
    y="chi2_over_dof",
    color="market",
    log_y=True,
    markers=True,
    title="Transactions: dependence between weekday and hour (χ² / dof) by clock shift",
)
fig.add_hline(y=1, line_dash="dot", annotation_text="independence")
fig.update_layout(height=360, xaxis_title="hours added to the raw timestamps")
fig.show()
best = scan.loc[scan.groupby(["process", "market"]).chi2.idxmin()].set_index(["process", "market"])
at0 = scan[scan.shift_hours == 0].set_index(["process", "market"]).chi2_over_dof
legal = pd.Series(
    {
        (p, m): scan[
            (scan.process == p)
            & (scan.market == m)
            & (scan.shift_hours == country.COUNTRIES[m].utc_offset)
        ].chi2_over_dof.iloc[0]
        for p, m in best.index
    }
)
clock = best[["shift_hours", "chi2_over_dof"]].rename(
    columns={"shift_hours": "best shift (h)", "chi2_over_dof": "χ²/dof at best"}
)
clock["χ²/dof at legal local time"] = legal
clock["χ²/dof at raw clock (0 h)"] = at0
clock = clock.reset_index()
clock.to_csv(OUT / "granularity_time_clock.csv", index=False)
show(clock.round(2), paging=False)
per_process = clock.groupby("process")["best shift (h)"].agg(lambda x: x.mode().iloc[0])
same = clock.groupby("process")["best shift (h)"].nunique().eq(1)
display(
    Markdown(
        "**Every market of a process aligns at the same shift, and the shift depends on the process, not the market:** "
        + ", ".join(
            f"{k} {v:+d} h" + ("" if same[k] else " (varies)") for k, v in per_process.items()
        )
        + f". At the best shift the dependence falls to χ²/dof {clock['χ²/dof at best'].median():.2f} (independence is "
        f"1), against {clock['χ²/dof at raw clock (0 h)'].median():.0f} on the raw clock and "
        f"{clock['χ²/dof at legal local time'].median():.0f} on each country's legal local time. The shifts are the start "
        "hours of each process's daily delivery batch (06:00 UTC for transactions, digital events and sends; 08:00 UTC for "
        "contacts and complaints): the next section checks that directly."
    )
)

# %% [markdown]
# ### The clock is the delivery day
# Every row carries `process_date`, the daily batch it was delivered in. If the generator drew the weekly rhythm on
# that day and placed the timestamp inside the batch window, then the timestamp shifted back to the window's start
# must land on `process_date` for every row.

# %%
match = []
for t, c in PROCESSES.items():
    r = (
        con.sql(f"""select {", ".join(f"avg((cast(try_cast({c} as timestamp) + interval ({k}) hour as date) = try_cast(process_date as date))::int) as s{abs(k)}" for k in (0, -6, -8, -10))}
                    from {raw(t)}""")
        .df()
        .iloc[0]
    )
    match.append(
        {
            "process": t,
            "share = process_date at 0 h": r.s0,
            "at −6 h": r.s6,
            "at −8 h": r.s8,
            "at −10 h": r.s10,
            "library offset (h)": country.PROCESS_DAY_OFFSET.get(t),
        }
    )
match = pd.DataFrame(match)
show(match.round(4), paging=False)
exact = match[match[["at −6 h", "at −8 h"]].max(axis=1) > 0.995]
display(
    Markdown(
        f"**For {len(exact)} of {len(match)} processes the shifted timestamp equals `process_date` on "
        f"{100 * exact[['at −6 h', 'at −8 h']].max(axis=1).min():.1f} % or more of rows.** The generator drew each event's "
        "day as a delivery day with the weekly rhythm, then placed its timestamp uniformly inside that day's batch window. "
        "**The data's business day is the delivery day (`process_date`), the same for every market**; the timestamps are "
        "UTC and say nothing about the customer's local time. Surveys arrive in roughly 42-hour windows and have no "
        "fixed offset. The library now encodes this (`country.PROCESS_DAY_OFFSET`); the granularity day facts use "
        "`process_date` directly."
    )
)

# %% [markdown]
# ## 3 · What the wrong clock did to the calendar findings
# The country series placed each customer's day on the legal local time (Colombia UTC−5, Argentina UTC−3). The table
# re-estimates, per market, the calendar regression of notebook 04 of the country series (log daily transactions on
# weekday, holiday, payday window, month end and trend, HC3 errors) on both clocks.

# %%
tx = hourly[hourly.process == "transactions"]
rec = []
for mk, d in tx.groupby("market"):
    cal = (
        country.calendar(mk)
        .assign(local_date=lambda x: pd.to_datetime(x.local_date))
        .set_index("local_date")
    )
    for clk in ["local", "business"]:
        day = (d.hour_start + pd.Timedelta(hours=country.utc_offset(mk, clk))).dt.normalize()
        y = d.groupby(day).n.sum()
        y = y[(y.index >= "2023-07-01") & (y.index < "2026-05-01")]
        k = cal.reindex(y.index)
        df = pd.DataFrame(
            {
                "y": np.log(y.to_numpy()),
                "wd": y.index.weekday,
                "hol": k.is_holiday.astype(int).to_numpy(),
                "pay": (k.days_since_payday.fillna(99) <= 2).astype(int).to_numpy(),
                "me": k.is_month_end.astype(int).to_numpy(),
                "t": ((y.index - y.index.min()).days / 365.25).to_numpy(),
            }
        )
        m = smf.ols("y ~ C(wd) + hol + pay + me + t", data=df).fit(cov_type="HC3")
        eff = lambda term: 100 * (np.exp(m.params[term]) - 1)  # noqa: E731
        mon = m.params[[f"C(wd)[T.{i}]" for i in range(1, 5)]].mean()  # Tue..Fri against Monday
        rec.append(
            {
                "market": mk,
                "clock": f"{clk} (UTC{country.utc_offset(mk, clk):+d})",
                "Saturday %": eff("C(wd)[T.5]"),
                "Sunday %": eff("C(wd)[T.6]"),
                "Monday vs Tue–Fri %": -100 * (np.exp(mon) - 1),
                "holiday %": eff("hol"),
                "holiday p": m.pvalues["hol"],
                "payday window %": eff("pay"),
                "payday p": m.pvalues["pay"],
                "R²": m.rsquared,
            }
        )
recon = pd.DataFrame(rec)
recon.to_csv(OUT / "granularity_time_reconciliation.csv", index=False)
show(recon.round(3), paging=False)
loc = recon[recon.clock.str.startswith("local")].set_index("market")
bus = recon[recon.clock.str.startswith("business")].set_index("market")
display(
    Markdown(
        f"**On the business clock the weekend is the same in every market** (Saturday {bus['Saturday %'].min():.1f} % to "
        f"{bus['Saturday %'].max():.1f} %, Sunday {bus['Sunday %'].min():.1f} % to {bus['Sunday %'].max():.1f} %), and the "
        f"model explains more (R² {bus['R²'].mean():.3f} against {loc['R²'].mean():.3f}). On the legal clocks Argentina's "
        f"Saturday looked {loc.loc['AR', 'Saturday %']:.1f} % and its Monday {loc.loc['AR', 'Monday vs Tue–Fri %']:+.1f} % "
        f'against the other weekdays (business clock: {bus.loc["AR", "Monday vs Tue–Fri %"]:+.1f} %): the "national" '
        "patterns the country series reported for Argentina and Colombia were **three and one hours of Sunday counted as "
        "Monday**. Holidays and paydays stay without effect on either clock (every holiday p > "
        f"{min(recon['holiday p']):.2f}): the calendar beyond the weekend is absent from the data, not hidden by the clock."
    )
)

# %% [markdown]
# ## What this means, and what was changed
# * **The business day is now explicit** (`country.PROCESS_DAY_OFFSET`, `enrich_transactions(clock="business")`; the
#   granularity day facts use `process_date`), and the country, backup-as-main and granularity notebooks that depend on
#   a day boundary were re-executed on it.
# * **The platform has two defects of the same kind** (ADR-014; P0 items of v0.3.0 in
#   `docs/strategy/12_development_path.md` §12.7):
#   * `transaction_ts_local`, `local_hour` and `is_weekend` in `int_transactions_enriched` (macro
#     `enrich_transactions`) use the transaction country's legal offset, so the fraud features read Colombian and
#     Argentine weekends three and one hours off. They should be derived from the delivery day.
#   * Integrity rules **R15** (contacts) and **R16** (complaints) test `timestamp − 6 h = process_date`; for these two
#     processes the delivery day starts at 08:00 UTC, so their ~8 % "violations" are an artefact of the wrong offset
#     (at −8 h the match is 100 %, section 2). The rules should use each process's own window start.
# * **For real data the question returns**: the source contract must declare the clock of every timestamp and the
#   window of every delivery; this scan and the `process_date` match are the tests that verify the declaration on every
#   delivery.

# %%
con.close()
print(f"notebook time {time.time() - t0:.0f}s")
