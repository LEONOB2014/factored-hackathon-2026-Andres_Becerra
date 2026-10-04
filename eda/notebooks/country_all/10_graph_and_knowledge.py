# %% [markdown]
# # 10 · Graph and knowledge exports (All countries)
# **Country series · All countries** · *generated from `notebooks/country_template`: edit the template*
#
# The property graph, temporal events, federated silos and GraphRAG documents of All countries (pipeline series,
# notebook 10). The bank-wide replay found that tokenising a missing IP gives one constant token, a supernode. Here:
# how large that supernode is inside one country, and what genuine sharing remains.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme

COUNTRY = "ALL"
DATASET = "main"
PREFIX = "country"
CTRY = country.SCOPES[COUNTRY]
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "gold")
GRAPH = [
    "graph_nodes",
    "graph_edges",
    "tgn_node_features",
    "tgn_tx_events",
    "fgl_silo_nodes",
    "fgl_silo_edges",
    "kb_entity_docs",
    "kb_entity_triples",
]
built = pl.build_set(GRAPH)

# %%
show(
    pl.q("select node_type, count(*) as nodes from {graph_nodes} group by 1 order by 2 desc"),
    paging=False,
)
deg = pl.q(
    """select dst_id, count(distinct src_id) as customers from {graph_edges} where dst_type = 'ip' group by 1"""
)
custs = pl.q("select count(*) from {stg_customers}").iloc[0, 0]
top = int(deg.customers.max()) if len(deg) else 0
custs = max(int(custs), 1)
fig = px.histogram(
    deg, x="customers", log_y=True, nbins=40, title=f"{CTRY.title}: customers per IP node"
)
fig.update_layout(height=280)
fig.show()
display(
    Markdown(
        f"**The largest IP node links {top:,} of {CTRY.name}'s {custs:,} customers ({100 * top / custs:.0f} %)**; "
        f"{int((deg.customers == 2).sum())} IP nodes link exactly two customers. The large node is the token of NULL "
        "(missing IPs), the same defect as bank-wide: fix `pii_hash` before any graph work in any country."
    )
)

# %%
show(
    pl.q("""select silo, residency_region, count(*) as nodes from {fgl_silo_nodes} group by all"""),
    paging=False,
)
show(
    pl.q(
        """select entity_type, count(*) as documents from {kb_entity_docs} group by 1 order by 2 desc"""
    ),
    paging=False,
)

# %% [markdown]
# The whole bank produces one federated silo per country, each in its residency region: the cut the country scopes
# make by hand is the one the federated design makes in the data model.
#
# ## Findings for All countries and what to do
# The computed statements above; the token fix and the missing transfer counterparties are bank-wide blockers for
# graph learning in every country.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
