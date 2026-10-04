# %% [markdown]
# # 07 · Service marts: customer 360, inquiries, cards, disputes, CX
# **Pipeline series** · task group `gold`, part 2: the marts behind the service copilot (bundle B1)
#
# ## What a mart is for
# A mart answers **one family of questions with one read**: "what is my balance and why was my payment
# declined?", "what should the agent do with this card?", "which transaction is this complaint about?". It is
# denormalised on purpose (one row per product, card, complaint or contact, with everything the answer needs),
# windowed relative to `as_of_date` (2026-05-17, the last historical day), and **deterministic**: an LLM copilot may
# phrase the answer, but it never computes a balance or decides an action. Every number it says traces to a row here.
#
# | mart | grain | question family |
# |---|---|---|
# | `mart_customer_360` | customer | who is this customer, what do they hold, how do they behave |
# | `mart_account_payment_inquiry` + `mart_product_recent_transactions` | product / product × rank | balances, payments, declines, recent movements |
# | `mart_card_support` | card | block, unblock, reissue, limits: a rule-based next best action |
# | `mart_transaction_disputes` | dispute | which transaction is disputed, SLA clocks, evidence |
# | `mart_cx_journey` | contact | first-contact resolution, escalation, transcript, survey |

# %%
import sys
import time

sys.path.insert(0, "../../src")
import ipywidgets as w
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import pipeline as pipe
from latam_eda import theme

theme.register()
t0 = time.time()
pl = pipe.session()
pl.ensure_until("snapshots")
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
# ## 1 · `mart_customer_360`: one row per customer
# Seven left-joined aggregates (products, transactions, digital, contact centre, complaints, marketing, surveys) on the
# pseudonymised profile. Two imputation decisions are visible in every column:
# * **counts and sums become 0** when there is no activity (`coalesce(tx.tx_count_90d, 0)`): no transaction is zero
#   transactions;
# * **rates and "last" values stay NULL** (`decline_rate_90d`, `last_tx_ts`): a decline rate over zero transactions is
#   undefined, and 0 % would claim a customer with no attempts never gets declined.

# %%
c360 = pl.q("""
    select count(*) as customers, round(avg(tx_count_90d), 2) as avg_tx_90d,
           round(100 * avg((tx_count_90d = 0)::int), 1) as no_tx_90d_pct,
           round(100 * avg((decline_rate_90d is null)::int), 1) as decline_rate_null_pct,
           round(median(days_since_last_tx), 0) as median_days_since_last_tx,
           round(100 * avg((sessions_90d = 0)::int), 1) as no_digital_90d_pct,
           round(100 * avg((contacts_90d > 0)::int), 1) as contacted_90d_pct,
           count(*) filter (where confirmed_fraud_365d > 0) as customers_with_fraud_label_365d
    from {mart_customer_360}""")
show(c360, paging=False)
dist = pl.q(
    "select least(tx_count_90d, 12) as tx_90d, count(*) as customers from {mart_customer_360} group by 1"
)
fig = px.bar(
    dist.sort_values("tx_90d"),
    x="tx_90d",
    y="customers",
    title="Transactions in the 90 days before as_of (12 = 12 or more)",
)
fig.update_layout(height=300)
fig.show()

# %% [markdown]
# **Reading.** In the last 90 days the average customer made 2.5 transactions and 22 % made none. The 360 is a thin
# profile: good for "what do you hold and how can we help", weak for behavioural scoring.
#
# **A naming problem to fix.** `confirmed_fraud_365d` counts `is_fraud` rows. `is_fraud` is not a confirmed fraud: it
# is a deterministic function of the legacy `fraud_score` (the label-leakage finding of the EDA). Any consumer that
# reads the column name literally, for example a copilot telling an agent "this customer had a confirmed fraud last
# year", states something the data does not support. **Recommendation:** rename to `fraud_flag_365d` with a
# description saying "legacy score-derived flag, not a confirmed case", until confirmed cases (chargebacks, analyst
# dispositions) exist. The same applies to the card-support and disputes marts below.

# %% [markdown]
# ## 2 · Inquiries: one row per product plus its last 20 transactions
# `mart_account_payment_inquiry` holds the answer-ready state of every product (balance, limit, last payment, last
# decline and its decoded reason). Its recent movements live in a separate, **normalised** table
# (`mart_product_recent_transactions`, one row per transaction, rank 1 = latest) instead of a nested list: rows index
# and serve better than arrays, and memory per product stays bounded.

# %%
show(
    pl.q("""select (select count(*) from {mart_account_payment_inquiry}) as products,
                   (select count(distinct product_id) from {mart_product_recent_transactions}) as products_with_movements,
                   (select count(*) from {mart_product_recent_transactions}) as movement_rows,
                   (select count(*) from {mart_account_payment_inquiry} where last_payment_ts is null)
                     as products_without_payment"""),
    paging=False,
)
show(
    pl.q("""select last_decline_reason, last_decline_action, count(*) as products
            from {mart_account_payment_inquiry} where last_decline_reason is not null group by all order by 3 desc"""),
    paging=False,
)

# %% [markdown]
# 15 % of products (about 60 k) have **never** moved: an inquiry about them can only report the balance. Decline
# explanations come from the `response_codes` seed (meaning, customer message in Spanish and English, next action), so
# the copilot's explanation of a decline is reviewed text, not generated text.
# The four real decline reasons are almost equally frequent (about 38 k products each): the generator draws them
# uniformly, so "most common decline reason" analyses carry no signal here. 7,931 products last declined **without**
# a response code (R03) get `DATA_QUALITY_TICKET`: the copilot must not invent a reason for them.

# %% [markdown]
# ## 3 · `mart_card_support`: a deterministic next best action
# Rules in priority order: the first one that applies wins. Each is a business rule a supervisor can read.
#
# | priority | action | condition |
# |---|---|---|
# | 1 | `FRAUD_REVIEW_AND_BLOCK` | a fraud flag in the last 365 days and the card is not blocked |
# | 2 | `REISSUE_CARD` | active but expired (R22), or declined as expired in 30 days |
# | 3 | `PROACTIVE_RENEWAL` | expires within 45 days |
# | 4 | `VERIFY_CARD_DATA` | 3+ invalid-card declines in 30 days |
# | 5 | `REVIEW_RISK_BLOCK` | 3+ do-not-honour declines in 30 days |
# | 6 | `EXPLAIN_LIMIT_OR_OFFER_INCREASE_REVIEW` | utilisation ≥ 95 % or 3+ insufficient-funds declines |
# | 7 | `UNBLOCK_AFTER_STRONG_AUTH` | the card is blocked |
# | – | `NONE` | nothing applies |

# %%
nba = pl.q(
    "select next_best_action, count(*) as cards from {mart_card_support} group by 1 order by 2 desc"
)
fig = px.bar(
    nba, x="cards", y="next_best_action", orientation="h", title="Next best action per card"
)
fig.update_layout(height=320, yaxis_title=None, yaxis=dict(autorange="reversed"))
fig.show()
show(nba, paging=False)

# %% [markdown]
# **Reading.**
# * **REISSUE_CARD for 55 k cards** is the R22 artefact (active cards past expiry). In a real bank this would be a
#   reissue campaign, not a support action, and should be handled as a batch operation.
# * **FRAUD_REVIEW_AND_BLOCK for 499 cards** is driven by the score-derived fraud flag. Blocking a card is a
#   customer-harming action; driven by a synthetic label it would block cards for the wrong reason. **In production
#   this rule must read confirmed fraud cases or the anomaly monitor's analyst-confirmed alerts**, never the legacy
#   score.
# * Rules 4 and 5 never fire: 0.8 transactions a month cannot produce three declines of one kind in 30 days.
#
# **Why rules and not a model.** A support action must be explainable to the customer and to the regulator ("your card
# was reissued because it expired"). A rule table is explainable by construction, testable with unit tests (the
# mart's `_unit_tests.yml`), and can be learned from later (the logged actions and their outcomes become training data).

# %% [markdown]
# ## 4 · `mart_transaction_disputes`: linking a complaint to a transaction without a key
# The source has **no** complaint → transaction key. The mart guesses: among the customer's transactions in the 60 days
# before the complaint, score each candidate (+3 same product, +3 amount within 1 % of the claim, up to +2 for
# recency) and keep the best, with a confidence label (`high` = product and amount, `medium` = amount, `low` = product).

# %%
link = pl.q("""select link_confidence, count(*) as disputes, round(avg(n_candidates), 1) as avg_candidates
               from {mart_transaction_disputes} group by 1 order by 2 desc""")
show(link, paging=False)
lost = pl.q("""
    with d as (select * from {stg_complaints}
               where category in ('Transactions', 'Fees') or subcategory in ('Cargo no reconocido', 'Cobro indebido')),
    c as (select d.complaint_id, d.affected_product_id is not null as names_a_product,
                 count(t.transaction_id) as transactions_in_window
          from d left join {fct_transaction} t on t.customer_id = d.customer_id
           and t.transaction_ts_utc between d.created_ts_utc - interval 60 day and d.created_ts_utc
          group by all)
    select c.names_a_product, count(*) as disputes,
           count(*) filter (where transactions_in_window > 0) as with_transactions_in_window,
           count(*) filter (where m.linked_transaction_id is not null) as with_a_linked_candidate
    from c join {mart_transaction_disputes} m using (complaint_id) group by 1""")
show(lost, paging=False)

# %% [markdown]
# **Finding: the candidate filter trusts a column known to be wrong.** The join keeps a candidate only if
# `affected_product_id is null`, or the transaction is on that product, or the amount matches. But every complaint
# that names a product names **another customer's** product (R25, notebook 06). So for the 17,507 disputes that name a
# product, every candidate is discarded unless the amount matches: 11,803 of them had transactions in the window and
# end with **no** candidate at all. Overall only 34 of 26,351 disputes link with medium confidence and none with high.
#
# **Recommendation (two steps).**
# 1. Now: ignore `affected_product_id` when it is not owned by the complainant (`dq_r25_product_not_owned`). The
#    disputes would then carry their recent transactions as low-confidence candidates: still not a link, but the
#    evidence an agent needs to ask the right question.
# 2. Product: **capture `disputed_transaction_id` at intake** (the service copilot asks "which transaction?" and
#    stores the id). This is the only real fix; probabilistic linkage on 0.8 transactions a month cannot work. It is
#    decision *dispute-key* on the decision board.

# %%
show(
    pl.q("""select count(*) as disputes, count(*) filter (where came_via_regulator) as via_regulator,
                   round(100 * avg(sla_breached::int), 1) as sla_breached_pct,
                   round(median(hours_to_first_response), 0) as median_hours_to_first_response,
                   count(*) filter (where prior_disputes_365d > 0) as repeat_disputers
            from {mart_transaction_disputes}"""),
    paging=False,
)

# %% [markdown]
# 286 disputes arrived **through the regulator** and about 20 % breached their SLA. The SLA clocks are computed, but
# the regulatory deadlines per country (CONDUSEF in Mexico, SFC in Colombia, BCRA in Argentina) are not yet a seed:
# the mart's own comment says "must come from compliance". **Recommendation:** add a `regulatory_deadlines` seed so
# breaches are measured against the law of each country, not one generic SLA.

# %% [markdown]
# ## 5 · `mart_cx_journey`: first-contact resolution and escalation
# One row per contact with the next contact (`lead()` over the customer's contacts), complaints within 14 days, the
# transcript and the survey. `repeat_contact_7d` (same reason within 7 days) is the first-contact-resolution proxy;
# `complaint_within_14d` is the escalation label for a future model.

# %%
show(
    pl.q("""select count(*) as contacts, round(100 * avg(repeat_contact_7d::int), 2) as repeat_contact_7d_pct,
                   round(100 * avg(complaint_within_14d::int), 2) as complaint_within_14d_pct,
                   round(100 * avg(was_escalated::int), 1) as escalated_pct,
                   count(transcript_id) as with_transcript,
                   count(*) filter (where transcript_is_template_artifact) as template_transcripts
            from {mart_cx_journey}"""),
    paging=False,
)
by_reason = pl.q("""select contact_reason, count(*) as contacts, round(100 * avg(was_resolved::int), 1) as resolved_pct,
                           round(100 * avg(repeat_contact_7d::int), 2) as repeat_7d_pct
                    from {mart_cx_journey} group by 1 order by 2 desc limit 12""")
show(by_reason, paging=False)

# %% [markdown]
# **Reading.** Repeat contacts within 7 days (0.66 %) and complaints within 14 days (0.57 %) are both rare, because
# contacts are sparse per customer, not because service is excellent. An escalation model would train on a 0.6 %
# positive class, which is possible but needs AP-based evaluation (see the atlas). Complaint contacts (`Queja`) are resolved at
# first contact only 44 % of the time against about 90 % for transactional and product contacts: the one CX
# difference in the data with an operational meaning. **Every transcript is a template
# artefact** (`{monto}` placeholders, one intent): the transcript columns are for pipeline prototyping only, never for
# NLP training or for quoting to an agent.

# %% [markdown]
# ## 6 · Explorer: everything the copilot would see for one customer
# Pick a customer id (the default is the first customer with a dispute). Personal fields are masked, as they would be
# for anyone without the restricted role.

# %%
default_id = pl.q("select min(customer_id) from {mart_transaction_disputes}").iloc[0, 0]
w_id = w.Text(value=default_id, description="customer")
out_c = w.Output()


def draw_customer(*_):
    with out_c:
        out_c.clear_output()
        cid = w_id.value.strip().replace("'", "")
        for mart, title in [
            ("mart_customer_360", "360"),
            ("mart_account_payment_inquiry", "products"),
            ("mart_card_support", "cards"),
            ("mart_transaction_disputes", "disputes"),
        ]:
            df = pl.q(f"select * from {{{mart}}} where customer_id = '{cid}'")
            display(Markdown(f"**{title}** · {len(df)} row(s)"))
            if len(df):
                show(pl.safe(df.T.reset_index()) if title == "360" else pl.safe(df), paging=False)


w_id.observe(draw_customer, "value")
draw_customer()
display(w.VBox([w_id, out_c]))

# %% [markdown]
# ## Findings and what to do
# 1. **The service marts are ready for a deterministic copilot**: one read per question, decoded reasons from reviewed
#    seeds, explicit zero-versus-NULL choices.
# 2. **Rename the fraud columns** (`confirmed_fraud_365d`, `confirmed_fraud` in the dispute evidence): they count a
#    score-derived flag, not confirmed cases. A copilot repeating the name would make a false statement.
# 3. **Do not block cards on the legacy flag.** The `FRAUD_REVIEW_AND_BLOCK` rule must read confirmed cases or
#    analyst-confirmed alerts in production.
# 4. **Fix the dispute candidate filter** (ignore unowned products) now, and **capture the disputed transaction at
#    intake** in the copilot: the only real fix for dispute linkage.
# 5. **Add per-country regulatory deadlines** as a seed, so SLA breaches are measured against each country's rules.
# 6. **CX labels are rare and transcripts are synthetic templates**: escalation modelling is possible but weak; NLP is
#    not possible on this data.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
