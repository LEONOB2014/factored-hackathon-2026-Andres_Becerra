# %% [markdown]
# # 03 · Within the hour: sequences and bursts
# **Granularity series II · time and cells** · grain: the individual event, ordered in time per customer
#
# **Stakeholders.** Service design (does a failed app action make the customer call within the hour?), fraud (card
# testing and account takeover show as bursts of activity minutes apart), complaints management (does an unresolved call
# turn into a complaint the same day?), marketing (does a send move a customer to transact within hours?).
#
# **What this grain adds.** Every aggregate so far (month, day, hour) counted events in a window and lost their order.
# The sub-day sequence is where cause and effect live in a real bank: an error, then a call twenty minutes later.
#
# **Methods.**
# 1. **Symmetric windows.** For each trigger event A and response B of the same customer, count B in the W hours
#    *after* A and in the W hours *before* A. Without a causal link (and with a stationary background), after and before
#    are equally likely: after ~ Binomial(after + before, ½). A link shows as more B after than before. The design
#    controls for each customer's own activity level, because the same customer provides both windows.
# 2. **Burstiness.** If a customer's transactions follow a Poisson process with a personal rate λ, the gap between two
#    transactions is exponential with mean 1/λ and P(gap < 10 min) = 1 − e^(−λ·10 min). The observed share of short gaps
#    is compared with this expectation computed **per customer** (each with its own λ), so heterogeneity between
#    customers is not mistaken for bursts.
# 3. **Velocity and fraud.** The fraud flag rate of transactions that follow another within an hour, against the rest.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show
from scipy import stats
from statsmodels.stats.proportion import proportion_confint

from latam_eda import pipeline as pipe
from latam_eda import theme

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


con.sql(f"""create table tx as select customer_id, try_cast(transaction_date as timestamp) as ts, transaction_status as status,
            response_code, lower(is_fraud) in ('true', '1') as is_fraud
            from {raw("transactions")} where coalesce(customer_id, '') <> ''""")
con.sql(f"""create table cc as select customer_id, try_cast(interaction_date as timestamp) as ts,
            lower(was_escalated) in ('true', '1') as escalated, lower(was_resolved) in ('true', '1') as resolved
            from {raw("call_center_interactions")} where coalesce(customer_id, '') <> ''""")
con.sql(f"""create table er as select customer_id, try_cast(event_date as timestamp) as ts from {raw("digital_events")}
            where event_type = 'Error' and coalesce(customer_id, '') <> ''""")
con.sql(f"""create table cp as select customer_id, try_cast(creation_date as timestamp) as ts from {raw("complaints")}
            where coalesce(customer_id, '') <> ''""")
con.sql(f"""create table sd as select customer_id, try_cast(send_date as timestamp) as ts from {raw("campaign_sends")}
            where coalesce(customer_id, '') <> '' and lower(was_delivered) in ('true', '1')""")
print(
    {t: con.sql(f"select count(*) from {t}").fetchone()[0] for t in ["tx", "cc", "er", "cp", "sd"]}
)

# %% [markdown]
# ## 1 · Does one event lead to another within hours?

# %%
PAIRS = [
    ("digital error → contact", "er", "true", "cc", "service: the call a failed app action causes"),
    (
        "declined payment → contact",
        "tx",
        "a.status = 'Declined'",
        "cc",
        "service: the call a decline causes",
    ),
    (
        "unresolved contact → complaint",
        "cc",
        "not a.resolved",
        "cp",
        "complaints: unresolved calls escalating",
    ),
    (
        "escalated contact → complaint",
        "cc",
        "a.escalated",
        "cp",
        "complaints: escalations becoming complaints",
    ),
    ("complaint → contact", "cp", "true", "cc", "service: follow-up calls after a complaint"),
    (
        "campaign delivered → transaction",
        "sd",
        "true",
        "tx",
        "marketing: activity triggered by a send",
    ),
    (
        "declined for funds → transaction",
        "tx",
        "a.response_code = '51'",
        "tx",
        "payments: retries after insufficient funds",
    ),
]
WINDOWS = [1, 2, 6, 24, 72]
rows = []
for name, A, cond, B, use in PAIRS:
    same = A == B
    for w in WINDOWS:
        after, before = con.sql(f"""
            select count(*) filter (where b.ts > a.ts and b.ts <= a.ts + to_hours({w})),
                   count(*) filter (where b.ts < a.ts and b.ts >= a.ts - to_hours({w}))
            from {A} a join {B} b using (customer_id)
            where {cond} and b.ts between a.ts - to_hours({w}) and a.ts + to_hours({w})
            {"and b.ts <> a.ts" if same else ""}""").fetchone()
        n = after + before
        p = stats.binomtest(after, n, 0.5).pvalue if n else np.nan
        rows.append(
            {
                "sequence": name,
                "window (h)": w,
                "after": after,
                "before": before,
                "after / before": after / before if before else np.nan,
                "p_value": p,
                "business use": use,
            }
        )
seq = pd.DataFrame(rows)
seq.to_csv(OUT / "granularity_time_sequences.csv", index=False)
show(seq.round(4), paging=False)
fig = px.line(
    seq,
    x="window (h)",
    y="after / before",
    color="sequence",
    log_x=True,
    markers=True,
    title="Responses after the trigger over responses before it, by window (1 = no sequence)",
)
fig.add_hline(y=1, line_dash="dot")
fig.update_layout(height=380)
fig.show()
sig = seq[(seq.p_value < 0.001) & ((seq["after / before"] > 1.1) | (seq["after / before"] < 0.9))]
display(
    Markdown(
        f"**{len(sig)} of {len(seq)} (sequence, window) tests show a material lead (after/before outside 0.9–1.1, "
        "p < 0.001).** "
        + (
            "No event leads to another at any window from one hour to three days: a digital error is not followed by a "
            "call, a decline neither by a call nor by a retry, a send not by a transaction. The sub-day order of events "
            "carries no information here. A real bank's service and fraud analytics live in exactly these sequences "
            "(error-to-call journeys, decline-retry bursts, send-to-activity lift); on this data they cannot be learned, "
            "and journey analytics must wait for real interaction logs with shared session or case keys."
            if not len(sig)
            else "Leads found: "
            + "; ".join(
                f"{r['sequence']} within {r['window (h)']} h (×{r['after / before']:.2f})"
                for _, r in sig.iterrows()
            )
        )
    )
)

# %% [markdown]
# ## 2 · Bursts: do a customer's transactions cluster in time?

# %%
gaps = con.sql("""
    with g as (select customer_id, epoch(ts - lag(ts) over (partition by customer_id order by ts)) / 60.0 as gap_min from tx),
         r as (select customer_id, count(*) as n, epoch(max(ts) - min(ts)) / 60.0 as span_min from tx group by 1 having count(*) >= 3)
    select g.customer_id, g.gap_min, r.n, r.span_min from g join r using (customer_id) where g.gap_min is not null""").df()
gaps["lam"] = (gaps.n - 1) / gaps.span_min  # each customer's own rate per minute
rows = []
for thr in [1, 10, 60, 24 * 60]:
    obs = (gaps.gap_min < thr).mean()
    exp_ = (1 - np.exp(-gaps.lam * thr)).mean()
    rows.append(
        {
            "gap shorter than (min)": thr,
            "observed %": 100 * obs,
            "Poisson expectation %": 100 * exp_,
            "observed / expected": obs / exp_,
        }
    )
burst = pd.DataFrame(rows)
show(burst.round(4), paging=False)
cg = gaps.groupby("customer_id").gap_min.agg(["std", "mean", "size"])
cv = (cg["std"] / cg["mean"])[cg["size"] > 2].rename("gap CV")
# pre-binned: one bar per bin, not one point per customer, keeps the notebook small
cnt, edges = np.histogram(cv.clip(upper=3), bins=60)
fig = px.bar(
    x=(edges[:-1] + edges[1:]) / 2,
    y=cnt,
    title="Coefficient of variation of each customer's transaction gaps (Poisson = 1)",
)
fig.add_vline(x=1, line_dash="dot")
fig.update_layout(height=300, showlegend=False, xaxis_title="CV of gaps", yaxis_title="customers")
fig.show()
display(
    Markdown(
        f"**Gaps under 10 minutes: {burst.iloc[1]['observed %']:.3f} % observed against {burst.iloc[1]['Poisson expectation %']:.3f} % "
        f"for Poisson customers (×{burst.iloc[1]['observed / expected']:.2f}); the median customer's gap CV is "
        f"{cv.median():.2f} (Poisson: 1).** "
        + (
            "Transactions arrive as independent events at each customer's own rate: no bursts, no sessions of rapid "
            "purchases, no retries. Velocity features (counts in the last hour, the last ten minutes) can only rediscover "
            "the customer's rate."
            if 0.8 < burst.iloc[1]["observed / expected"] < 1.5 and 0.8 < cv.median() < 1.2
            else "Activity clusters in time beyond each customer's rate: bursts exist."
        )
    )
)

# %% [markdown]
# ## 3 · Velocity and the fraud flag

# %%
vel = con.sql("""
    with x as (select is_fraud, epoch(ts - lag(ts) over (partition by customer_id order by ts)) / 60.0 as gap_min from tx)
    select case when gap_min is null then 'first transaction' when gap_min < 60 then 'within 1 h of the previous'
                when gap_min < 1440 then 'within 24 h' else 'more than 24 h' end as previous,
           count(*) as transactions, sum(is_fraud::int) as flagged
    from x group by 1 order by 2 desc""").df()
lo, hi = proportion_confint(vel.flagged, vel.transactions, method="wilson")
vel["flag rate %"] = 100 * vel.flagged / vel.transactions
vel["95 % CI"] = [f"{100 * a:.3f}–{100 * b:.3f}" for a, b in zip(lo, hi, strict=True)]
chi = stats.chi2_contingency(np.column_stack([vel.flagged, vel.transactions - vel.flagged]))
show(vel, paging=False)
display(
    Markdown(
        f"**The fraud flag rate does {'not ' if chi.pvalue > 0.01 else ''}depend on how soon a transaction follows the "
        f"previous one (χ² p = {chi.pvalue:.2g}).** "
        + (
            "Velocity is the classic first signal of card fraud; here the flag (itself a function of a legacy score) is "
            "independent of timing, consistent with every earlier fraud finding."
            if chi.pvalue > 0.01
            else "Timing carries fraud signal: velocity rules are justified."
        )
    )
)

# %% [markdown]
# ## Findings and what they mean downstream
# * **No sequence, no burst, no velocity signal at sub-day resolution.** The generator places each event independently in
#   time, so ordering events within the hour adds nothing to the monthly and daily aggregates.
# * **What this rules out on this data:** journey analytics (error → call → complaint), retry and card-testing detection,
#   send-to-activity attribution windows, intraday triggers for a service agent.
# * **What it requires on real data:** shared keys between processes (session id across app and contact centre, case id
#   from contact to complaint, transaction id at dispute intake) and event-level streaming; the symmetric-window test of
#   this notebook is the cheap first check of each new link before any journey model is built.

# %%
con.close()
print(f"notebook time {time.time() - t0:.0f}s")
