# %% [markdown]
# # 11 · Privacy inputs and serving tables (__COUNTRY_NAME__)
# **__SERIES__ · __COUNTRY_NAME__** · *generated from `notebooks/country_template`: edit the template*
#
# Differential-privacy inputs and the contracted serving tables for __COUNTRY_NAME__ (pipeline series, notebook 11).
# The country question for privacy: a country-level release has **smaller cells** than a bank-wide one, so the same
# noise costs more accuracy.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import pandas as pd
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme

COUNTRY = "__COUNTRY__"
DATASET = "__DATASET__"
PREFIX = "__PREFIX__"
CTRY = country.SCOPES[COUNTRY]
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "features_graph_knowledge")
PRIV = ["privacy_input_complaints_country_month", "privacy_input_tx_segment_month"]
SERVING = sorted(n for n in pl.catalog()["node"] if n.startswith("serving_"))
built = pl.build_set(PRIV + SERVING)

# %% [markdown]
# ## 1 · Cell sizes and the noise they can carry
# Complaint counts per (month, category) for this country, and the relative error of a Laplace release with
# sensitivity 3 (the contribution bound) at three privacy budgets.

# %%
cells = pl.q("""select year_month, category, sum(bounded_contribution) as complaints
                from {privacy_input_complaints_country_month} group by all""")
rows = []
for eps in (0.1, 0.5, 1.0):
    b = 3 / eps
    rows.append(
        {
            "epsilon": eps,
            "noise scale": b,
            "median cell": cells.complaints.median(),
            "median relative error %": round(100 * b / cells.complaints.median(), 1),
            "cells below 10 × scale %": round(100 * (cells.complaints < 10 * b).mean(), 1),
        }
    )
show(pd.DataFrame(rows), paging=False)
display(
    Markdown(
        f"**{CTRY.title}: {len(cells)} complaint cells, median {cells.complaints.median():.0f} complaints.** At ε = 0.5 the "
        f"median cell is released within about {100 * 6 / cells.complaints.median():.0f} %; the smaller the country, the "
        "coarser its releases must be (quarterly instead of monthly, or fewer categories) for the same budget."
    )
)

# %% [markdown]
# ## 2 · Serving tables

# %%
srv = [
    {
        "serving table": s,
        "rows": pl.rows(s),
        "contract enforced": bool(
            (pl.nodes[pl.key(s)]["config"].get("contract") or {}).get("enforced")
        ),
    }
    for s in SERVING
]
show(pd.DataFrame(srv), paging=False)
pl.ensure_until("privacy_serving")
t = pl.run_tests("privacy_serving")
display(
    Markdown(
        f"Privacy and serving tests: {', '.join(f'{k} {v}' for k, v in t.status.value_counts().items())}. "
        "A country deployment publishes only its own rows to the serving store in its residency region."
    )
)

# %% [markdown]
# ## Findings for __COUNTRY_NAME__ and what to do
# The computed statements above; privacy budgets are set per release and per country, and small countries need
# coarser cells.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
