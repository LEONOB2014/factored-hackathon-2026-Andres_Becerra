# %% [markdown]
# # 11 · Privacy inputs and serving tables
# **Pipeline series** · task group `privacy_serving`: `models/privacy`, `models/serving`
#
# ## What happens here
# Two exits from the lakehouse, each with its own protection:
# * **Privacy inputs** prepare aggregate statistics for publication with **differential privacy (DP)**. The SQL
#   *bounds each person's contribution*; the OpenDP release (the `dp_release` DAG) adds calibrated noise. Only the
#   noised output leaves.
# * **Serving tables** are the online copies of the marts that applications read with low latency (Postgres), under
#   **enforced dbt contracts**: a column's name and type cannot change without the contract changing in the same pull
#   request, so an application never breaks silently.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import ipywidgets as w
import numpy as np
import pandas as pd
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import pipeline as pipe
from latam_eda import theme

theme.register()
t0 = time.time()
pl = pipe.session()
pl.ensure_until("features_graph_knowledge")
PRIVACY = ["privacy_input_complaints_country_month", "privacy_input_tx_segment_month"]
SERVING = sorted(n for n in pl.catalog()["node"] if n.startswith("serving_"))
built = pl.build_set(PRIVACY + SERVING)

# %% [markdown]
# ## 1 · Why bound contributions?
# Differential privacy guarantees that a published statistic barely changes whether or not any one person is in the
# data. The noise needed is proportional to the **sensitivity**: how much one person can change the statistic. An
# unbounded sum has unbounded sensitivity (one customer with a 10-million-dollar month), so DP is impossible without a
# bound. The privacy inputs impose two:
# * **complaints**: at most 3 complaints per customer per (country, month, category) are counted;
# * **spend**: each customer's monthly spend is clamped to [0, 20,000] USD.
#
# The price is bias: anything above the bound is cut. The bound is a trade-off between noise (higher bound, more noise)
# and bias (lower bound, more truncation).

# %%
cmp = pl.q("""select (select count(*) from {stg_complaints}) as complaints,
                     (select sum(bounded_contribution) from {privacy_input_complaints_country_month}) as counted,
                     (select max(bounded_contribution) from {privacy_input_complaints_country_month}) as max_per_person""")
cmp["dropped by the bound"] = cmp.complaints - cmp.counted
show(cmp, paging=False)
sp = pl.q("""select count(*) as customer_months, count(*) filter (where clamped_spend_usd >= 20000) as at_the_clamp,
                    round(max(clamped_spend_usd), 0) as max_after_clamp,
                    round(quantile_cont(clamped_spend_usd, 0.99), 0) as p99
             from {privacy_input_tx_segment_month}""")
show(sp, paging=False)

# %% [markdown]
# Both bounds are free here: the complaint cap removes **nothing** (no customer files more than two complaints of one
# category in a month) and only 2,023 of 2.6 M customer-months (0.08 %) reach the spend clamp. The bias is negligible;
# the bounds buy a finite sensitivity.

# %% [markdown]
# ## 2 · What the noise does to small cells
# The release adds Laplace noise with scale `sensitivity / ε` to each published count. ε (epsilon) is the privacy
# budget: smaller is more private and noisier. The same absolute noise is negligible on a large cell and destroys a
# small one, so the release must suppress or merge small cells. Move ε to see it on the real complaint counts per
# country, month and category.

# %%
cells = pl.q("""select country_code, year_month, category, sum(bounded_contribution) as true_count
                from {privacy_input_complaints_country_month} group by all""")
rng = np.random.default_rng(7)
w_eps = w.FloatLogSlider(value=0.5, base=10, min=-2, max=1, step=0.1, description="ε")
out_dp = w.Output()


def draw_dp(*_):
    with out_dp:
        out_dp.clear_output()
        scale = 3 / w_eps.value  # sensitivity = the contribution bound (3)
        noisy = cells.true_count + rng.laplace(0, scale, len(cells))
        rel = (noisy - cells.true_count).abs() / cells.true_count
        d = pd.DataFrame({"true count": cells.true_count, "relative error": rel})
        fig = px.scatter(
            d,
            x="true count",
            y="relative error",
            log_x=True,
            log_y=True,
            opacity=0.4,
            title=f"ε = {w_eps.value:.2f}: Laplace scale {scale:.1f}",
        )
        fig.update_layout(height=340)
        fig.show()
        small = (cells.true_count < 10 * scale).mean()
        display(
            Markdown(
                f"{100 * small:.1f} % of the {len(cells):,} cells are smaller than 10 × the noise scale; "
                f"they should be suppressed or merged before release."
            )
        )


w_eps.observe(draw_dp, "value")
draw_dp()
display(w.VBox([w_eps, out_dp]))
show(cells.true_count.describe(percentiles=[0.1, 0.5, 0.9]).round(1).to_frame().T, paging=False)

# %% [markdown]
# **Reading.** Relative error falls as 1/count. The 540 published cells hold 28 to 226 complaints (median 111): at
# ε = 0.5 the Laplace scale is 6, so the median cell is reported within about 5 % and the smallest within about 20 %.
# Lower ε or a finer breakdown (by subcategory, by city) quickly produces cells that are mostly noise.
# **Recommendation:** publish only cells whose expected count clears a threshold (for example 10 × the noise scale),
# and spend the budget on fewer, larger cells. Track the cumulative ε per release in the ledger: privacy budgets add
# up over repeated releases.

# %% [markdown]
# ## 3 · Serving tables under contract

# %%
srv = []
for s in SERVING:
    n = pl.nodes[pl.key(s)]
    srv.append(
        {
            "serving table": s,
            "rows": pl.rows(s),
            "columns": len(pl.columns(s)),
            "contract enforced": bool((n["config"].get("contract") or {}).get("enforced")),
            "reads": ", ".join(pl.name(d) for d in pl.deps(pl.key(s))),
        }
    )
show(pd.DataFrame(srv), paging=False)

# %% [markdown]
# * Every serving table has an **enforced contract**: dbt checks at build time that names, types and constraints
#   match the YAML. Changing a served column is a reviewed contract change, never a side effect.
# * Serving tables are **narrower** than their marts (tokens only, the columns an app needs); re-identification happens
#   in the presentation layer behind authorisation.
# * `serving_online_fraud_state` is the warm start for the stream: each customer's history as of the stream cutoff, so
#   the first streamed transaction sees the same history the batch features saw (parity by construction).

# %%
pl.ensure_until("privacy_serving")
t = pl.run_tests("privacy_serving")
show(t[["test", "attached_to", "severity", "failures", "status"]], paging=False)

# %% [markdown]
# ## 4 · Do the serving tables say the same as the marts?
# A serving table must never disagree with the mart it publishes. Row counts and a shared key per pair:

# %%
pairs = [
    ("serving_customer_360", "mart_customer_360", "customer_id"),
    ("serving_account_inquiry", "mart_account_payment_inquiry", "product_id"),
    ("serving_card_support", "mart_card_support", "product_id"),
    ("serving_credit_eligibility", "mart_credit_eligibility", "customer_id"),
    ("serving_dispute_case", "mart_transaction_disputes", "complaint_id"),
]
rows = []
for s, m, k in pairs:
    r = pl.q(f"""select (select count(*) from {{{s}}}) as serving_rows, (select count(*) from {{{m}}}) as mart_rows,
                        (select count(*) from {{{s}}} s anti join {{{m}}} m using ({k})) as keys_not_in_mart""").iloc[
        0
    ]
    rows.append({"serving": s, "mart": m, **r.to_dict()})
show(pd.DataFrame(rows), paging=False)

# %% [markdown]
# ## Findings and what to do
# 1. **Contribution bounding works and costs little bias** here; DP releases are feasible for country × month ×
#    category complaint statistics with small-cell suppression.
# 2. **Track the privacy budget** across releases in the ledger; ε accumulates.
# 3. **Serving tables are contracted and consistent with their marts**; keep the contracts generated from the built
#    relations and reviewed by hand (`scripts/generate_contracts.py`).
# 4. **Serving inherits every mart finding**: the fraud wording (notebook 07) and the token collapse (notebook 10)
#    reach applications through these tables, so fix them upstream before publishing to Postgres.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
