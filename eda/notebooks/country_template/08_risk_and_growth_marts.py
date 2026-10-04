# %% [markdown]
# # 08 · Risk and growth marts (__COUNTRY_NAME__)
# **Country series · __COUNTRY_NAME__** · *generated from `notebooks/country_template`: edit the template*
#
# Credit eligibility, collections early warning, AML typologies and campaign compliance on __COUNTRY_NAME__ alone
# (pipeline series, notebook 08), with one addition: AML thresholds in the **country's own terms**.

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
country.prepare(pl, "snapshots")
MARTS = [
    "mart_credit_eligibility",
    "mart_collections_early_warning",
    "mart_aml_customer_month",
    "mart_campaign_compliance_uplift",
]
built = pl.build_set(MARTS)

# %% [markdown]
# ## 1 · Credit eligibility

# %%
el = pl.q("""select count(*) as customers, count(*) filter (where len(decline_reasons) = 0) as no_adverse_reason,
                    count(*) filter (where eligible_credit_card) as eligible_card,
                    count(*) filter (where eligible_personal_loan) as eligible_loan
             from {mart_credit_eligibility}""")
show(el, paging=False)
reasons = pl.q("""select r as reason, count(*) as customers,
                         round(100 * count(*) / (select count(*) from {mart_credit_eligibility}), 1) as pct
                  from (select unnest(decline_reasons) as r from {mart_credit_eligibility}) group by 1 order by 2 desc""")
fig = px.bar(
    reasons,
    x="pct",
    y="reason",
    orientation="h",
    title=f"{CTRY.name}: adverse-action reasons (% of customers)",
)
fig.update_layout(height=300, yaxis_title=None, yaxis=dict(autorange="reversed"))
fig.show()
display(
    Markdown(
        f"**{CTRY.name}: {int(el.eligible_card.iloc[0]):,} card and {int(el.eligible_loan.iloc[0]):,} loan approvals out of "
        f"{int(el.customers.iloc[0]):,} customers**; the leading reason is "
        f"{reasons.reason.iloc[0]} ({reasons.pct.iloc[0]} %). Same mechanism as bank-wide: deposit-only, 0.8-a-month "
        "inflows cannot show regular income."
    )
)

# %% [markdown]
# ## 2 · Collections early warning

# %%
show(
    pl.q("""select coalesce(dpd_bucket, '(none)') as dpd_bucket, count(*) as products,
                    round(avg(early_warning_score), 1) as avg_score
             from {mart_collections_early_warning} group by 1 order by 1"""),
    paging=False,
)

# %% [markdown]
# ## 3 · AML: the typologies, and the country's own reporting lines
# The mart's structuring rule counts transactions of 9,000–9,999 **USD**: the United States' cash-reporting line. Each
# country has its own:
# * **Mexico**: "relevant operations" in cash of USD 7,500 or more (or the equivalent) must be reported;
# * **Colombia**: cash transactions of COP 10 million or more are reported to the UIAF (and COP 50 million a month in
#   multiple transactions);
# * **Argentina**: the UIF sets thresholds by resolution and updates them with inflation, so no fixed number is
#   assumed here.
#
# These are the general rules as publicly stated; the operational thresholds must come from compliance in a seed. The
# cell below counts **cash** transactions in the 10 % band just under the country's line, against the mart's USD rule.

# %%
LINES = {"MX": ("USD", 7500.0), "CO": ("COP", 10_000_000.0), "AR": (None, None)}
cur, line = LINES[COUNTRY]
pl.ensure(pl.key("int_transactions_enriched"))
mart_rule = pl.q("""select count(*) as tx_in_9000_9999_usd, count(*) filter (where is_cash) as of_which_cash
                    from {int_transactions_enriched} where amount_usd >= 9000 and amount_usd < 10000""")
show(mart_rule, paging=False)
if line:
    unit = "amount" if cur != "USD" else "amount_usd"
    local = pl.q(f"""select count(*) as cash_tx_in_band,
                            count(distinct customer_id) as customers,
                            count(*) filter (where dq_r18_amount_usd_imputed) as with_imputed_usd
                     from {{int_transactions_enriched}}
                     where is_cash and {unit} >= {0.9 * line} and {unit} < {line}
                       {"and currency = '" + cur + "'" if cur != "USD" else ""}""")
    show(local, paging=False)
    display(
        Markdown(
            f"**{CTRY.name}'s own line ({cur} {line:,.0f} in cash): {int(local.cash_tx_in_band.iloc[0]):,} cash transactions "
            f"sit in the 10 % band below it**, against {int(mart_rule.tx_in_9000_9999_usd.iloc[0]):,} transactions in the "
            "mart's generic 9,000–9,999 USD band. A structuring rule must watch the line the country's regulator actually "
            "uses; the generic band watches the wrong place."
        )
    )
else:
    display(
        Markdown(
            "Argentina's line is inflation-indexed by UIF resolution: the rule must read it from a "
            "compliance seed, updated at every resolution. Hard-coding a number would be wrong within months."
        )
    )

typ = pl.q("""select t as typology, count(*) as customer_months from (select unnest(typology_hits) as t
              from {mart_aml_customer_month}) group by 1 order by 2 desc""")
show(typ, paging=False)
z = pl.q("""select count(*) as customer_months, round(100 * avg((inflow_usd > 0)::int), 1) as with_inflow_pct,
                   count(inflow_robust_z_vs_peers) as defined_peer_z from {mart_aml_customer_month}""")
show(z, paging=False)
display(
    Markdown(
        f"`PEER_OUTLIER_INFLOW` has a defined z-score on {int(z.defined_peer_z.iloc[0]):,} customer-months in {CTRY.name}: "
        + (
            "the rule is dead here too (peer MAD = 0 when most months have no inflow)."
            if z.defined_peer_z.iloc[0] == 0
            else "it can fire here."
        )
    )
)

# %% [markdown]
# ## 4 · Campaigns: consent and attribution

# %%
camp = pl.q("""
    select 'consent' as split, (not sent_without_current_consent)::varchar as value_, count(*) as delivered,
           round(100 * avg(outcome_converted::int), 3) as conversion_pct
    from {mart_campaign_compliance_uplift} where treatment_delivered group by all
    union all
    select 'already holds the product', already_held_promoted_product::varchar, count(*),
           round(100 * avg(outcome_converted::int), 3)
    from {mart_campaign_compliance_uplift} where treatment_delivered group by all""")
show(camp, paging=False)
nc = pl.q(
    "select round(100 * avg(sent_without_current_consent::int), 2) as pct from {mart_campaign_compliance_uplift}"
)
display(
    Markdown(
        f"**{nc.pct.iloc[0]} % of {CTRY.name}'s sends went to customers without current marketing consent.** "
        + {
            "MX": "Mexico's LFPDPPP and the REUS registry of users who refuse advertising make this a direct sanction risk.",
            "CO": "Colombia's Ley 1581 de 2012 (habeas data) requires prior, express consent for marketing use of data.",
            "AR": "Argentina's Ley 25.326 and the Registro Nacional No Llame forbid unsolicited marketing to opted-out persons.",
        }[COUNTRY]
        + " A consent gate in the send pipeline is the first fix in every country."
    )
)

# %% [markdown]
# ## 5 · How strict is the income-history rule here?

# %%
sens = []
for v in (1, 2, 3, 4):
    n = pl.q(f"""select count(*) from {{feat_credit_eligibility_pit}}
                 where snapshot_date = (select max(snapshot_date) from {{feat_credit_eligibility_pit}})
                   and months_with_inflow_6m_pit < {v}""").iloc[0, 0]
    sens.append({"minimum months with inflow (of 6)": v, "customers declined by R04": n})
sens = pd.DataFrame(sens)
sens["pct"] = (100 * sens["customers declined by R04"] / int(el.customers.iloc[0])).round(1)
show(sens, paging=False)

# %% [markdown]
# ## Findings for __COUNTRY_NAME__ and what to do
# The computed statements above. Country-specific: AML lines and consent law are national, so their parameters must be
# country seeds owned by compliance; the bank-wide fixes (dead peer typology, eligibility ordering) apply unchanged.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
