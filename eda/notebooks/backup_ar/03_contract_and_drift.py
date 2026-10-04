# %% [markdown]
# # 03 · The contract, the circuit breaker and schema evolution (Argentina)
# **Backup-as-main series · Argentina** · *generated from `notebooks/country_template`: edit the template*
#
# The circuit breaker holds a day of data when it no longer looks like the contract says it should (pipeline series,
# notebook 03). The contract's **baselines** (how empty each column usually is, the typical magnitude of each
# number) were measured on the three countries together. This notebook asks three questions for Argentina:
# 1. Does the global contract fit the country, or does the breaker misfire?
# 2. If it misfires, what are the right baselines for the country, and how should they be estimated?
# 3. Once the baselines are right, did the country's schema or distributions evolve over three years?

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

COUNTRY = "AR"
DATASET = "backup"
PREFIX = "backup"
CTRY = country.SCOPES[COUNTRY]
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
pl.build_layer("seeds", verbose=False)
pl.ensure(pl.key("dq_partition_profile"))
pl.ensure(pl.key("dq_partition_header"))

# %% [markdown]
# ## 1 · The country judged by the global contract

# %%
glob = country.global_contract_drift(pl)
held_g = (
    glob[glob.severity == "A"]
    .groupby(["table_name", "check_name", "column_name"])
    .partition_date.nunique()
)
held_g = (
    held_g.rename("partitions held").reset_index().sort_values("partitions held", ascending=False)
)
show(held_g, paging=False)
n_held = glob[glob.severity == "A"][["table_name", "partition_date"]].drop_duplicates()
# a baseline check judges a magnitude or a share against the contract's typical value: a population question.
# A rule check (vocabulary, required field, format, key, header, grammar) judges the values or the file against the
# contract's rules: re-fitting baselines cannot release it.
BASELINE = {"scale", "empty_share"}
a = glob[glob.severity == "A"]
structural = a[~a.check_name.isin(BASELINE)][["table_name", "partition_date"]].drop_duplicates()
display(
    Markdown(
        f"**On the global contract, the breaker would hold {len(n_held):,} partitions of {CTRY.name}**"
        + (
            f" ({', '.join(f'{t}: {n}' for t, n in n_held.table_name.value_counts().items())})."
            if len(n_held)
            else "."
        )
        + (
            " The global contract fits."
            if not len(n_held)
            else " Every one is held by a baseline check (scale): nothing changed in the files; the contract describes "
            "another population."
            if not len(structural)
            else f" **{len(structural):,} of them are held by contract rules, not baselines** ("
            + ", ".join(
                f"`{r.table_name}.{r.column_name}` {r.check_name}"
                for r in a[~a.check_name.isin(BASELINE)][
                    ["table_name", "column_name", "check_name"]
                ]
                .drop_duplicates()
                .itertuples()
            )
            + "): the values break the contract's rules, which no baseline can fix. Section 3 shows which holds "
            "survive a contract fitted to this data."
        )
    )
)

# %% [markdown]
# ## 2 · Why: the baselines of a blend are wrong for each country
# The scale check compares each day's median magnitude (log10 of the median absolute value) with the contract's.
# Compare the global baseline with this country's own.

# %%
GLOBAL = country.global_contract(pl)
base = country.country_baselines(pl)
cmp = pl.con.sql(f"""
    select g.table_name, g.column_name, g.scale_log10_median as global_log10_median,
           b.scale_log10_median_country as country_log10_median,
           power(10, b.scale_log10_median_country - g.scale_log10_median) as country_over_global,
           g.scale_mad as global_mad, b.scale_mad_country as country_mad
    from {GLOBAL} g join base b using (table_name, column_name)
    where g.scale_log10_median is not null order by abs(b.scale_log10_median_country - g.scale_log10_median) desc
""").df()
show(cmp.round(3), paging=False)
worst = cmp.iloc[0]
ratio = worst.country_over_global
why = (
    (
        "The magnitudes match the reviewed contract: the scale checks fit."
        if 1 / 3 <= ratio <= 3
        else "The reviewed contract's baselines were measured on main's whole bank; this dataset's typical magnitude "
        "differs from them by that factor, so the scale check misjudges every day of it."
    )
    if COUNTRY == "ALL"
    else "Amounts are recorded in the account's currency; this country's accounts are mostly in a currency worth a "
    "fraction of a dollar, so its amounts are larger numbers than the blend's."
    if ratio > 3
    else "This country's accounts are in dollars: its amounts are smaller numbers than the blend's, which the peso "
    "countries pull upwards."
    if ratio < 1 / 3
    else "The magnitudes are close to the blend: the scale checks fit."
)
display(
    Markdown(
        f"**The largest gap: `{worst.table_name}.{worst.column_name}` is typically {ratio:,.2f}× the global baseline "
        f"in {CTRY.name}.** {why}"
        + (
            " The blend's median sits between populations and describes none of them."
            if COUNTRY != "ALL" and not 1 / 3 <= ratio <= 3
            else ""
        )
    )
)

# %% [markdown]
# ## 3 · Decision: country baselines estimated on a reference window
# **Choice.** Re-estimate each baseline (empty share, median magnitude and its spread) on the country's **first 180
# days** and use those as the country's contract. Three reasons:
# * A drift reference must be fixed *before* the period it monitors; estimating it on the whole history would absorb
#   the very changes it is meant to catch (a unit change in year 3 would move the baseline towards itself).
# * 180 days covers every weekday, month-end and pay cycle at least six times, so the baseline is not one season.
# * The estimators are the contract generator's own (median and median absolute deviation of daily values), robust to
#   the odd day.
#
# The alternatives rejected: widening the thresholds (blind to real unit changes in the low-magnitude country),
# dropping scale checks for amounts (blind to the most expensive producer error), or one contract per currency
# (right in principle, but the source does not split files by currency).

# %%
res = country.apply_country_contract(pl)
pl.build_set(["dq_schema_drift", "dq_partition_releases_active", "dq_partition_holds"])
held = pl.q("select table_name, count(*) as held from {dq_partition_holds} group by 1")
drift = pl.q("""select table_name, column_name, check_name, severity, count(*) as partitions
                from {dq_schema_drift} group by all order by partitions desc""")
show(held, paging=False)
show(drift, paging=False)
display(
    Markdown(
        f"**With baselines fitted to this scope: {int(held.held.sum()) if len(held) else 0} partitions held** (global "
        f"contract: {len(n_held):,}), {int(drift.partitions.sum()) if len(drift) else 0} severity-B reports."
        + (
            " The holds that remain break contract rules, and **staging excludes every held partition**: those days "
            "vanish from silver, gold and every model downstream until someone releases or corrects them."
            if len(held) and held.held.sum()
            else ""
        )
    )
)

# %% [markdown]
# ## 4 · Why small countries get more empty-share reports: sampling noise
# The empty-share check reports a day when its share of empty values moves 30 points from the baseline. On a day with
# `n` rows and a true empty share `p`, the observed share has a standard deviation of `√(p(1−p)/n)`. A small daily
# volume makes a 30-point move a routine fluctuation. The table puts each report in units of that noise.

# %%
noise = pl.q("""
    with d as (select d.table_name, d.column_name, d.partition_date, d.observed
               from {dq_schema_drift} d where d.check_name = 'empty_share'),
         p as (select table_name, column_name, partition_date, n_rows, (n_empty + n_absent) / n_rows as share
               from {dq_partition_profile} where zone = 'bronze')
    select d.table_name, d.column_name, count(*) as reports, round(median(p.n_rows), 0) as median_rows_per_day,
           round(median(c.empty_share), 3) as baseline_share,
           round(median(0.30 / sqrt(greatest(c.empty_share * (1 - c.empty_share), 1e-6) / p.n_rows)), 1)
             as band_in_noise_sd
    from d join p using (table_name, column_name, partition_date)
    join {source_contract_columns} c using (table_name, column_name)
    group by all order by reports desc""")
show(noise, paging=False)

# %% [markdown]
# Read `band_in_noise_sd`: how many standard deviations of pure sampling noise the fixed 30-point band represents on
# a typical day. Below about 3, a report is as likely to be chance as change. **Recommendation for every country:**
# replace the fixed band by a binomial test (report when the observed share is more than 4 standard deviations from the
# baseline, given that day's `n`), and measure emptiness within the rows where the field applies (pipeline series,
# notebook 03). Both changes live in the contract generator.

# %% [markdown]
# ## 5 · Did the country's data evolve? Monthly distribution stability
# Beyond the breaker's daily checks: the **population stability index** (PSI) of key columns, each month against the
# reference window. PSI = Σ (pₘ − p_ref) · ln(pₘ / p_ref) over the categories (or deciles) of a column. The industry
# reading: below 0.10 stable, 0.10–0.25 shifting, above 0.25 a different population.

# %%
pl.ensure(pl.key("stg_transactions"))
tx = pl.q("""select date_trunc('month', transaction_ts_utc) as month, transaction_type, channel, currency,
                    transaction_status, ln(1 + abs(amount)) as log_amount
             from {stg_transactions} where hash(transaction_id) % 4 = 0""")
ref_end = tx.month.min() + pd.DateOffset(months=6)


def psi(ref: pd.Series, cur: pd.Series) -> float:
    a = ref.value_counts(normalize=True)
    b = cur.value_counts(normalize=True)
    idx = a.index.union(b.index)
    a, b = (
        a.reindex(idx).fillna(1e-4).clip(lower=1e-4),
        b.reindex(idx).fillna(1e-4).clip(lower=1e-4),
    )
    return float(((b - a) * np.log(b / a)).sum())


edges = np.quantile(tx.loc[tx.month < ref_end, "log_amount"], np.linspace(0, 1, 11))
tx["amount_decile"] = np.clip(np.searchsorted(edges[1:-1], tx.log_amount), 0, 9)
rows = []
ref = tx[tx.month < ref_end]
for m, cur in tx[tx.month >= ref_end].groupby("month"):
    for col in ["transaction_type", "channel", "currency", "transaction_status", "amount_decile"]:
        rows.append({"month": m, "column": col, "psi": psi(ref[col], cur[col])})
ps = pd.DataFrame(rows)
fig = px.line(
    ps,
    x="month",
    y="psi",
    color="column",
    title=f"{CTRY.title}: PSI of each month against the first 6 months",
)
fig.add_hline(y=0.10, line_dash="dot", annotation_text="0.10 shifting")
fig.add_hline(y=0.25, line_dash="dash", annotation_text="0.25 different population")
fig.update_layout(height=360, xaxis_title=None)
fig.show()
mx = ps.groupby("column").psi.max().sort_values(ascending=False)
pd.DataFrame(
    [
        {
            "country": COUNTRY,
            "dataset": DATASET,
            "partitions_held_global_contract": len(n_held),
            "partitions_held_country_contract": int(held.held.sum()) if len(held) else 0,
            "b_reports_country_contract": int(drift.partitions.sum()) if len(drift) else 0,
            "amount_scale_country_over_global": float(
                cmp.loc[
                    (cmp.table_name == "transactions") & (cmp.column_name == "amount"),
                    "country_over_global",
                ].iloc[0]
            ),
            "max_monthly_psi": float(mx.iloc[0]),
            "max_psi_column": mx.index[0],
        }
    ]
).to_csv(OUT / f"{PREFIX}_{COUNTRY.lower()}_contract.csv", index=False)
show(mx.round(4).rename("max monthly PSI").to_frame(), paging=False)
display(
    Markdown(
        f"**Largest monthly PSI in {CTRY.name}: {mx.iloc[0]:.3f} ({mx.index[0]}).** "
        + (
            f"All columns stay far below 0.10: the population of transactions is stationary over "
            f"{tx.month.nunique()} months. "
            "Stationarity is itself a generator fingerprint: a real bank's channel mix drifts towards digital and its "
            "amounts with inflation."
            if mx.iloc[0] < 0.10
            else "At least one column shifts: inspect the month and column above before training anything on the full window."
        )
    )
)

# %% [markdown]
# ## Findings for Argentina and what to do
# 1. **A bank-wide contract is not a country contract.** Wherever the currency mix differs from the blend, the global
#    scale baseline holds healthy days; the country's own reference-window baselines remove the false holds without
#    blinding the breaker to real unit changes.
# 2. **Production design:** one contract per (table, country) or, better, scale checks per currency inside each table.
# 3. **Empty-share checks need a noise-aware threshold** (binomial z) and applicability conditioning; small countries
#    and small tables suffer most.
# 4. **The country's distributions are stationary** where PSI stays low: a model trained on the first two years can be
#    expected to hold on the third, which notebook 14 tests directly.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
