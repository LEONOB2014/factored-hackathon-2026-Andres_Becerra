# %% [markdown]
# # 04 · Staging, local time and the country calendar (All countries)
# **Backup-as-main series · All countries** · *generated from `notebooks/country_template`: edit the template*
#
# Staging names the source timestamps `*_ts_utc` (pipeline series, notebook 04). For behaviour, what matters is the
# **customer's** local day: when salaries arrive, which days banks close, when the weekend starts. This notebook
# places every transaction on its day (the source's business clock) and enriches it with the country's calendar, then
# measures what the calendar explains.
#
# **Decisions.**
# * **The delivery day, not each country's legal time.** The source states no timezone, and the data decides it. Every
#   event belongs to a daily delivery batch (`process_date`), and the generator drew its weekly rhythm on that day:
#   hour of day is independent of weekday only once each timestamp is shifted back to the start of its batch window
#   (−6 hours for transactions, digital events and sends, −8 hours for contacts and complaints), where
#   `cast(ts + offset as date) = process_date` for every row (`notebooks/granularity_time/01`). The same day boundary
#   applies to every market (`country.PROCESS_DAY_OFFSET`, `enrich_transactions(clock="business")`). An earlier
#   version used each country's legal offset (Colombia UTC−5, Argentina UTC−3), which cut the weekends 1 and 3 hours
#   off their true boundary: Argentina's weekend looked weaker and its Mondays quieter, both artefacts. On real data
#   whose timestamps are true UTC, `clock="local"` applies the legal offsets (fixed offsets are exact for 2023–2026: no
#   DST in Mexico since 2022 outside border cities, none in Colombia, none in Argentina since 2009).
# * **The customer's country, not the transaction's**: a cross-border purchase still happens in the customer's day
#   (and its own local time stays in silver as `transaction_ts_local`).
# * **Calendar variables** (`country.calendar`): weekday, weekend, statutory **and bank** holidays (Mexico's banks also
#   close on Holy Thursday, Good Friday, 2 November and 12 December), long weekends, **paydays** (Mexico and
#   Colombia pay fortnightly on the 15th and the last day, moved back to the previous business day; Argentina monthly
#   in the first business days), days since payday, month start and end, week of month, bonus months (aguinaldo,
#   prima).

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

from latam_eda import country, theme

COUNTRY = "ALL"
DATASET = "backup"
PREFIX = "backup"
CTRY = country.SCOPES[COUNTRY]
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "seeds")
STG = sorted(n for n in pl.catalog()["node"] if n.startswith("stg_"))
built = pl.build_set(STG)
pl.ensure(pl.key("int_transactions_enriched"))
for code in country.scope_codes(COUNTRY):
    c = country.COUNTRIES[code]
    print(
        f"{c.name}: delivery day = timestamp {country.utc_offset(code):+d} h (legal local time UTC{c.utc_offset:+d}, {c.timezone})"
    )
print(country.enrich_transactions(pl))

# %% [markdown]
# ## 1 · The calendar

# %%
cal = pl.q("select * from main.calendar_local")
hol = cal[cal.is_holiday][["country_code", "local_date", "holiday_name", "iso_weekday"]]
show(hol, paging=False)
summary = cal.groupby("country_code").apply(
    lambda g: pd.Series(
        {
            "days": len(g),
            "holidays": int(g.is_holiday.sum()),
            "on_weekdays": int((g.is_holiday & ~g.is_weekend).sum()),
            "long_weekend_days": int(g.is_long_weekend.sum()),
            "paydays": int(g.is_payday.sum()),
        }
    ),
    include_groups=False,
)
show(summary, paging=False)

# %% [markdown]
# ## 2 · Time of day, in local time

# %%
hours = pl.q(
    "select local_hour_customer as local_hour, count(*) as transactions from main.tx_local group by 1 order by 1"
)
fig = px.bar(
    hours, x="local_hour", y="transactions", title=f"{CTRY.title}: transactions by local hour"
)
fig.update_layout(height=300)
fig.show()
cv = hours.transactions.std() / hours.transactions.mean()
display(
    Markdown(
        f"**Hour-of-day coefficient of variation: {cv:.3f}.** "
        + (
            "Local time shifts the uniform UTC profile by the offset and leaves it uniform: there is no daily cycle to "
            "model, in any time zone. Time-of-day features stay in the design and carry no signal here."
            if cv < 0.05
            else "There is a daily cycle in local time: time-of-day features can carry signal."
        )
    )
)

# %% [markdown]
# ## 3 · What the calendar explains: a regression on daily volume
# Daily transaction counts (local date) regressed on weekday, holiday, long weekend, payday window, month end and a
# linear trend, by **OLS on log counts**: on a log scale a coefficient β is a percentage effect, exp(β) − 1, and daily
# counts in the thousands make the log-normal approximation accurate. Standard errors are heteroscedasticity-robust
# (HC3). The first and last partial months are excluded.
#
# **Whole bank:** one row per (country, local day), each day on its own country's calendar, with **country fixed
# effects** (`C(country_code)`): the levels of the three countries differ, and the calendar terms are estimated within
# country, so a Mexican holiday is compared with Mexican working days.

# %%
daily = pl.q("""
    select k.country_code, t.local_date, count(*) as n_tx, sum(t.amount_usd) as usd,
           any_value(k.iso_weekday) as iso_weekday, any_value(k.is_holiday) as is_holiday,
           any_value(k.is_long_weekend) as is_long_weekend, any_value(k.is_payday) as is_payday,
           any_value(k.days_since_payday) as days_since_payday, any_value(k.is_month_end) as is_month_end,
           any_value(k.is_bonus_month) as is_bonus_month
    from main.tx_local t join main.calendar_local k
      on k.country_code = t.customer_country_code and k.local_date = t.local_date
    group by 1, 2 order by 1, 2""")
daily["local_date"] = pd.to_datetime(daily.local_date)
daily = country.full_months(daily)
FE = " + C(country_code)" if daily.country_code.nunique() > 1 else ""
daily["log_n"] = np.log(daily.n_tx)
daily["t"] = (daily.local_date - daily.local_date.min()).dt.days / 365.25
daily["payday_window"] = daily.days_since_payday.fillna(99) <= 2
for c in ["is_holiday", "is_long_weekend", "is_month_end", "is_bonus_month", "payday_window"]:
    daily[c] = daily[c].astype(int)
model = smf.ols(
    "log_n ~ C(iso_weekday) + is_holiday + is_long_weekend + payday_window + is_month_end + "
    "is_bonus_month + t" + FE,
    data=daily,
).fit(cov_type="HC3")
coef = pd.DataFrame(
    {
        "coef": model.params,
        "ci_low": model.conf_int()[0],
        "ci_high": model.conf_int()[1],
        "p_value": model.pvalues,
    }
).drop("Intercept")
coef["effect %"] = (100 * (np.exp(coef.coef) - 1)).round(1)
coef.assign(country=COUNTRY, dataset=DATASET, r2=model.rsquared).rename_axis(
    "term"
).reset_index().to_csv(OUT / f"{PREFIX}_{COUNTRY.lower()}_calendar_effects.csv", index=False)
show(coef.round(4), paging=False)
print(
    f"R² = {model.rsquared:.3f} on {int(model.nobs)} (country, day) rows, {daily.local_date.min().date()} to {daily.local_date.max().date()}"
)

# %%
eff = coef.reset_index().rename(columns={"index": "term"})
eff["lo %"] = 100 * (np.exp(eff.ci_low) - 1)
eff["hi %"] = 100 * (np.exp(eff.ci_high) - 1)
fig = px.scatter(
    eff,
    x="effect %",
    y="term",
    error_x=eff["hi %"] - eff["effect %"],
    error_x_minus=eff["effect %"] - eff["lo %"],
    title=f"{CTRY.title}: calendar effects on daily volume (95 % CI)",
)
fig.add_vline(x=0, line_dash="dot")
fig.update_layout(height=420, yaxis_title=None)
fig.show()


def says(term: str, label: str) -> str:
    if term not in coef.index:
        return f"{label}: not estimable."
    r = coef.loc[term]
    sig = r.p_value < 0.01
    return f"{label}: **{r['effect %']:+.1f} %** " + (
        "(significant)" if sig else f"(not significant, p = {r.p_value:.2f})"
    )


display(
    Markdown(
        "\n".join(
            [
                "**What the calendar explains in " + CTRY.name + f"** (R² {model.rsquared:.2f}):",
                "* " + says("C(iso_weekday)[T.6]", "Saturday versus Monday"),
                "* " + says("C(iso_weekday)[T.7]", "Sunday versus Monday"),
                "* " + says("is_holiday", "a holiday"),
                "* " + says("payday_window", "the three days after a payday"),
                "* " + says("is_month_end", "month end"),
                "* " + says("is_bonus_month", "bonus month"),
                "* " + says("t", "trend per year"),
            ]
        )
    )
)

# %% [markdown]
# **How to read it.** A real bank would show strong holiday dips (branches and transfers close), payday spikes
# (salaries arrive, bills are paid) and month-end peaks. Effects that are absent or insignificant here are absent from
# the **generator**, not from banking: weekday seasonality is the only calendar structure this synthetic data was built
# with. The enrichment is still right to keep: the same columns will carry signal on real data, and notebook 14 lets
# every model use them.

# %% [markdown]
# ## 4 · The enriched transaction table
# `main.tx_local` is the conformed transaction with local time and calendar: the input of notebooks 09, 13 and 14.
# **Recommendation:** promote `country.calendar` to a dbt seed (`country_calendar.csv`, regenerated yearly) and the
# local columns to `int_transactions_enriched`, so every mart and feature shares one definition of a local day.

# %%
show(
    pl.safe(
        pl.q("""select transaction_id, transaction_ts_utc, ts_customer_local, local_date, local_hour_customer,
                            iso_weekday, is_holiday, holiday_name, is_payday, days_since_payday, is_month_end
                     from main.tx_local where is_holiday limit 8""")
    ),
    paging=False,
)

# %% [markdown]
# ## Findings for All countries and what to do
# The statements computed above are this notebook's findings. Across countries: local time is a fixed offset,
# the calendar is the country's own (bank holidays included), and the regression tells which calendar effects the data
# actually contains before any model is asked to learn them.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
