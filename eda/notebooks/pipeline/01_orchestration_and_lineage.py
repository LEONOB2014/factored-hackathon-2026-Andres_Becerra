# %% [markdown]
# # 01 · Orchestration and lineage
# **Pipeline series** · how Airflow runs the data platform, and how this series replays it without Airflow
#
# ## What this series is for
# The platform turns 23.5 M source records into audited silver, a Kimball gold layer, marts, features, graphs,
# privacy-safe aggregates and serving tables. In production that happens inside Airflow, where every step is a task
# you can only watch from the outside. This series runs **the same SQL, step by step, in a scratch DuckDB** and
# stops after every step to look at what it produced: counts, rows that pass, rows that fail, distributions, joins
# that lose or duplicate rows, and the decisions encoded in each model, with an explanation of why the decision was
# taken and what it implies for the rest of the project.
#
# | notebook | Airflow task group | what you learn |
# |---|---|---|
# | 01 (this one) | the DAG chain and `seeds` | orchestration, compilation, lineage, reference data |
# | 02 | `silver` (typed) | lossless bronze, source contracts, cell findings, the correction overlay |
# | 03 | `silver` (quality) | partition profiles, schema drift, the circuit breaker, what `not_held` removes |
# | 04 | `silver` (staging) | vocabulary joins, row hashes, where personal data stays |
# | 05 | `silver` (conformed) | currency conversion, imputation, repairs, data-quality flags, monthly grid |
# | 06 | `snapshots` + `gold` core | SCD2, surrogate keys, the star schema, join coverage |
# | 07 | `gold` marts I | service marts: customer 360, inquiries, cards, disputes, CX |
# | 08 | `gold` marts II | risk and growth marts: credit, collections, AML, campaigns |
# | 09 | `features_graph_knowledge` (features) | point-in-time features, out-of-time splits, leakage guards |
# | 10 | `features_graph_knowledge` (graph, knowledge) | graph exports, temporal events, knowledge documents |
# | 11 | `privacy_serving` | differential-privacy inputs, serving tables |
# | 12 | `audit` + the three gates | integrity rules, the data-quality gate, governance, all test results |
#
# **How to run it.** Run the notebooks in order (each builds its layer on top of the previous one; a notebook run on
# its own builds whatever is missing first). The full data takes about 5 GB in `data/tmp/pipeline/` and roughly
# 15–25 minutes of building across the series on a laptop with the bounded profile (DuckDB 4 GB, 4 threads). Nothing
# is written to the shared lake or to the live lakehouse. DuckDB allows one writer per file, so close a notebook's
# kernel before opening the next if you jump around.

# %%
import sys
import time

sys.path.insert(0, "../../src")
import ipywidgets as w
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import show

from latam_eda import pipeline as pipe
from latam_eda import theme

theme.register()
t0 = time.time()
pl = pipe.session()
print(f"manifest: {len(pl.nodes)} nodes · scratch lakehouse: data/tmp/pipeline/{pl.db.name}")

# %% [markdown]
# ## 1 · The orchestration: data-aware scheduling
# Airflow 3 schedules most DAGs on **assets** rather than on clocks: a DAG declares the asset it produces
# (`outlets`) and others run when that asset is updated. That is why the chain below has only one clock at its
# start: once the daily landing arrives, every downstream step is triggered by the step before it, and nothing runs
# on stale inputs because "it is 2 a.m.".
#
# | DAG | runs when | produces | what it does |
# |---|---|---|---|
# | `landing_ingest` | daily | `LANDING` | copies the day's source files to WORM landing storage with a sealed manifest |
# | `bronze_build` | `LANDING` | `BRONZE` | lossless bronze: every record as text with its sha256, proven byte-exact |
# | `dbt_lakehouse` | `BRONZE` or `CORRECTIONS` | `LAKEHOUSE` | **the dbt project, replayed by this series**, then three gates |
# | `dq_correction_review` | manual | `CORRECTIONS` | four-eyes correction of flagged cells (model-risk notebook 02) |
# | `backup_reconciliation` | `BRONZE` | – | reconciles the backup folder against main (audit only) |
# | `publish_serving` | `LAKEHOUSE` | `SERVING` | publishes serving tables to the online store |
# | `graph_load` → `ml_graph_learning` | `LAKEHOUSE` → `GRAPH` | `GRAPH` | loads Neo4j, trains graph models |
# | `ml_fraud_ensemble` | `LAKEHOUSE` | `FRAUD_MODEL` | trains and registers the anomaly ensemble (needs human approval) |
# | `compliance_triggers`, `monitoring_drift` | `LAKEHOUSE` | – | compliance reviews, data and model drift |
# | `kb_sync`, `audit_anchor` | hourly | `KNOWLEDGE` | knowledge-base sync, ledger head anchoring |
# | `dp_release`, `retention_and_erasure` | monthly, daily | – | differential-privacy releases, retention and erasure requests |
#
# Inside `dbt_lakehouse`, Astronomer **Cosmos** turns each dbt model into an Airflow task, grouped in seven task
# groups that run one after another, followed by three Python gates:
#
# `seeds → silver → snapshots → gold → features/graph/knowledge → privacy/serving → audit → drift_holds → dq_gate →
# governance_gate`
#
# Each group runs its models in dependency order and then its data tests (`TestBehavior.AFTER_ALL`): a model is
# never tested half-built, and a failing test stops the groups after it.

# %%
cat = pl.catalog()
by = cat.groupby(["layer", "materialized"], observed=True).size().unstack(fill_value=0)
by["total"] = by.sum(axis=1)
tests = pd.Series(
    {layer: len(pl.layer_tests(layer)) for layer in pipe.LAYER_NAMES}, name="data tests"
)
summary = by.join(tests)
display(summary)
print(f"{len(cat)} buildable nodes, {int(tests.sum())} data tests")

# %%
fig = px.bar(
    cat.groupby(["layer", "materialized"], observed=True).size().reset_index(name="nodes"),
    x="layer",
    y="nodes",
    color="materialized",
    text="nodes",
    title="Nodes per Airflow task group and materialization",
)
fig.update_layout(xaxis_title=None, legend_title=None, height=380)
fig.show()

# %% [markdown]
# **Reading the materializations.**
# * **view**: a stored query, computed when read. Used for the typed and staging layers, which are thin
#   projections over bronze Parquet: materializing them would copy 23 M rows twice for no gain, and a view always
#   reflects the current bronze and the current corrections.
# * **table**: computed once per run and stored. Used where a result is read many times (conformed silver, gold,
#   marts) or is expensive (joins, window functions).
# * **external**: a table written as Parquet to the lake so non-dbt consumers (graph loader, ML training, the
#   stream demo) can read it without opening DuckDB. The emulator keeps them as tables in the scratch database, so
#   the shared lake is never rewritten.
# * **seed**: a small CSV in git loaded as a table: reference data and policy (codes, SLOs, PII lists).
# * **snapshot**: SCD Type 2 history (notebook 06).

# %% [markdown]
# ## 2 · Compilation: from Jinja to the SQL that actually runs
# dbt models are SQL templates. `{{ ref('x') }}` becomes a relation name, `{{ source(...) }}` becomes a
# `read_parquet(...)` over the lake, and macros expand into SQL. `dbt compile` renders all of it without running
# anything; this series executes exactly that rendered SQL. Here is one model before and after compilation.

# %%
k = pl.key("stg_transactions")
print("— raw (what is in git) —\n" + pl.nodes[k]["raw_code"].strip()[:600])
print("\n— compiled (what DuckDB executes), first 40 lines —")
print("\n".join(pl.sql("stg_transactions").splitlines()[:40]))

# %% [markdown]
# The compiled statement shows two decisions that the template hides:
# 1. **Vocabulary is normalised by a join, not by `CASE` statements.** `left join country_codes on raw_name =
#    transaction_country` maps `México`, `Mexico` and `Colombia` to ISO codes. A new spelling in the source does not
#    break the model; it produces a NULL code, which notebook 04 counts.
# 2. **Held partitions are filtered here**, by `not exists (... dq_partition_holds ...)`. Staging is the first
#    layer that drops rows, and only rows of partitions whose schema changed (notebook 03).

# %% [markdown]
# ## 3 · Lineage: who reads whom
# Every node's parents and children come from the manifest. The figure places each node in its task-group column;
# lines are dependencies. The explorer below shows the full upstream and downstream set of any node: before changing
# a model, this is the blast radius.

# %%
rank = {name: i for i, name in enumerate(pipe.LAYER_NAMES)}
pos = {}
for layer, grp in cat.groupby("layer", observed=True):
    for j, nm in enumerate(sorted(grp["node"])):
        pos[nm] = (rank[layer], j - len(grp) / 2)
ex, ey = [], []
for k2 in pl.buildable():
    a = pl.name(k2)
    for d in pl.deps(k2):
        b = pl.name(d)
        if a in pos and b in pos:
            ex += [pos[b][0], pos[a][0], None]
            ey += [pos[b][1], pos[a][1], None]
fig = go.Figure()
fig.add_trace(
    go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=0.4, color="#b8c2cc"), hoverinfo="skip")
)
fig.add_trace(
    go.Scatter(
        x=[p[0] for p in pos.values()],
        y=[p[1] for p in pos.values()],
        mode="markers",
        text=list(pos),
        hovertemplate="%{text}<extra></extra>",
        marker=dict(size=7),
    )
)
fig.update_layout(
    title="Dependency graph by task group (hover a node)",
    showlegend=False,
    height=640,
    xaxis=dict(tickvals=list(range(len(pipe.LAYER_NAMES))), ticktext=pipe.LAYER_NAMES, title=None),
    yaxis=dict(visible=False),
)
fig.show()

# %%
w_node = w.Dropdown(
    options=sorted(cat["node"]), value="int_transactions_enriched", description="node"
)
out_lin = w.Output()


def draw_lineage(*_):
    with out_lin:
        out_lin.clear_output()
        lin = pl.lineage(w_node.value)
        row = cat.set_index("node").loc[w_node.value]
        display(
            Markdown(
                f"**{w_node.value}** · {row['layer']} · {row['materialized']} · {row['description'] or '–'}\n\n"
                f"**{len(lin['upstream'])} upstream:** {', '.join(lin['upstream']) or '–'}\n\n"
                f"**{len(lin['downstream'])} downstream:** {', '.join(lin['downstream']) or '–'}"
            )
        )


w_node.observe(draw_lineage, "value")
draw_lineage()
display(w.VBox([w_node, out_lin]))

# %%
reach = pd.DataFrame(
    [
        {
            "node": n,
            "upstream": len(pl.lineage(n)["upstream"]),
            "downstream": len(pl.lineage(n)["downstream"]),
        }
        for n in cat["node"]
    ]
).merge(cat[["node", "layer"]], on="node")
show(reach.sort_values("downstream", ascending=False).head(15), paging=False)

# %% [markdown]
# **The most central nodes are the ones to protect.** A change to `stg_transactions` or
# `int_transactions_enriched` reaches dozens of tables (marts, features, graph, serving, privacy, audit). Those
# models carry the most tests and must keep the reproducibility guard (model-risk notes, `test_dbt_determinism.py`).

# %% [markdown]
# ## 4 · A real ordering defect: a node that reads a later task group
# Task groups run in sequence, but dbt dependencies do not know about the groups. The emulator checks every edge for
# a node that reads something Airflow builds **later**.

# %%
fwd = pl.forward_dependencies()
show(fwd, paging=False)

# %% [markdown]
# **Finding.** `mart_credit_eligibility` (task group `gold`) reads `feat_credit_eligibility_pit` (task group
# `features_graph_knowledge`, which runs after `gold`).
#
# * On a **fresh lakehouse** the gold group fails: the feature table does not exist yet.
# * On every **later run** the mart reads the feature table of the **previous run**: eligibility decisions lag the
#   data by one run. With a daily schedule, a customer whose overdue balance was paid yesterday is still declined
#   today, and an approval can rest on yesterday's income.
#
# **Why it happened.** The Cosmos selectors are paths (`path:models/gold`), not graph selections. A mart that needs
# a feature crosses the boundary silently.
#
# **What to do (recommended).** Move `mart_credit_eligibility` next to its input. Either place it under
# `models/features/` or a new `models/marts_on_features/` path selected after the features group, or select the gold
# group as `path:models/gold` minus `+feat_*` children and add a later group for them. Add a CI test that fails when
# `forward_dependencies()` is not empty (this function, or the same check on the manifest in
# `platform/libs/tests`), so the defect cannot come back. The emulator builds in true dependency order, so the
# series is not affected.

# %% [markdown]
# ## 5 · Task group `seeds`: reference data and policy in git
# Seeds are small, reviewed CSVs. Putting policy in seeds (rather than in code or in a spreadsheet) means every
# threshold has an author, a review and a history, and a model change and its policy change land in the same pull
# request.

# %%
seeds = pl.build_layer("seeds", rebuild=True)
desc = {
    pl.name(k2): (pl.nodes[k2].get("description") or "").strip() for k2 in pl.layer_nodes("seeds")
}
seeds["what it encodes"] = seeds["node"].map(desc)
show(seeds[["node", "rows", "what it encodes"]], paging=False)

# %% [markdown]
# | seed | used by | why it is a seed |
# |---|---|---|
# | `country_codes` | staging of every table with a country | maps raw spellings (`México`, `Mexico`) to ISO codes, home currency and UTC offset; a new spelling is a one-line review |
# | `response_codes` | `int_transactions_enriched`, card support, inquiries | decodes authorisation codes into a meaning, a customer message (ES/EN) and a next action |
# | `dq_rule_slo` | `audit.dq_rule_summary`, `dq_gate` | baseline and maximum rate per integrity rule: the SLO the gate enforces |
# | `dq_cell_rule_slo` | `audit.dq_rule_summary` | the same for cell-level contract rules (C01–C10) |
# | `source_contract_columns` | quality models | the reviewed source contracts as a table: types, required flags, drift baselines |
# | `restricted_pii_columns` | governance tests, this series' masking | columns that must never leave the restricted silver schema |
# | `protected_attributes` | fairness isolation test | attributes (gender, marital status…) kept apart from model features |

# %%
show(pl.q("select * from {dq_rule_slo} order by rule_id"), paging=False)
show(
    pl.q(
        "select response_code, meaning, customer_actionable, suggested_action from {response_codes}"
    ),
    paging=False,
)
show(pl.q("select * from {country_codes}"), paging=False)

# %% [markdown]
# **Two decisions visible in the seeds.**
# * `dq_rule_slo` gives **R21, R25 and R26 a maximum of 0 %** while their measured baselines are 50 %, 66 % and 7 %.
#   The policy says these must never happen; the data violates them by construction. `enforce_in_dev = false` keeps
#   the gate from blocking every run in development. In production they must either be enforced (and the source
#   fixed) or the marts must exclude the violating rows: that is decision *slo-breach-rules* on the decision board.
# * `country_codes` contains **both `México` and `Mexico`**. Staging maps both to `MX`, so the accent variant never
#   reaches gold. The cell finding (V2) is still recorded in silver (notebook 02), because the source should be told.

# %% [markdown]
# ## Findings and what to do
# 1. **The emulator runs Airflow's exact SQL.** 7 task groups, 109 buildable nodes and 107 data tests, compiled by
#    dbt and executed here in dependency order. Fidelity against the live lakehouse is checked in notebook 12.
# 2. **Ordering defect (fix recommended).** `mart_credit_eligibility` reads a feature table built one task group
#    later: stale by one run, or failing on a fresh lakehouse. Move it after the features group and add a CI check.
# 3. **Policy lives in seeds**, reviewed in git. Before production, decide the three SLOs at 0 % (R21, R25, R26).
# 4. **Central nodes** (`stg_transactions`, `int_transactions_enriched`, `int_customer_profile`) feed most of the
#    platform: changes there need the full test suite and the two-build reproducibility check.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
