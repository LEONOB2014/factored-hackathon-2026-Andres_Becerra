# %% [markdown]
# # 02 · Bronze to typed silver (__COUNTRY_NAME__)
# **Country series · __COUNTRY_NAME__** · *generated from `notebooks/country_template`: edit the template*
#
# The typed views cast every bronze text field against the reviewed source contract and record each breaking cell in
# `_dq_issues` instead of dropping it (pipeline series, notebook 02). Here: which contract findings exist **in this
# country**, and whether the country's own vocabulary and emptiness patterns differ from the bank's.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme

COUNTRY = "__COUNTRY__"
CTRY = country.COUNTRIES[COUNTRY]
theme.register()
t0 = time.time()
pl = country.session(COUNTRY)
pl.build_layer("seeds", verbose=False)
TYPED = sorted(n for n in pl.catalog()["node"] if n.startswith("typed_"))
built = pl.build_set(["dq_corrections_active", *TYPED])
pl.ensure(pl.key("dq_partition_profile"))

# %% [markdown]
# ## 1 · Clean versus flagged rows

# %%
rows = []
for t in TYPED:
    r = pl.q(f"""select count(*) as n_rows, count(*) filter (where len(_dq_issues) > 0) as flagged
                 from {{{t}}}""").iloc[0]
    rows.append({"typed view": t, "rows": int(r.n_rows), "flagged": int(r.flagged)})
surv = pd.DataFrame(rows)
surv["flagged %"] = (100 * surv.flagged / surv.rows.where(surv.rows > 0)).round(3)
show(surv, paging=False)

issues = pl.q(
    " union all ".join(
        f"select '{t.removeprefix('typed_')}' as table_name, split_part(i, ':', 1) as column_name, "
        f"split_part(i, ':', 2) as code, count(*) as cells from (select unnest(_dq_issues) as i from {{{t}}}) group by all"
        for t in TYPED
    )
).sort_values("cells", ascending=False)
show(issues, paging=False)
total = surv.rows.sum()
display(
    Markdown(
        f"**{CTRY.name}: {surv.flagged.sum():,} flagged rows of {total:,} ({100 * surv.flagged.sum() / total:.2f} %), "
        f"{len(issues)} distinct (table, column, code) findings.** "
        + (
            "None beyond the bank-wide three."
            if len(issues) <= 5
            else "More findings than bank-wide: inspect below."
        )
    )
)

# %% [markdown]
# ## 2 · The "Mexico" spelling in this country
# Bank-wide, `Mexico` (without the accent) turned out to be the generator's foreign-destination label in transactions
# and the anonymous-traffic label in digital events. What it is here:

# %%
tx = pl.q("""select transaction_country, count(*) as transactions from {typed_transactions}
             group by 1 order by 2 desc""")
show(tx, paging=False)
ev = pl.q("""select customer_id is null as anonymous, ip_country, count(*) as events from {typed_digital_events}
             group by all order by 1, 2""")
show(ev, paging=False)
n_mex = int(tx.loc[tx.transaction_country == "Mexico", "transactions"].sum())
n_home = int(tx.loc[tx.transaction_country.isin(CTRY.raw_names), "transactions"].sum())
foreign = tx[~tx.transaction_country.isin(CTRY.raw_names)]
display(
    Markdown(
        f"**Transactions:** {n_home:,} in {CTRY.name} itself, {foreign.transactions.sum():,} abroad "
        f"({100 * foreign.transactions.sum() / tx.transactions.sum():.1f} %), spread evenly over "
        f"{len(foreign)} destinations. "
        + (
            f"Here `Mexico` (no accent) is a **foreign destination** for {CTRY.name}'s customers ({n_mex:,} rows), counted "
            "like USA, Spain or Brazil: correcting it to `México` changes nothing (both map to MX)."
            if COUNTRY != "MX"
            else f"For Mexican customers, `Mexico` (no accent, {n_mex:,} rows) is the generator's foreign label landing on "
            "their own country: staging maps it to MX, which makes those transactions domestic, as they geographically are."
        )
    )
)
anon = ev[ev.anonymous]
display(
    Markdown(
        f"**Digital events:** {int(ev[~ev.anonymous].events.sum()):,} identified, {int(anon.events.sum()):,} anonymous "
        f"({100 * anon.events.sum() / ev.events.sum():.1f} %), attributed by IP country. "
        + (
            "The anonymous traffic arrives under both spellings, `México` and `Mexico`: the IP attribution needed both "
            "names, which is why the cut lists every spelling of a country."
            if COUNTRY == "MX"
            else "Identified customers never log in from another country here either: login-country features stay silent."
        )
    )
)

# %% [markdown]
# ## 3 · Emptiness: where this country differs from the bank
# Share of empty values per column in this country, against the global contract's `empty_share`. A large gap means
# the column is used differently here (a product mix, a channel mix, a process) and the global baseline will
# misfire on this country's days.

# %%
GLOBAL = country.global_contract(pl)
emp = pl.q(f"""
    with p as (select table_name, column_name, sum(n_empty + n_absent) / sum(n_rows) as country_empty
               from {{dq_partition_profile}} where zone = 'bronze' group by 1, 2)
    select p.table_name, p.column_name, round(100 * p.country_empty, 2) as country_empty_pct,
           round(100 * c.empty_share, 2) as contract_empty_pct,
           round(100 * (p.country_empty - c.empty_share), 2) as gap_points
    from p join {GLOBAL} c using (table_name, column_name)
    where abs(p.country_empty - c.empty_share) >= 0.02
    order by abs(p.country_empty - c.empty_share) desc""")
show(emp, paging=False)
if len(emp):
    fig = px.bar(
        emp.head(20),
        x="gap_points",
        y=emp.head(20).table_name + "." + emp.head(20).column_name,
        orientation="h",
        title=f"Columns whose emptiness in {CTRY.name} differs from the contract (points)",
    )
    fig.update_layout(height=520, yaxis_title=None, yaxis=dict(autorange="reversed"))
    fig.show()
display(
    Markdown(
        f"**{len(emp)} columns differ from the contract's empty share by 2 points or more in {CTRY.name}.** "
        "These are the columns where a bank-wide baseline cannot describe this country; notebook 03 re-estimates "
        "them on the country's reference window."
    )
)

# %% [markdown]
# ## Findings for __COUNTRY_NAME__ and what to do
# * The country's contract findings are the bank's (variant spellings, `nan` subjects) in the country's proportion:
#   typing is structurally clean everywhere, so no country needs its own typing rules.
# * Emptiness differs by country where the product or channel mix differs: those baselines are re-based in notebook 03.
# * Raw country text is never a feature: use the ISO codes from staging.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
