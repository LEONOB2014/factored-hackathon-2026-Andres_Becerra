# %% [markdown]
# # 14 · Which targets are learnable? Candidate models, out of time (Colombia)
# **Country series · Colombia** · *an additional component of the series; generated from
# `notebooks/country_template`: edit the template*
#
# Every use case the bank wants to automate has a **target**: a column a model would predict. Before building any
# model, a model-risk function asks whether the target can be predicted **at all** from information available at
# decision time. This notebook answers that for seven candidate targets in Colombia, with one protocol:
#
# * **Point-in-time features only** (nothing known after the decision moment), including the country's calendar.
# * **Out-of-time split**: train on the earliest 75 % of the period, test on the latest 25 %. A model is used on the
#   future, so it is judged on the future.
# * **Gradient boosting** (scikit-learn `HistGradientBoostingClassifier`): strong on tabular data, native missing
#   values and categories, class weights for rare targets. If boosting finds nothing, simpler models will not.
# * **Metrics with uncertainty**: test ROC AUC with a Hanley–McNeil 95 % interval; average precision (AP) with a
#   bootstrap interval, read against the base rate (AP lift = AP / base rate; a random ranking has lift 1).
# * **Verdict**: no evidence (the AUC interval contains 0.5), weak (rules, not models), moderate, or learnable.
#
# | target | decision it would support | unit |
# |---|---|---|
# | fraud, honest | block or review a payment | transaction |
# | fraud, with `fraud_score` | (leakage demonstration: never deploy) | transaction |
# | complaint in the next 90 days | proactive service outreach | customer × quarter |
# | dormant in the next 90 days | retention offer | customer × quarter |
# | more than 30 days past due | collections priority | credit product |
# | campaign conversion | whom to contact | send |
# | complaint within 14 days of a contact | escalation prevention | contact |

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme

COUNTRY = "CO"
DATASET = "main"
PREFIX = "country"
CTRY = country.SCOPES[COUNTRY]
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "features_graph_knowledge")
country.enrich_transactions(pl)
results = []


def run(name: str, df: pd.DataFrame, target: str, time_col: str, features: list[str]) -> None:
    t = time.time()
    r = country.evaluate_target(df, target, time_col, features)
    r["name"] = name
    r["verdict"] = country.verdict(r)
    r["seconds"] = round(time.time() - t, 1)
    results.append(r)
    imp = ", ".join(f"{k} ({v:+.3f})" for k, v in list((r.get("importance") or {}).items())[:5])
    display(
        Markdown(
            f"**{name}**: test AUC {r['auc']:.3f} [{r['auc_lo']:.3f}, {r['auc_hi']:.3f}], AP {r['ap']:.4f} against a base "
            f"rate of {r['base_rate']:.4f} (lift {r['ap_lift']:.2f}) → **{r['verdict']}**. "
            + (f"Most important (permutation, AUC drop): {imp}. " if imp else "")
            + (
                f"Features with no value in this dataset, dropped: {r['dropped_empty_features']}. "
                if r.get("dropped_empty_features")
                else ""
            )
            + (
                f"The best single feature alone (`{r['best_single_feature']}`, either direction) reaches AUC "
                f"{r['best_single_auc']:.3f}: the model adds {r['auc'] - r['best_single_auc']:+.3f}."
                if r.get("best_single_feature")
                else ""
            )
            if np.isfinite(r.get("auc", np.nan))
            else f"**{name}**: {r['note']}."
        )
    )


CAL = [
    "local_hour_customer",
    "iso_weekday",
    "is_holiday",
    "is_long_weekend",
    "is_payday",
    "days_since_payday",
    "is_month_end",
    "is_bonus_month",
]

# %% [markdown]
# ## 1 · Fraud, honestly (point-in-time behaviour + calendar), and with the leaking score

# %%
fr = pl.q("""
    select f.* exclude (customer_id, product_id, transaction_id, last_login_ip_country),
           t.local_hour_customer, t.iso_weekday, t.is_holiday, t.is_long_weekend, t.is_payday, t.days_since_payday,
           t.is_month_end, t.is_bonus_month, e.fraud_score
    from {feat_fraud_realtime_pit} f join main.tx_local t using (transaction_id)
    join {int_transactions_enriched} e using (transaction_id)
    where f.split in ('train', 'valid', 'test')""")
FR = [
    c
    for c in fr.columns
    if c not in ("anchor_ts", "split", "label_is_fraud", "fraud_score", "local_hour")
]
run("fraud (honest)", fr, "label_is_fraud", "anchor_ts", FR)
run("fraud with fraud_score (leak)", fr, "label_is_fraud", "anchor_ts", [*FR, "fraud_score"])

# %% [markdown]
# ## 2 · Complaint in the next 90 days and dormancy in the next 90 days
# Unit: customer × quarter start (the cutoffs of `ml_kumo_relational_complaint90d`). Features are computed from monthly
# aggregates **strictly before the cutoff** (transactions, contacts, sentiment, prior complaints, digital activity,
# products, tenure, segment). The dormancy label: no transaction in the 90 days after the cutoff, among customers
# active in the 180 days before it.

# %%
pl.con.sql(f"""
    create or replace temp table cut as
    select customer_id, cutoff_ts::date as cutoff, label_complaint_90d, segment, tenure_days_at_cutoff
    from {pl.relation(pl.key("ml_kumo_relational_complaint90d"))}""")
pl.con.sql(f"""
    create or replace temp table cc_m as
    select customer_id, date_trunc('month', interaction_ts_utc)::date as m, count(*) as contacts,
           count(*) filter (where was_escalated) as escalations, count(*) filter (where not was_resolved) as unresolved,
           avg(sentiment_score) as sentiment
    from {pl.relation(pl.key("stg_call_center_interactions"))} group by all""")
pl.con.sql(f"""
    create or replace temp table cp_m as
    select customer_id, date_trunc('month', created_ts_utc)::date as m, count(*) as complaints
    from {pl.relation(pl.key("stg_complaints"))} group by all""")
pl.con.sql(f"""
    create or replace temp table dg_m as
    select customer_id, date_trunc('month', event_ts_utc)::date as m, count(*) as events,
           count(*) filter (where event_type = 'Error') as errors, count(distinct session_id) as sessions
    from {pl.relation(pl.key("stg_digital_events"))} where customer_id is not null group by all""")
cust = pl.con.sql(f"""
    with tx as (select c.customer_id, c.cutoff,
                       sum(g.n_tx) filter (where g.month_start >= c.cutoff - interval 3 month) as tx_3m,
                       sum(g.n_tx) as tx_6m, sum(g.outflow_usd) as outflow_6m, sum(g.inflow_usd) as inflow_6m,
                       sum(g.insufficient_funds_declines) as nsf_6m, max(g.month_start) filter (where g.n_tx > 0) as last_active_month
                from cut c join {pl.relation(pl.key("int_customer_month_tx"))} g
                  on g.customer_id = c.customer_id and g.month_start < c.cutoff and g.month_start >= c.cutoff - interval 6 month
                group by all),
         fut as (select c.customer_id, c.cutoff, sum(g.n_tx) as tx_next_3m
                 from cut c join {pl.relation(pl.key("int_customer_month_tx"))} g
                   on g.customer_id = c.customer_id and g.month_start >= c.cutoff and g.month_start < c.cutoff + interval 3 month
                 group by all),
         cc as (select c.customer_id, c.cutoff, sum(x.contacts) as contacts_3m, sum(x.escalations) as escalations_3m,
                       sum(x.unresolved) as unresolved_3m, avg(x.sentiment) as sentiment_3m
                from cut c join cc_m x on x.customer_id = c.customer_id and x.m < c.cutoff and x.m >= c.cutoff - interval 3 month
                group by all),
         cp as (select c.customer_id, c.cutoff, sum(x.complaints) as complaints_12m
                from cut c join cp_m x on x.customer_id = c.customer_id and x.m < c.cutoff and x.m >= c.cutoff - interval 12 month
                group by all),
         dg as (select c.customer_id, c.cutoff, sum(x.events) as events_3m, sum(x.errors) as errors_3m, sum(x.sessions) as sessions_3m
                from cut c join dg_m x on x.customer_id = c.customer_id and x.m < c.cutoff and x.m >= c.cutoff - interval 3 month
                group by all)
    select c.*, p.credit_score, p.monthly_income_usd, p.age_years,
           coalesce(tx.tx_3m, 0) as tx_3m, coalesce(tx.tx_6m, 0) as tx_6m, coalesce(tx.outflow_6m, 0) as outflow_6m,
           coalesce(tx.inflow_6m, 0) as inflow_6m, coalesce(tx.nsf_6m, 0) as nsf_6m,
           date_diff('month', tx.last_active_month, c.cutoff) as months_since_active,
           coalesce(cc.contacts_3m, 0) as contacts_3m, coalesce(cc.escalations_3m, 0) as escalations_3m,
           coalesce(cc.unresolved_3m, 0) as unresolved_3m, cc.sentiment_3m,
           coalesce(cp.complaints_12m, 0) as complaints_12m, coalesce(dg.events_3m, 0) as events_3m,
           coalesce(dg.errors_3m, 0) as errors_3m, coalesce(dg.sessions_3m, 0) as sessions_3m,
           coalesce(fut.tx_next_3m, 0) = 0 as dormant_next_90d, coalesce(tx.tx_6m, 0) > 0 as active_before
    from cut c join {pl.relation(pl.key("int_customer_profile"))} p using (customer_id)
    left join tx using (customer_id, cutoff) left join fut using (customer_id, cutoff)
    left join cc using (customer_id, cutoff) left join cp using (customer_id, cutoff)
    left join dg using (customer_id, cutoff)""").df()
CF = [
    "segment",
    "tenure_days_at_cutoff",
    "credit_score",
    "monthly_income_usd",
    "age_years",
    "tx_3m",
    "tx_6m",
    "outflow_6m",
    "inflow_6m",
    "nsf_6m",
    "months_since_active",
    "contacts_3m",
    "escalations_3m",
    "unresolved_3m",
    "sentiment_3m",
    "complaints_12m",
    "events_3m",
    "errors_3m",
    "sessions_3m",
]
run("complaint in next 90 days", cust, "label_complaint_90d", "cutoff", CF)
# a dormancy label needs the whole 90-day future observed: a cutoff whose window passes the last transaction would
# call every customer dormant because the data stops, not because the customer did
tx_end = pd.Timestamp(
    pl.q("select max(transaction_ts_utc) as m from {int_transactions_enriched}").m.iloc[0]
)
observed = pd.to_datetime(cust.cutoff) + pd.Timedelta(days=90) <= tx_end
censored = sorted(pd.to_datetime(cust.loc[~observed, "cutoff"]).dt.date.unique())
display(
    Markdown(
        f"Dormancy cutoffs whose 90-day window ends after the last transaction ({tx_end.date()}) are dropped: "
        + (", ".join(str(c) for c in censored) if censored else "none")
        + "."
    )
)
act = cust[cust.active_before & observed].copy()
run(
    "dormant in next 90 days",
    act,
    "dormant_next_90d",
    "cutoff",
    [c for c in CF if c != "months_since_active"],
)

# %% [markdown]
# **A note on current-state attributes.** Credit score and income come from today's profile (no history exists yet),
# so for past cutoffs they are mild leaks at worst. They are kept because a deployed model would read the same current
# values; the permutation importances show whether the verdict rests on them or on the behavioural aggregates.

# %% [markdown]
# ## 3 · More than 30 days past due (credit products)
# Cross-sectional: the current delinquency of each loan and credit card, predicted from the product, the customer and
# their behaviour in the 6 months **before** the snapshot. Split by product vintage (older products train, newer test).

# %%
dq = pl.q("""
    with b as (select customer_id, avg(outflow_usd) as avg_outflow_6m, avg(inflow_usd) as avg_inflow_6m,
                      avg(payments_usd) as avg_payments_6m, sum(insufficient_funds_declines) as nsf_6m,
                      count(*) filter (where inflow_usd > 0) as months_with_inflow_6m
               from {int_customer_month_tx} where month_start >= date '2025-11-01' group by 1)
    select p.product_family, p.currency, p.credit_limit_usd, p.interest_rate, p.opening_date,
           date_diff('day', p.opening_date, date '2026-05-17') as product_age_days,
           c.credit_score, c.monthly_income_usd, c.segment, c.tenure_days, c.age_years,
           b.avg_outflow_6m, b.avg_inflow_6m, b.avg_payments_6m, b.nsf_6m, b.months_with_inflow_6m,
           p.days_past_due > 30 as dpd_over_30
    from {int_products_enriched} p join {int_customer_profile} c using (customer_id) left join b using (customer_id)
    where p.product_family in ('loan', 'credit_card') and p.days_past_due is not null""")
DF = [
    "product_family",
    "currency",
    "credit_limit_usd",
    "interest_rate",
    "product_age_days",
    "credit_score",
    "monthly_income_usd",
    "segment",
    "tenure_days",
    "age_years",
    "avg_outflow_6m",
    "avg_inflow_6m",
    "avg_payments_6m",
    "nsf_6m",
    "months_with_inflow_6m",
]
run("more than 30 days past due", dq, "dpd_over_30", "opening_date", DF)

# %% [markdown]
# Balance and utilisation are deliberately **excluded**: they are measured at the same moment as the delinquency and
# partly caused by it (unpaid interest grows a balance), which would make the target look predictable for the wrong
# reason.

# %% [markdown]
# ## 4 · Campaign conversion

# %%
camp = pl.q("""
    select m.send_ts_utc, m.send_channel, m.campaign_objective, m.promoted_product, m.target_segment, m.segment,
           m.target_segment = m.segment as segment_match, m.prior_sends_7d, m.prior_sends_30d,
           m.accepts_marketing_current, m.already_held_promoted_product, m.send_cost,
           k.iso_weekday, k.is_holiday, k.is_payday, k.days_since_payday, k.is_month_end, m.outcome_converted
    from {mart_campaign_compliance_uplift} m
    left join main.customer_local cl on cl.customer_id = m.customer_id
    left join main.calendar_local k
      on k.country_code = cl.country_code and k.local_date = cast(m.send_ts_utc + to_hours(cl.utc_offset) as date)
    where m.treatment_delivered""")
MF = [
    "send_channel",
    "campaign_objective",
    "promoted_product",
    "target_segment",
    "segment",
    "segment_match",
    "prior_sends_7d",
    "prior_sends_30d",
    "accepts_marketing_current",
    "already_held_promoted_product",
    "send_cost",
    "iso_weekday",
    "is_holiday",
    "is_payday",
    "days_since_payday",
    "is_month_end",
]
run("campaign conversion", camp, "outcome_converted", "send_ts_utc", MF)

# %% [markdown]
# A conversion model, even a learnable one, is **not** an uplift model: it predicts who converts, not who converts
# *because of* the send. Without a randomised holdout the causal effect stays unidentified (pipeline series, notebook 08).

# %% [markdown]
# ## 5 · Complaint within 14 days of a contact (escalation)

# %%
CONTACT_DAY = country.utc_offset(
    "MX", process="call_center_interactions"
)  # contacts' delivery day: ts − 8 h
cx = pl.q(f"""
    select j.interaction_ts_utc, j.interaction_type, j.channel, j.contact_reason, j.duration_seconds,
           j.wait_time_seconds, j.was_resolved, j.was_escalated, j.requires_followup, j.sentiment_score,
           j.prior_contacts_30d, j.agent_experience_level, j.agent_type, j.accent_matched,
           k.iso_weekday, k.is_holiday, j.complaint_within_14d
    from {{mart_cx_journey}} j
    left join main.customer_local cl on cl.customer_id = j.customer_id
    left join main.calendar_local k
      on k.country_code = cl.country_code
     and k.local_date = cast(j.interaction_ts_utc + to_hours({CONTACT_DAY}) as date)""")
XF = [
    "interaction_type",
    "channel",
    "contact_reason",
    "duration_seconds",
    "wait_time_seconds",
    "was_resolved",
    "was_escalated",
    "requires_followup",
    "sentiment_score",
    "prior_contacts_30d",
    "agent_experience_level",
    "agent_type",
    "accent_matched",
    "iso_weekday",
    "is_holiday",
]
run("complaint within 14 days of a contact", cx, "complaint_within_14d", "interaction_ts_utc", XF)

# %% [markdown]
# ## 6 · The learnability map of Colombia

# %%
res = pd.DataFrame(results)
res.insert(0, "country", COUNTRY)
res.insert(1, "dataset", DATASET)
cols = [
    "country",
    "dataset",
    "name",
    "train_rows",
    "test_rows",
    "test_positives",
    "base_rate",
    "auc",
    "auc_lo",
    "auc_hi",
    "ap",
    "ap_lo",
    "ap_hi",
    "ap_lift",
    "best_single_feature",
    "best_single_auc",
    "verdict",
    "split_at",
    "dropped_empty_features",
]
res[cols].to_csv(OUT / f"{PREFIX}_{COUNTRY.lower()}_learnability.csv", index=False)
show(res[cols].round(4), paging=False)
fig = go.Figure()
ok = res[np.isfinite(res.auc)]
fig.add_trace(
    go.Scatter(
        x=ok.auc,
        y=ok.name,
        mode="markers",
        error_x=dict(
            type="data", symmetric=False, array=ok.auc_hi - ok.auc, arrayminus=ok.auc - ok.auc_lo
        ),
        marker=dict(size=10),
    )
)
fig.add_vline(x=0.5, line_dash="dot")
fig.update_layout(
    title=f"{CTRY.title}: out-of-time test AUC per candidate target (95 % CI)",
    height=380,
    yaxis_title=None,
    xaxis_range=[0.3, 1.0],
)
fig.show()

# %% [markdown]
# **How to read the map.**
# * **Fraud with `fraud_score`** sits near the top for the wrong reason: the score produces the label. It is the
#   control that proves the evaluation can detect signal when there is some; the honest fraud row is the answer.
# * A target whose interval contains 0.5 cannot be served by any model on this data, however sophisticated: the
#   deliverable for it is a rule set plus the data collection that would make it learnable (labels, history, keys).
# * A learnable target gets a model card, a monitoring plan (AP on recent labels, PSI of the inputs, notebook 03) and a
#   champion–challenger rollout. A moderate one gets more data before a model.

# %%
display(
    Markdown(
        "**Verdicts for "
        + CTRY.name
        + ":**\n"
        + "\n".join(f"* {r.name}: {r.verdict}" for r in res.itertuples())
    )
)
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
