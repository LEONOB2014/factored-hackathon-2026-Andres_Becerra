# %% [markdown]
# # 07 · Service marts (Argentina)
# **Country series · Argentina** · *generated from `notebooks/country_template`: edit the template*
#
# The marts of the service copilot (customer 360, inquiries, card support, disputes, CX journey), built on
# Argentina alone (pipeline series, notebook 07). The questions: how the country's customers use the bank,
# what the deterministic rules decide for them, and whether the bank-wide defects (fraud wording, dispute candidates)
# look the same here.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme

COUNTRY = "AR"
DATASET = "main"
PREFIX = "country"
CTRY = country.SCOPES[COUNTRY]
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "snapshots")
MARTS = [
    "mart_customer_360",
    "mart_product_recent_transactions",
    "mart_account_payment_inquiry",
    "mart_card_support",
    "mart_transaction_disputes",
    "mart_cx_journey",
]
built = pl.build_set(MARTS)

# %% [markdown]
# ## 1 · Customer 360

# %%
c360 = pl.q("""select count(*) as customers, round(avg(tx_count_90d), 2) as avg_tx_90d,
                      round(100 * avg((tx_count_90d = 0)::int), 1) as no_tx_90d_pct,
                      round(median(days_since_last_tx), 0) as median_days_since_last_tx,
                      round(100 * avg((sessions_90d = 0)::int), 1) as no_digital_90d_pct,
                      round(100 * avg((contacts_90d > 0)::int), 1) as contacted_90d_pct,
                      round(avg(n_products), 2) as products_per_customer
               from {mart_customer_360}""")
show(c360, paging=False)
seg = pl.q("""select segment, count(*) as customers, round(avg(tx_count_365d), 1) as tx_365d,
                     round(median(deposits_usd), 0) as median_deposits_usd, round(avg(complaints_365d), 3) as complaints_365d
              from {mart_customer_360} group by 1 order by 2 desc""")
show(seg, paging=False)

# %% [markdown]
# ## 2 · Cards: next best action

# %%
nba = pl.q(
    "select next_best_action, count(*) as cards from {mart_card_support} group by 1 order by 2 desc"
)
nba["share %"] = (100 * nba.cards / nba.cards.sum()).round(2)
fig = px.bar(
    nba,
    x="cards",
    y="next_best_action",
    orientation="h",
    title=f"{CTRY.title}: next best action per card",
)
fig.update_layout(height=300, yaxis_title=None, yaxis=dict(autorange="reversed"))
fig.show()
show(nba, paging=False)

# %% [markdown]
# ## 3 · Disputes

# %%
dis = pl.q("""
    with d as (select * from {stg_complaints}
               where category in ('Transactions', 'Fees') or subcategory in ('Cargo no reconocido', 'Cobro indebido')),
    c as (select d.complaint_id, d.affected_product_id is not null as names_a_product,
                 count(t.transaction_id) as in_window
          from d left join {fct_transaction} t on t.customer_id = d.customer_id
           and t.transaction_ts_utc between d.created_ts_utc - interval 60 day and d.created_ts_utc group by all)
    select c.names_a_product, count(*) as disputes, count(*) filter (where in_window > 0) as with_transactions_in_window,
           count(*) filter (where m.linked_transaction_id is not null) as with_candidate,
           count(*) filter (where m.link_confidence in ('high', 'medium')) as linked_medium_or_better
    from c join {mart_transaction_disputes} m using (complaint_id) group by 1""")
show(dis, paging=False)
lost = dis[dis.names_a_product]
if len(lost):
    display(
        Markdown(
            f"**{int(lost.with_transactions_in_window.iloc[0]):,} of {CTRY.name}'s disputes had transactions in the window "
            f"but only {int(lost.with_candidate.iloc[0]):,} keep a candidate**: the filter trusts the complaint's product, "
            "which belongs to another customer (often in another country, notebook 05). Same defect, same fix as bank-wide."
        )
    )
show(
    pl.q("""select count(*) as disputes, count(*) filter (where came_via_regulator) as via_regulator,
                    round(100 * avg(sla_breached::int), 1) as sla_breached_pct,
                    round(median(hours_to_first_response), 0) as median_hours_to_first_response
             from {mart_transaction_disputes}"""),
    paging=False,
)
reg = {
    "MX": "CONDUSEF (Mexico): the bank must answer a complaint within 30 business days, and a disputed card charge "
    "within 45 days",
    "CO": "the Superintendencia Financiera (Colombia): 15 business days for a petition or complaint (Ley 1755 "
    "de 2015), with the consumer ombudsman as a second instance",
    "AR": "the BCRA (Argentina): 10 business days for a complaint, extendable once",
}
display(
    Markdown(
        f"**Regulatory clock for {CTRY.name}:** "
        + (reg[COUNTRY] if COUNTRY != "ALL" else "; ".join(reg.values()))
        + ". The mart computes generic SLA clocks; the recommendation "
        "stands: a compliance-owned seed of deadlines per country, so a breach is measured against this country's rule. "
        "(The deadlines quoted are the general rules; compliance must confirm them per product and case type.)"
    )
)

# %% [markdown]
# ## 4 · CX journey

# %%
cx = pl.q("""select contact_reason, count(*) as contacts, round(100 * avg(was_resolved::int), 1) as resolved_pct,
                    round(100 * avg(repeat_contact_7d::int), 2) as repeat_7d_pct,
                    round(100 * avg(complaint_within_14d::int), 2) as complaint_14d_pct,
                    round(avg(sentiment_score), 3) as sentiment
             from {mart_cx_journey} group by 1 order by 2 desc""")
show(cx, paging=False)
display(
    Markdown(
        "Complaint contacts resolve far less often at first contact than transactional ones in every country; the labels "
        "for an escalation model (`complaint_within_14d`) are rare, and notebook 14 tests whether they are learnable here."
        if len(cx)
        else "**The CX journey is empty**: "
        + country.why_empty(pl, "call_center_interactions")
        + ". Every contact-centre mart, label and SLA of this dataset is empty with it."
    )
)

# %% [markdown]
# ## Findings for Argentina and what to do
# The computed statements above, plus the bank-wide recommendations that apply unchanged: rename the fraud columns,
# do not block cards on the legacy flag, fix the dispute candidate filter, capture the disputed transaction at intake,
# and measure SLAs against this country's regulator.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
