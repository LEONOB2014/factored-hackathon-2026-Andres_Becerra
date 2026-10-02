# %% [markdown]
# # 05 · Comparison of comparable rows
# **CRISP-DM phase 4 (modelling / analysis)** · hypothesis **H5**: *records that exist in both folders have been silently mutated.*
#
# Only rows that can be paired with confidence are compared (notebook 04):
#
# | pair set | size | how paired |
# |---|---|---|
# | customers — same ID, same person | 3,023 | ID + 4/4 identity fields |
# | customers — same ID, edited identity | ≈ 250 | ID + 1–3/4 identity fields |
# | customers — same person, **different ID** | 7,531 | Fellegi–Sunter score ≥ 10 |
# | products | 146,398 | `product_number` |
# | agents | 631 | `employee_code` |
# | transactions — clones | 11,734 | ID + identical content |
# | complaints | 67,095 | ID (text identical) |
#
# We ask for each pair set: **which fields changed, how often, in which direction, and is it more than chance?**

# %%
import sys

sys.path.insert(0, "../src")
import ipywidgets as w
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import display
from plotly.subplots import make_subplots

from latam_eda import theme
from latam_eda.data import ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"


def agreement(sql_from: str, cols, extra_where="") -> pd.DataFrame:
    """% of pairs where main = backup (null = null counts as equal), plus % that went value→null / null→value."""
    parts = []
    for c in cols:
        parts.append(f"""select '{c}' as field,
            avg(((m.{c} is not distinct from b.{c}))::int) as agree,
            avg((m.{c} is not null and b.{c} is null)::int) as lost,
            avg((m.{c} is null and b.{c} is not null)::int) as gained,
            avg((m.{c} is not null and b.{c} is not null and m.{c} <> b.{c})::int) as changed
            {sql_from} {extra_where}""")
    return con.sql(" union all ".join(parts)).df()


# %% [markdown]
# ## 1 · Customers that share an ID — three kinds of pair
# The identity fields (document, first name, last name, birth date) split the 4,025 ID-sharing customers into *same person*, *edited* and *different person*.

# %%
ID_FROM = "from m_customers m join b_customers b using(customer_id)"
con.sql(f"""create or replace view cust_id_pairs as
  select m.customer_id, (m.document_number=b.document_number)::int + (m.first_name=b.first_name)::int
         + (m.last_name=b.last_name)::int + (m.date_of_birth=b.date_of_birth)::int as n_agree
  {ID_FROM}""")
con.sql(
    "create or replace view cust_same as select customer_id from cust_id_pairs where n_agree = 4"
)
con.sql(
    "create or replace view cust_edit as select customer_id from cust_id_pairs where n_agree between 1 and 3"
)
con.sql(
    "create or replace view cust_diff as select customer_id from cust_id_pairs where n_agree = 0"
)
print(
    con.sql(
        "select (select count(*) from cust_same) same_person, (select count(*) from cust_edit) edited, (select count(*) from cust_diff) different_person"
    )
    .df()
    .to_string(index=False)
)

# %%
CUST_COLS = [c[0] for c in con.sql("describe m_customers").fetchall() if c[0] != "customer_id"]
res = {}
for name, v in (
    ("same person (4/4)", "cust_same"),
    ("edited identity (1–3/4)", "cust_edit"),
    ("different person (0/4)", "cust_diff"),
):
    res[name] = agreement(
        f"from m_customers m join b_customers b using(customer_id) join {v} using(customer_id)",
        CUST_COLS,
    ).set_index("field")
ag = pd.DataFrame({k: v.agree for k, v in res.items()}) * 100
ag = ag.loc[ag["same person (4/4)"].sort_values().index]
fig = go.Figure(
    go.Heatmap(
        z=ag.values,
        x=ag.columns,
        y=ag.index,
        zmin=0,
        zmax=100,
        colorscale=[[0, "#cde2fb"], [0.5, "#3987e5"], [1, "#0d366b"]],
        colorbar=dict(title="% equal"),
        hovertemplate="%{y}<br>%{x}<br>%{z:.1f} % equal<extra></extra>",
    )
)
fig.update_layout(
    title="Field agreement for customers that share an ID", height=720, margin=dict(l=190)
)
fig.show()

# %% [markdown]
# **Reading the heatmap.** The three groups behave completely differently:
# * **same person (4/4)** — records are **bit-identical in every field except `credit_score`** (81 % equal); income, registration date and `last_updated` differ in ≈ 0.5 % of rows.
# * **edited identity (1–3/4)** — a *hybrid*: some identity fields agree, others do not, and almost every other field agrees only partially.
# * **different person (0/4)** — agreement is at **chance level** (≈ 0 for names/dates/documents; ≈ 40–60 % only for low-entropy fields such as `country`, `gender`, `document_type`).

# %% [markdown]
# ## 2 · What kind of change? A mismatch taxonomy
# (a) **Same-person pairs:** only `credit_score` moves — how?  (b) **Edited-identity pairs:** which fields disagree, and what *kind* of disagreement is it?

# %%
CS = con.sql("""select m.credit_score mcs, b.credit_score bcs, m.estimated_monthly_income mi, b.estimated_monthly_income bi
                from m_customers m join b_customers b using(customer_id) join cust_same using(customer_id)""").df()
cs = CS.dropna(subset=["mcs", "bcs"])
delta = cs.bcs - cs.mcs
nz = delta[delta != 0]
tab = pd.Series(
    {
        "pairs with both scores": len(cs),
        "scores unchanged": int((delta == 0).sum()),
        "scores changed": len(nz),
        "changed %": 100 * len(nz) / len(cs),
        "median |Δ| among changed": nz.abs().median(),
        "sd of Δ among changed": nz.std(),
        "mean Δ (bias)": nz.mean(),
        "values moved to / from null": int(((CS.mcs.isna()) != (CS.bcs.isna())).sum()),
        "income changed": int(((CS.mi != CS.bi) & CS.mi.notna() & CS.bi.notna()).sum()),
    }
)
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=[
        "Δ credit_score (backup − main), changed rows",
        "Backup vs main score (changed rows)",
    ],
)
fig.add_histogram(x=nz, nbinsx=60, marker_color=theme.BLUE, showlegend=False, row=1, col=1)
fig.add_scatter(
    x=cs.mcs[delta != 0],
    y=cs.bcs[delta != 0],
    mode="markers",
    marker=dict(size=4, color=theme.BLUE, opacity=0.5),
    showlegend=False,
    row=1,
    col=2,
)
fig.add_scatter(
    x=[420, 850],
    y=[420, 850],
    mode="lines",
    line=dict(color="#8a8984", dash="dot"),
    showlegend=False,
    row=1,
    col=2,
)
fig.update_layout(height=380, title="Credit-score re-scoring among otherwise identical customers")
fig.show()
tab.to_frame("value").style.format("{:,.2f}")

# %% [markdown]
# **Interpretation (a).** In **22 % of identical customers (519 of 2,330 with a score)** the credit score was **re-scored with symmetric noise** (bias +2 points, median |Δ| = 34, sd ≈ 55 points,
# strongly correlated with the original) — no nulls appear or disappear and nothing else about the customer changes. It reads like a periodic score refresh
# applied to a random subset, not a corruption of identity.

# %%
edit = con.sql("""select m.*, b.document_number b_doc, b.first_name b_fn, b.last_name b_ln, b.date_of_birth b_dob, b.country b_country, b.segment b_segment,
                         b.customer_status b_status, b.city b_city, b.email b_email, b.document_type b_dtype
                  from m_customers m join b_customers b using(customer_id) join cust_edit using(customer_id)""").df()


def doc_class(a, b):
    if a == b:
        return "equal"
    a, b = str(a), str(b)
    if a.lstrip("0") == b.lstrip("0"):
        return "leading zeros added/removed"
    if len(a) == len(b) and sorted(a) == sorted(b):
        return "digits permuted"
    if a[1:] == b[:-1] or a[:-1] == b[1:]:
        return "shifted by one digit"
    if len(a) != len(b):
        return "different length"
    return "other substitution"


edit["doc_change"] = [doc_class(a, b) for a, b in zip(edit.document_number, edit.b_doc)]
dc = edit.doc_change.value_counts().rename("pairs").to_frame()
dc["%"] = 100 * dc.pairs / len(edit)
dc.style.format({"pairs": "{:,.0f}", "%": "{:.1f}"})

# %% [markdown]
# **Interpretation (b).** Among the 245 edited-identity pairs 86 % keep the document number, while 14 % rewrite it — mostly to a **different length** (10 %; a different document
# type), otherwise substituted or shifted by a digit; there is no zero-padding case. Together with city differing in 70 % and country in 36 % of these pairs, they look like a **blend of two real records**
# rather than one customer updated twice.

# %%
cat_pairs = {
    "country": "b_country",
    "segment": "b_segment",
    "customer_status": "b_status",
    "document_type": "b_dtype",
    "city": "b_city",
}
rows = []
for f, bf in cat_pairs.items():
    a, b = edit[f], edit[bf]
    rows.append(
        dict(
            field=f,
            equal_pct=100 * (a.fillna("∅") == b.fillna("∅")).mean(),
            changed_pct=100 * (a.notna() & b.notna() & (a != b)).mean(),
            value_to_null_pct=100 * (a.notna() & b.isna()).mean(),
            null_to_value_pct=100 * (a.isna() & b.notna()).mean(),
        )
    )
tax = pd.DataFrame(rows).sort_values("equal_pct")
tax.to_csv(OUT / "customers_mismatch_taxonomy.csv", index=False)
tax.style.format(dict.fromkeys(tax.columns[1:], "{:.1f}"))

# %% [markdown]
# ## 3 · Is the change *recorded*? `last_updated` vs credit-score re-scoring
# A legitimate refresh should move `last_updated`. We test it on the 2,762 same-person customers.

# %%
lu = con.sql("""select m.last_updated mu, b.last_updated bu, (m.credit_score is not distinct from b.credit_score) cs_same
                from m_customers m join b_customers b using(customer_id) join cust_same using(customer_id)""").df()
lu["last_updated_identical"] = lu.mu == lu.bu
lu.groupby("cs_same").last_updated_identical.agg(share_identical="mean", pairs="size").style.format(
    {"share_identical": "{:.1%}", "pairs": "{:,.0f}"}
)

# %% [markdown]
# **Interpretation.** Rows whose score changed have the **same `last_updated`** (98.5 %) as rows whose score did not (99.9 %): the value moved but the
# audit column did not. In a bank this is a **change-control red flag** — a modification without a trace.

# %% [markdown]
# ## 4 · Transition matrices (edited-identity customers)
# Where do the disagreeing values go? (245 pairs — read as a pattern, not as statistics.)


# %%
def transition(f, bf, top=6):
    t = pd.crosstab(edit[f].fillna("∅"), edit[bf].fillna("∅"))
    keep = t.sum(axis=1).sort_values(ascending=False).index[:top]
    keepc = t.sum(axis=0).sort_values(ascending=False).index[:top]
    return t.loc[keep, keepc]


fig = make_subplots(
    rows=1,
    cols=3,
    subplot_titles=["country (main → backup)", "segment", "customer_status"],
    horizontal_spacing=0.12,
)
for i, (f, bf) in enumerate(
    (("country", "b_country"), ("segment", "b_segment"), ("customer_status", "b_status")), 1
):
    t = transition(f, bf)
    fig.add_heatmap(
        z=np.log10(t.values + 1),
        x=t.columns,
        y=t.index,
        text=t.values,
        texttemplate="%{text}",
        showscale=False,
        colorscale=[[0, "#f0efec"], [1, "#184f95"]],
        row=1,
        col=i,
    )
fig.update_yaxes(autorange="reversed")
fig.update_layout(
    height=420,
    title="Transitions among edited-identity customers (colour = log count; cells show counts)",
)
fig.show()

# %% [markdown]
# **Interpretation.** In the edited group the diagonal still holds the majority for `country` (64.5 %), `segment` (83 %) and `customer_status` (99 %), but **`city` disagrees in 70 %** —
# the geography fields are what come apart, with no single dominant destination, consistent with *mixed* records rather than a rule-based re-coding.
# %% [markdown]
# ## 5 · Products paired on `product_number`
# Pair set: 146,398 pairs = 121,448 that also share the `product_id` + 24,950 found only through `product_number`.

# %%
prod = con.sql("""select m.product_id mid, b.product_id bid, m.product_type mt, b.product_type bt, m.currency mc, b.currency bc,
                         m.current_balance mb, b.current_balance bb, m.credit_limit ml, b.credit_limit bl,
                         m.product_status ms, b.product_status bs, m.opening_date mo, b.opening_date bo, m.customer_id mcu, b.customer_id bcu
                  from m_products m join b_products b using(product_number)""").df()
prod["same_id"] = prod.mid == prod.bid
g = prod.groupby("same_id").apply(
    lambda d: pd.Series(
        {
            "pairs": len(d),
            "same type %": 100 * (d.mt == d.bt).mean(),
            "same status %": 100 * (d.ms == d.bs).mean(),
            "same opening_date %": 100 * (d.mo == d.bo).mean(),
            "same currency %": 100 * (d.mc == d.bc).mean(),
            "same balance %": 100 * (d.mb == d.bb).mean(),
            "same owner id %": 100 * (d.mcu == d.bcu).mean(),
        }
    ),
    include_groups=False,
)
g.index = g.index.map({True: "same product_id", False: "different product_id"})
g.style.format({"pairs": "{:,.0f}", **dict.fromkeys(g.columns[1:], "{:.1f}")})

# %% [markdown]
# **Reading the table.** For ID-matched products type, status and opening date agree (≈ 99 %), whereas **currency and balance agree in only ≈ 48 %** — and
# the two move together. For products matched **only** by number the agreement is much lower on every field: those are *not* the same product, just a repeated number.
# The owner id never agrees.

# %%
same_id = prod[prod.same_id]
fx = (
    same_id.groupby(["mc", "bc"])
    .apply(
        lambda d: pd.Series(
            {
                "pairs": len(d),
                "median ratio (backup ÷ main)": (d.bb / d.mb).replace([np.inf], np.nan).median(),
                "sd of log10 ratio": np.log10(
                    (d.bb / d.mb).replace([0, np.inf], np.nan).dropna()
                ).std(),
            }
        ),
        include_groups=False,
    )
    .reset_index()
)
fx = fx.sort_values("pairs", ascending=False)
fx.to_csv(OUT / "product_currency_redenomination.csv", index=False)
fx.style.format(
    {"pairs": "{:,.0f}", "median ratio (backup ÷ main)": "{:,.4f}", "sd of log10 ratio": "{:.3f}"}
)

# %% [markdown]
# **A systematic re-denomination.** When the currency differs, the balance is multiplied by a **fixed rate**: USD→COP ×4,000, USD→ARS ×350 (hence COP→ARS ×0.0875 and ARS→COP ×11.43).
# So the backup keeps the *economic* balance but **re-labels the currency** for ≈ 52 % of products, using a flat rate that ignores the daily FX table. After converting to USD
# the balances agree again:

# %%
rate = {"USD": 1.0, "COP": 4000.0, "ARS": 350.0}
same_id = same_id.assign(
    mb_usd=same_id.mb / same_id.mc.map(rate), bb_usd=same_id.bb / same_id.bc.map(rate)
)
ok = same_id[(same_id.mb_usd > 0) & (same_id.bb_usd > 0)]
rel = (ok.bb_usd / ok.mb_usd - 1).abs()
conv = pd.Series(
    {
        "ID-matched products with balance in both": len(ok),
        "balance equal in native currency (%)": 100 * (same_id.mb == same_id.bb).mean(),
        "balance equal after USD normalisation at 4000 / 350 (%, within 0.1 %)": 100
        * (rel <= 0.001).mean(),
        "within 1 % after normalisation (%)": 100 * (rel <= 0.01).mean(),
    }
)
fig = go.Figure()
bins = np.linspace(-5, 5, 121)
for vals, nm, col in (
    (np.log10((ok.bb / ok.mb).clip(1e-5, 1e5)), "native currency", theme.ORANGE),
    (np.log10((ok.bb_usd / ok.mb_usd).clip(1e-5, 1e5)), "after USD normalisation", theme.BLUE),
):
    cnt, edg = np.histogram(vals, bins=bins)
    fig.add_bar(x=(edg[:-1] + edg[1:]) / 2, y=cnt, name=nm, marker_color=col, opacity=0.8)
fig.update_layout(
    barmode="overlay",
    height=360,
    yaxis_type="log",
    title="log10(balance backup ÷ balance main): the spread collapses once currencies are aligned",
    xaxis_title="log10 ratio",
    yaxis_title="products (log)",
)
fig.show()
conv.to_frame("value").style.format("{:,.1f}")

# %% [markdown]
# **Interpretation.** Normalising currencies explains almost all of the balance "mismatch", so for products the backup is largely a **re-denominated copy**
# of the same economic state — except for the **owner**: `customer_id` of the product disagrees in 100 % of pairs, i.e. every product was **re-attributed** to a different customer.
# The owner mapping implied by products (≈ 94 k distinct main→backup customer pairs) is **not** the one implied by identity linkage (notebook 04: only 1 of 94,185
# pairs coincides). So the re-attribution is not a re-keying of the same person; it moves products between customers.

# %% [markdown]
# ## 6 · Transaction clones: what *else* changed when the record was re-dated?
# %%
cl = con.sql("""select m.transaction_id, m.process_date md, b.process_date bd, m.transaction_status ms, b.transaction_status bs,
                       m.amount_usd mu, b.amount_usd bu, m.branch_id mbr, b.branch_id bbr, m.transaction_city mcity, b.transaction_city bcity,
                       m.is_fraud mf, b.is_fraud bf, m.response_code mr, b.response_code br, m.customer_id mc, b.customer_id bc,
                       m.product_id mp, b.product_id bp, m.latitude mla, b.latitude bla,
                       cast(m.transaction_date as time) mtod, cast(b.transaction_date as time) btod
                from m_transactions m join b_transactions b using(transaction_id)
                where m.amount = b.amount and m.currency = b.currency and m.transaction_type = b.transaction_type and m.channel = b.channel
                  and m.fraud_score is not distinct from b.fraud_score and m.merchant_name is not distinct from b.merchant_name""").df()
rows = [
    ("same customer", (cl.mc == cl.bc).mean()),
    ("same product", (cl.mp == cl.bp).mean()),
    ("same status", (cl.ms == cl.bs).mean()),
    ("same response code", (cl.mr.fillna("∅") == cl.br.fillna("∅")).mean()),
    (
        "same amount_usd (when both set)",
        (cl.mu[cl.mu.notna() & cl.bu.notna()] == cl.bu[cl.mu.notna() & cl.bu.notna()]).mean(),
    ),
    ("same city", (cl.mcity.fillna("∅") == cl.bcity.fillna("∅")).mean()),
    ("same branch", (cl.mbr.fillna("∅") == cl.bbr.fillna("∅")).mean()),
    ("same is_fraud", (cl.mf == cl.bf).mean()),
    ("same time of day", (cl.mtod == cl.btod).mean()),
]
clone_tab = pd.DataFrame(rows, columns=["field", "agreement"])
clone_tab.to_csv(OUT / "transaction_clone_agreement.csv", index=False)
clone_tab.style.format({"agreement": "{:.1%}"})

# %% [markdown]
# **Interpretation.** A clone is the *same event* (amount, merchant, channel, fraud score, status, response code, `amount_usd`, time of day, branch agree) **posted to a
# different customer and product** and **a few days later**. Only 27 % keep the transaction *city*, so city follows the new owner. In banking terms this is a transaction that
# was **re-attributed and re-dated** — the most damaging combination for reconciliation. It affects only 0.27 % of main, but each such pair breaks customer-level balances.

# %% [markdown]
# ## 7 · Complaints — the control group
# Complaints keep text, dates, status and amounts; only the three foreign keys differ. They are our **negative control**: any
# method that flags complaints as different in content is wrong.

# %%
comp_cols = [c[0] for c in con.sql("describe m_complaints").fetchall() if c[0] != "complaint_id"]
ca = agreement("from m_complaints m join b_complaints b using(complaint_id)", comp_cols).set_index(
    "field"
)
ca[ca.agree < 1].assign(agree=lambda d: d.agree * 100)[["agree"]].style.format("{:.2f}")

# %% [markdown]
# **Interpretation.** Only `customer_id` (0 % equal), `affected_product_id` (33.6 % — those are the rows that are null in both) and `assigned_agent_id` (67.1 % — the rows null in both)
# differ; **all other 24 columns are 100 % equal**. The control behaves as expected, and it confirms that the generator re-keys foreign keys **independently** of attributes.

# %% [markdown]
# ## Interactive explorer — field agreement by table
# *(Needs a live kernel.)* Pick a table and see the share of equal / lost / gained / changed values per field.

# %%
SOURCES = {
    "customers (same ID)": ("from m_customers m join b_customers b using(customer_id)", CUST_COLS),
    "products (same ID)": (
        "from m_products m join b_products b using(product_id)",
        [c[0] for c in con.sql("describe m_products").fetchall() if c[0] != "product_id"],
    ),
    "service_agents (same ID)": (
        "from m_service_agents m join b_service_agents b using(agent_id)",
        [c[0] for c in con.sql("describe m_service_agents").fetchall() if c[0] != "agent_id"],
    ),
    "complaints (same ID)": (
        "from m_complaints m join b_complaints b using(complaint_id)",
        comp_cols,
    ),
}
cache = {}
dd = w.Dropdown(options=list(SOURCES), description="pairs")
out = w.Output()


def draw(_=None):
    k = dd.value
    if k not in cache:
        cache[k] = agreement(*SOURCES[k]).set_index("field").sort_values("agree")
    d = cache[k]
    out.clear_output(wait=True)
    f = go.Figure()
    for col, name, colr in (
        ("agree", "equal", theme.BLUE),
        ("changed", "changed value", theme.ORANGE),
        ("lost", "value → null", theme.MAGENTA),
        ("gained", "null → value", theme.AQUA),
    ):
        f.add_bar(y=d.index, x=d[col] * 100, orientation="h", name=name, marker_color=colr)
    f.update_layout(
        barmode="stack",
        height=max(380, 22 * len(d)),
        title=f"{k}: what happened to each field (% of pairs)",
        xaxis_title="% of pairs",
        margin=dict(l=190),
    )
    with out:
        display(f)


dd.observe(draw, "value")
draw()
display(w.VBox([dd, out]))

# %% [markdown]
# ## Findings (H5)
# | # | finding |
# |---|---|
# | 1 | Of 4,025 customers sharing an ID: **68.6 % are bit-identical** (except a re-scored credit score in 22 % of scored customers), **6.1 % are hybrid** (partial identity), **25.3 % are a different person** |
# | 2 | The credit-score refresh moves the value but **not `last_updated`** (98.5 % identical timestamps) — an untraced change |
# | 3 | Hybrid customers: document number rewritten in 14 % (mostly different length), city differs in 70 %, country in 36 % |
# | 4 | Products: same type, status and opening date; **currency re-denominated at fixed 4,000 COP and 350 ARS per USD** in ≈ 52 % of cases; balances agree in USD; **owner differs in 100 %** |
# | 5 | Transaction clones are **re-attributed (customer, product, city) and re-dated** |
# | 6 | Complaints (control) differ **only** in foreign keys |
#
# **H5 is supported, with nuance:** mutation is *not* a uniform field-level noise. It has distinct, systematic components — an untraced score refresh, a flat-rate currency
# re-denomination, and re-attribution of products/transactions to other customers.
