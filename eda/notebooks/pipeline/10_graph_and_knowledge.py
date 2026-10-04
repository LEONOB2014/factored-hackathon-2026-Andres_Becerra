# %% [markdown]
# # 10 · Graph and knowledge exports
# **Pipeline series** · task group `features_graph_knowledge`, part 2: `models/graph`, `models/knowledge`
#
# ## What happens here
# Some questions are about **relationships**: which customers share a device, which accounts form a ring, which
# merchants a fraudster tests cards on. They need a graph. Others are about **retrieval**: a copilot that answers "what
# do we know about this customer?" needs text documents and facts it can search. The platform derives both from gold,
# as Parquet files (`external` models) that non-dbt consumers read: the Neo4j loader, graph-learning jobs, the
# GraphRAG indexer.
#
# | model | what it is |
# |---|---|
# | `graph_nodes`, `graph_edges` | a heterogeneous property graph: customers, products, merchants, agents, branches, campaigns, complaints, countries, IPs |
# | `tgn_tx_events`, `tgn_node_features` | a time-stamped event stream for temporal graph networks (TGN) |
# | `fgl_silo_nodes`, `fgl_silo_edges` | one subgraph per data-residency silo, for federated graph learning |
# | `kb_entity_docs`, `kb_entity_triples` | entity documents and subject–predicate–object facts for GraphRAG |

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
pl.ensure_until("gold")
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

# %% [markdown]
# ## 1 · The property graph

# %%
nodes = pl.q("select node_type, count(*) as nodes from {graph_nodes} group by 1 order by 2 desc")
edges = pl.q("""select src_type || ' -' || rel || '→ ' || dst_type as edge, count(*) as edges,
                       count(label) as edges_with_label
                from {graph_edges} group by 1 order by 2 desc""")
show(nodes, paging=False)
show(edges, paging=False)

# %% [markdown]
# 617 k nodes and 4.6 M edges. Most edges are customer–campaign and customer–agent contacts; the money edges are
# `product → merchant` (paid at) and `customer → country` (transacted in). **There are no transfer edges between
# customers**: transfers carry no counterparty, so the graph cannot show money moving between accounts, which is the
# edge mule detection needs.

# %% [markdown]
# ## 2 · Degree: who is connected to whom
# In a graph the **degree** of a node is its number of edges. Graph algorithms (community detection, random walks,
# GNN message passing) are dominated by high-degree nodes, so the degree distribution is the first thing to inspect.

# %%
deg = pl.q("""select dst_type as node_type, dst_id, count(distinct src_id) as degree
              from {graph_edges} where dst_type in ('ip', 'merchant', 'country', 'branch') group by all""")
top = deg.sort_values("degree", ascending=False).groupby("node_type").head(3)
show(pl.safe(top.rename(columns={"dst_id": "node_id_token"})), paging=False)
ip = deg[deg.node_type == "ip"]
fig = px.histogram(
    ip, x="degree", log_y=True, nbins=60, title="Customers per IP node (log count of IPs)"
)
fig.update_layout(height=300)
fig.show()

# %% [markdown]
# **Finding: one IP node is connected to 143,222 customers (95 % of the bank).** The other 226 IP nodes link exactly
# two customers each.

# %%
show(
    pl.q("""select count(*) filter (where ip_address is null) as events_without_ip, count(*) as events
            from {stg_digital_events}"""),
    paging=False,
)
null_token = pl.q(
    "select sha256(concat('local-dev-salt', '|', lower(trim(cast(null as varchar))))) as t"
).iloc[0, 0]
super_id = ip.sort_values("degree").iloc[-1]["dst_id"]
print("the supernode is the token of NULL:", super_id == null_token)
show(
    pl.q("""select 'email_token' as token, count(*) filter (where c.email is null) as source_nulls,
                   (select max(k) from (select email_token, count(*) as k from {int_customer_profile} group by 1))
                     as max_customers_per_token
            from {stg_customers} c
            union all
            select 'phone_token', count(*) filter (where c.mobile_phone is null),
                   (select max(k) from (select phone_token, count(*) as k from {int_customer_profile} group by 1))
            from {stg_customers} c"""),
    paging=False,
)

# %% [markdown]
# **Root cause: tokenising NULL produces a constant.** `pii_hash(x) = sha256(salt || '|' || lower(trim(x)))`, and
# DuckDB's `concat` treats NULL as an empty string, so **every missing value hashes to the same token**. 759 k
# digital events have no IP: all of them become "the same IP", which the graph sees as one device shared by 143 k
# customers. The same happens to the 2,984 customers without e-mail (one shared `email_token`) and the 4,707 without
# a mobile phone (one shared `phone_token`).
#
# **Why it matters.**
# * For **graph analytics**, a supernode puts almost every customer two hops from every other. Community detection
#   returns one giant community, PageRank concentrates on one node, and a GNN's message passing averages everyone
#   together. "Shared device" fraud features would flag 95 % of customers.
# * For **entity resolution**, thousands of different people look like one person on e-mail or phone.
# * The atlas quoted "237 IP addresses shared across customers" from an earlier warehouse; the real figure is
#   **226 IPs shared by two customers each**, plus one artefact.
#
# **What to do (high priority, one-line fix).** Make the macro NULL-preserving:
# `case when x is null or trim(x) = '' then null else sha256(...) end`, and exclude NULL tokens from graph edges.
# Add a test that no token is shared by more than a small number of entities (a uniqueness-ratio check on every
# `*_token` column). Rebuild silver onwards.

# %% [markdown]
# ## 3 · Temporal and federated exports

# %%
show(
    pl.q("""select count(*) as events, count(distinct src) as sources, count(distinct dst) as destinations,
                   min(ts) as first_ts, max(ts) as last_ts, round(100 * avg(label::int), 4) as label_pct
            from {tgn_tx_events}"""),
    paging=False,
)
show(
    pl.q("""select silo, residency_region, count(*) as nodes,
                   round(100 * avg(label_complaint_90d::int), 2) as complaint_label_pct
            from {fgl_silo_nodes} group by all order by 1"""),
    paging=False,
)

# %% [markdown]
# * **`tgn_tx_events`**: one event per transaction that names a merchant (1 M of the 4.3 M), with PIT features and the
#   fraud label: the input of a temporal graph network. It inherits both limits found earlier: no counterparty edges
#   and a label without behavioural content (notebook 09).
# * **`fgl_silo_*`**: one subgraph per residency silo (Mexico in `northamerica-south1`; Colombia and Argentina in
#   `southamerica-east1`). Federated learning trains on each silo where it lives and only shares model updates, so
#   personal data never crosses the residency boundary. The silos are built from the country dimension's residency
#   column (notebook 06): the legal constraint is enforced by the data model, not by convention.

# %% [markdown]
# ## 4 · Knowledge: documents and triples for GraphRAG

# %%
show(
    pl.q("""select entity_type, count(*) as documents, round(avg(length(text)), 0) as avg_chars
            from {kb_entity_docs} group by 1 order by 2 desc"""),
    paging=False,
)
show(
    pl.q("""select predicate, count(*) as triples, count(distinct provenance) as provenances
            from {kb_entity_triples} group by 1 order by 2 desc"""),
    paging=False,
)
example = pl.q("select entity_type, text from {kb_entity_docs} where entity_type = 'agent' limit 1")
print(example.iloc[0]["text"][:600])

# %% [markdown]
# Each customer, complaint, agent and campaign gets a short **generated document** (a templated summary of its gold
# facts) and a set of **triples** with provenance. A GraphRAG copilot retrieves documents by similarity and walks
# triples for multi-hop questions ("which agents handled complaints from customers who received campaign X?").
#
# **Two cautions.** The documents are built from tokens and aggregates, so they carry no direct identifiers, but
# the `used_ip` triples inherit the supernode above. And a generated document is only as true as the gold facts
# behind it: the "fraud" wording must follow the rename recommended in notebook 07.

# %% [markdown]
# ## 5 · Explorer: neighbours of a node type

# %%
w_rel = w.Dropdown(options=edges["edge"].tolist(), description="edge")
out_n = w.Output()


def draw_edges(*_):
    with out_n:
        out_n.clear_output()
        src, rest = w_rel.value.split(" -", 1)
        rel, dst = rest.split("→ ")
        d = pl.q(f"""select degree, count(*) as source_nodes from (
                         select src_id, count(*) as degree from {{graph_edges}}
                         where src_type = '{src}' and rel = '{rel}' and dst_type = '{dst.strip()}' group by 1)
                     group by 1 order by 1""")
        display(Markdown(f"**{w_rel.value}**: out-degree of the source nodes"))
        fig = px.bar(d, x="degree", y="source_nodes", log_y=True)
        fig.update_layout(height=280)
        fig.show()


w_rel.observe(draw_edges, "value")
draw_edges()
display(w.VBox([w_rel, out_n]))

# %% [markdown]
# ## Findings and what to do
# 1. **Fix `pii_hash` to keep NULL as NULL** (high priority). Missing IPs, e-mails and phones collapse into one token
#    each; the graph gets a supernode linking 95 % of customers, and entity resolution would merge thousands of
#    people. Add a token-uniqueness test.
# 2. **The graph has no money-movement edges between customers**: mule and ring detection need transfer
#    counterparties (account or key of the beneficiary), the first data request for bundle B2.
# 3. **Real shared-device signal is tiny** (226 IPs shared by two customers). Graph-based fraud features cannot be
#    validated on this data beyond the method.
# 4. **Residency is enforced by the data model** (federated silos from the country dimension), the right pattern for
#    four jurisdictions with different data-protection laws.
# 5. **Knowledge exports are ready for GraphRAG prototyping** once the token fix and the fraud-wording fix land.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
