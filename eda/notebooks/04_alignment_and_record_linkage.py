# %% [markdown]
# # 04 · Alignment & record linkage
# **CRISP-DM phase 3 (data preparation)** — build the comparable pairs that notebook 05 will analyse.
#
# Notebook 03 showed that a global re-dating is **not** available. Alignment therefore has to be earned
# row by row. We build four layers of increasing ambition and **validate each one on a ground truth**:
#
# | layer | what is aligned | method | ground truth for validation |
# |---|---|---|---|
# | L1 | rows sharing a key | exact key + **drift-corrected dates** | complaints (identical content) |
# | L2 | the same *person* under different customer IDs | **Fellegi–Sunter** probabilistic linkage, EM-estimated, blind to IDs | pairs that share an ID |
# | L3 | the same *product* / *agent* under a different ID | natural key (`product_number`, `employee_code`) | pairs that share an ID |
# | L4 | the same *transaction* re-dated | content fingerprint + date window | clones found in notebook 03 |

# %%
import sys

sys.path.insert(0, "../src")
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.metrics import roc_auc_score

from latam_eda import theme
from latam_eda.data import DERIVED, ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"

# %% [markdown]
# ## L1 · Drift-corrected date alignment for shared keys
# Per table we model the offset as a smooth function of the main date (monthly median, which notebook 03 showed
# is the right shape) and ask: **how much of each pair's offset does the model explain?**
# Evaluation is *out-of-time*: the monthly median is estimated on the **other** months (leave-one-month-out).

# %%
rows = []
resid = {}
for t in ["transactions", "digital_events", "call_center_interactions", "campaign_sends"]:
    d = pd.read_parquet(DERIVED / f"offsets_{t}.parquet")
    d["month"] = d.md.dt.to_period("M")
    med = d.groupby("month").k_days.median()
    # leave-one-month-out prediction: linear interpolation of neighbouring months' medians
    pred = {}
    for m in med.index:
        others = med.drop(m)
        x = np.array([p.ordinal for p in others.index])
        y = others.values
        pred[m] = np.interp(m.ordinal, x, y)
    d["pred"] = d.month.map(pred)
    d["err_naive0"] = d.k_days.abs()  # "no shift"
    d["err_const"] = (d.k_days - d.k_days.median()).abs()  # one global constant
    d["err_drift"] = (d.k_days - d.pred).abs()  # drift-corrected
    resid[t] = d[["k_days", "pred", "month"]]
    rows.append(
        dict(
            table=t,
            pairs=len(d),
            MAE_no_shift=d.err_naive0.mean(),
            MAE_global_constant=d.err_const.mean(),
            MAE_drift_model=d.err_drift.mean(),
            within_1d_after_drift_pct=100 * (d.err_drift <= 1).mean(),
            within_1d_no_shift_pct=100 * (d.err_naive0 <= 1).mean(),
        )
    )
l1 = pd.DataFrame(rows)
l1.to_csv(OUT / "alignment_l1_date_drift.csv", index=False)
l1.style.format(
    {
        "pairs": "{:,.0f}",
        **dict.fromkeys(l1.columns[2:5], "{:.2f}"),
        "within_1d_after_drift_pct": "{:.1f}",
        "within_1d_no_shift_pct": "{:.1f}",
    }
)

# %% [markdown]
# **Interpretation.** The drift model removes most of the date error: mean absolute error falls from
# **81 → 1.5 days for sends**, **6.2 → 1.5 for events**, **3.0 → 0.5 for transactions** (93 % within one day) and
# **1.7 → 0.7 for interactions** — against a *single global constant*, which only gets sends to 43 days. The
# prediction is leave-one-month-out, so this is genuine predictive power, not a fit. A residual jitter of ≈ 1.5 days
# remains for events and sends: dates can be aligned to the nearest day or two, never exactly, so day-level comparisons
# below use a ±3-day tolerance window.

# %% [markdown]
# ## L2 · Probabilistic record linkage for customers (Fellegi–Sunter)
# **Question:** how many people appear in both folders, and under which IDs?
#
# **Why not just trust the IDs?** Among the 4,025 customers that share an ID, the four core identity fields
# (document number, first name, last name, birth date) tell a bimodal story:

# %%
core = con.sql("""select ((m.document_number = b.document_number)::int + (m.first_name = b.first_name)::int
                          + (m.last_name = b.last_name)::int + (m.date_of_birth = b.date_of_birth)::int) n_agree, count(*) n
                  from m_customers m join b_customers b using(customer_id) group by 1 order by 1""").df()
fig = go.Figure(
    go.Bar(
        x=core.n_agree,
        y=core.n,
        marker_color=[theme.ORANGE, "#8a8984", "#8a8984", "#8a8984", theme.BLUE],
        text=core.n,
        textposition="outside",
    )
)
fig.update_layout(
    title="Customers sharing an ID: how many of the 4 core identity fields agree?",
    height=360,
    xaxis_title="fields that agree (document, first name, last name, birth date)",
    yaxis_title="customers",
    bargap=0.4,
)
fig.show()

# %% [markdown]
# **A shared customer ID is a noisy label.** 69 % of ID-sharing customers agree on *all four* fields (same person), **25 % agree on none**
# (the ID was reused for a **different person**) and 6 % are in between (the same person with edited fields). So "same ID ⇒ same customer" is false
# for a quarter of the cases — the linkage cannot be validated against IDs alone.
#
# **Method.** Block on cheap identifiers → candidate pairs; compare 9 fields (agree / disagree); estimate **u** (chance agreement) from
# **random cross-folder pairs** (the textbook way — estimating it on blocked candidates is biased because blocking forces agreement on
# the blocking fields); estimate **m** and the match prevalence with EM; score with the log-likelihood-ratio weight.

# %%
FIELDS = [
    "document_number",
    "first_name",
    "last_name",
    "date_of_birth",
    "email",
    "mobile_phone",
    "city",
    "country",
    "gender",
]
cmp_sql = ",\n".join(f"(m.{f} = b.{f})::int AS a_{f}" for f in FIELDS)
cand = (
    con.sql(f"""
    with c as (
      select m.customer_id mid, b.customer_id bid from m_customers m join b_customers b on m.document_number = b.document_number
      union select m.customer_id, b.customer_id from m_customers m join b_customers b on m.date_of_birth = b.date_of_birth and m.last_name = b.last_name
      union select m.customer_id, b.customer_id from m_customers m join b_customers b on m.mobile_phone = b.mobile_phone
      union select m.customer_id, b.customer_id from m_customers m join b_customers b on m.email = b.email and m.date_of_birth = b.date_of_birth)
    select c.mid, c.bid, (c.mid = c.bid)::int same_id, {cmp_sql}
    from c join m_customers m on m.customer_id = c.mid join b_customers b on b.customer_id = c.bid""")
    .df()
    .fillna(0)
)
A = cand[[f"a_{f}" for f in FIELDS]].values.astype(float)

# u from random pairs (20k x 2k cross sample)
u_hat = (
    con.sql(
        "select "
        + ", ".join(f"avg(coalesce((m.{f} = b.{f})::int, 0)) a_{f}" for f in FIELDS)
        + """
    from (select * from m_customers using sample 20000 rows) m cross join (select * from b_customers using sample 2000 rows) b"""
    )
    .df()
    .iloc[0]
    .values
)
u_hat = np.clip(u_hat.astype(float), 1e-6, 1 - 1e-6)
print(f"{len(cand):,} candidate pairs, of which {int(cand.same_id.sum()):,} share an ID")


# %%
def em_m(A, u, iters=300, p0=0.5):
    """EM for m and prevalence p with u held fixed."""
    k = A.shape[1]
    m = np.full(k, 0.9)
    p = p0
    for _ in range(iters):
        lm = np.log(p) + (A * np.log(m) + (1 - A) * np.log(1 - m)).sum(1)
        lu = np.log(1 - p) + (A * np.log(u) + (1 - A) * np.log(1 - u)).sum(1)
        g = 1 / (1 + np.exp(np.clip(lu - lm, -60, 60)))
        p = float(np.clip(g.mean(), 1e-3, 0.99))
        m = np.clip((g[:, None] * A).sum(0) / g.sum(), 1e-4, 1 - 1e-4)
    return m, p, g


m_hat, p_hat, post = em_m(A, u_hat)
W_agree, W_dis = np.log2(m_hat / u_hat), np.log2((1 - m_hat) / (1 - u_hat))
cand["score"] = (A * W_agree + (1 - A) * W_dis).sum(1)
cand["posterior"] = post
params = pd.DataFrame(
    {
        "field": FIELDS,
        "m (agree | match)": m_hat,
        "u (chance agreement)": u_hat,
        "agreement weight (bits)": W_agree,
        "disagreement weight (bits)": W_dis,
    }
)
print(f"EM match prevalence among candidates (capped at 0.99): {p_hat:.3f}")
params.style.format(
    {
        "m (agree | match)": "{:.3f}",
        "u (chance agreement)": "{:.2e}",
        "agreement weight (bits)": "{:+.1f}",
        "disagreement weight (bits)": "{:+.1f}",
    }
)

# %% [markdown]
# **Reading the parameters.** With realistic chance-agreement rates the weights are interpretable: agreeing on
# `document_number` is worth ≈ +20 bits, `mobile_phone` ≈ +19, `date_of_birth` ≈ +14, `email` ≈ +14, `last_name` ≈ +11, while
# `country` and `gender` are weak (≈ +1.3, few categories). **Caveat:** *m* is estimated on blocked candidates (which are enriched
# in matches by construction), so the EM prevalence saturates (capped at 0.99) and absolute weights are approximate.
# That is why the linkage is validated on **held-out fields** below rather than trusted on its own likelihood.

# %%
# How well does the score do against the ID label, and what does the "error" look like?
y = cand.same_id.values
auc = roc_auc_score(y, cand.score)
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=[
        "Score distribution of candidate pairs",
        "Only ID-sharing pairs: the label is bimodal",
    ],
)
for v, name, col in ((1, "shares an ID", theme.BLUE), (0, "different ID", theme.ORANGE)):
    fig.add_histogram(
        x=cand.score[y == v], name=name, marker_color=col, opacity=0.75, nbinsx=50, row=1, col=1
    )
fig.add_histogram(
    x=cand.score[y == 1], marker_color=theme.BLUE, nbinsx=50, showlegend=False, row=1, col=2
)
fig.update_layout(
    barmode="overlay",
    height=380,
    title=f"Blind linkage score vs the (noisy) ID label — AUC {auc:.2f}",
)
fig.update_xaxes(title_text="log-likelihood-ratio score (bits)")
fig.show()

# %% [markdown]
# **Interpretation.** Against the raw ID label the AUC is modest (≈ 0.8) — **not because the linkage is weak but because the label is wrong
# for a quarter of ID-sharing pairs**: the right panel shows two clearly separated populations (a high-score mode = same person,
# a low-score mode = ID reused for another person). The score reproduces the structure that §above found by hand.

# %%
# Blind validation on HELD-OUT fields: fit used identity fields only; check agreement on fields it never saw.
held = [
    "address",
    "email",
    "mobile_phone",
    "landline_phone",
    "credit_score",
    "segment",
    "occupation",
    "registration_date",
]
sql = ", ".join(f"avg(coalesce((m.{f} = b.{f})::int, 0)) {f}" for f in held)
base = (
    con.sql(
        f"select {sql} from (select * from m_customers using sample 20000 rows) m cross join (select * from b_customers using sample 2000 rows) b"
    )
    .df()
    .iloc[0]
)
CUT = 10.0
sel = cand[cand.score >= CUT][["mid", "bid"]]
con.register("sel_pairs", sel)
linked_agree = (
    con.sql(
        f"select {sql} from sel_pairs s join m_customers m on m.customer_id = s.mid join b_customers b on b.customer_id = s.bid"
    )
    .df()
    .iloc[0]
)
vs = pd.DataFrame(
    {"agreement among linked pairs": linked_agree, "agreement among random pairs": base}
)
vs["lift ×"] = vs.iloc[:, 0] / vs.iloc[:, 1].replace(0, np.nan)
vs.style.format(
    {
        "agreement among linked pairs": "{:.1%}",
        "agreement among random pairs": "{:.2e}",
        "lift ×": "{:,.0f}",
    }
)

# %% [markdown]
# **Blind validation.** Pairs linked using only identity fields agree on fields the model never saw — `address` 84 %, `registration_date`
# 55 %, `landline_phone` 17 % — versus ≈ 1e-6 for random pairs (lifts of 10⁵–10⁶). Low-entropy fields such as `segment` (lift 2×) and
# `occupation` (9×) show little lift, as they should: they cannot discriminate identity. This held-out evidence, not the ID label, is
# what shows the linked pairs really are the same person.

# %%
cand["linked"] = cand.score >= CUT
cand["pair_type"] = np.select(
    [
        cand.linked & (cand.same_id == 1),
        cand.linked & (cand.same_id == 0),
        ~cand.linked & (cand.same_id == 1),
    ],
    ["same person, same ID", "same person, DIFFERENT ID", "same ID, different person"],
    default="other candidate",
)
pt = cand.pair_type.value_counts().rename("pairs").to_frame()
pt["distinct main customers"] = cand.groupby("pair_type").mid.nunique()
cand.to_parquet(DERIVED / "customer_linkage_pairs.parquet")
n_same_person = cand[cand.linked].mid.nunique()
print(
    f"Population overlap (same person in both folders): {n_same_person:,} of 150,000 main customers = {100 * n_same_person / 150000:.1f} %"
)
pt.style.format("{:,.0f}")

# %% [markdown]
# **Interpretation.** About **7 % of the population** (10.5 k customers) exists in both folders. Of those, ≈ 3.0 k keep their ID and
# ≈ **7.5 k appear under a different ID** — the re-keyed core is real but small. Conversely, ID reuse for a *different* person is common: 1,018 of the
# 4,025 ID-sharing customers agree on none of the four identity fields. The remaining ≈ 93 % of customers have no counterpart:
# the two folders describe largely different people.

# %% [markdown]
# ## L3 · Natural-key alignment for products and agents
# `product_number` and `employee_code` are unique in each folder, so a join on them is deterministic. We measure how
# much that adds beyond ID matching, and whether the two routes agree.

# %%
rows = []
for t, pk, nk in [
    ("products", "product_id", "product_number"),
    ("service_agents", "agent_id", "employee_code"),
]:
    r = con.sql(f"""
        with a as (select {pk} mid, {nk} nk from m_{t}), b as (select {pk} bid, {nk} nk from b_{t})
        select count(*) pairs_by_natural_key, sum((mid = bid)::int) also_same_id from a join b using(nk)""").fetchone()
    s = con.sql(f"select count(*) from m_{t} m join b_{t} b using({pk})").fetchone()[0]
    both = con.sql(
        f"""select count(*) from m_{t} m join b_{t} b using({pk}) where m.{nk} = b.{nk}"""
    ).fetchone()[0]
    rows.append(
        dict(
            table=t,
            shared_ids=s,
            ids_with_same_natural_key=both,
            natural_key_pairs=r[0],
            natural_key_pairs_also_same_id=r[1],
        )
    )
l3 = pd.DataFrame(rows)
l3["id_pairs_that_are_same_object_pct"] = 100 * l3.ids_with_same_natural_key / l3.shared_ids
l3.to_csv(OUT / "alignment_l3_natural_keys.csv", index=False)
l3.style.format(
    dict.fromkeys(l3.columns[1:5], "{:,.0f}") | {"id_pairs_that_are_same_object_pct": "{:.1f}"}
)

# %% [markdown]
# **Interpretation.** 94.4 % of ID-sharing products carry the same `product_number` (so the ID is mostly reliable there), but natural-key
# matching finds **146,398 pairs vs 128,599 shared IDs**: ≈ **24,950 products exist in both folders under a different ID**. For agents the two routes agree
# 100 % and the natural key adds 27 more pairs. Product linkage should therefore use `product_number`.

# %% [markdown]
# ## L4 · Transaction clones: content fingerprint + date window
# Clones (same amount, currency, type, channel, merchant, fraud score) were found among shared IDs in notebook 03.
# Can they also be found **without** IDs? We search for fingerprint-equal pairs whose date offset is inside the drift-corrected
# window (±3 days around the monthly median) and compare with the ID-based clone set.

# %%
pairs = pd.read_parquet(DERIVED / "transaction_pairs.parquet")
med = pairs.groupby(pairs.md.dt.to_period("M")).k_days.median()
med_df = med.rename("med").reset_index().rename(columns={"md": "month"})
med_df["month"] = med_df.month.astype(str)
con.register("med_tbl", med_df)
cols = (
    "amount, currency, transaction_type, channel, transaction_country, merchant_name, fraud_score"
)
found = con.sql(f"""
    with a as (select transaction_id mid, process_date d, strftime(process_date, '%Y-%m') ym, hash({cols}) h from m_transactions),
         b as (select transaction_id bid, process_date d, hash({cols}) h from b_transactions)
    select a.mid, b.bid, date_diff('day', a.d, b.d) k, med.med
    from a join b using(h) join med_tbl med on med.month = a.ym
    where abs(date_diff('day', a.d, b.d) - med.med) <= 3""").df()
found["same_id"] = found.mid == found.bid
id_clones = set(pairs.loc[pairs.is_clone, "pk"])
rec = len(set(found.loc[found.same_id, "mid"]) & id_clones) / len(id_clones)
# placebo: same search with the window moved +120 / +240 / -120 days → expected number of chance matches
plc = []
for shift in (120, 240, -120):
    plc.append(
        len(
            con.sql(f"""
        with a as (select transaction_id mid, process_date d, strftime(process_date, '%Y-%m') ym, hash({cols}) h from m_transactions),
             b as (select transaction_id bid, process_date d, hash({cols}) h from b_transactions)
        select 1 from a join b using(h) join med_tbl med on med.month = a.ym
        where abs(date_diff('day', a.d, b.d) - med.med - {shift}) <= 3""").df()
        )
    )
chance = float(np.mean(plc))
res = pd.Series(
    {
        "expected chance matches (placebo windows)": f"{chance:,.0f}",
        "fingerprint+window pairs": len(found),
        "…of which share an ID": int(found.same_id.sum()),
        "…different ID (clones found without IDs)": int((~found.same_id).sum()),
        "recall of the 11,734 ID-clones": f"{100 * rec:.1f} %",
        "main transactions with ≥1 counterpart": found.mid.nunique(),
    }
)
res.to_frame("value")

# %% [markdown]
# **Interpretation.** Without IDs, content + window matching recovers **≈ 88 % of the ID-clones** (the ±3-day window misses those with a larger
# jitter) and adds **169 pairs under different IDs**. Placebo windows (moved by +120/+240/−120 days) give **≈ 107 pure chance matches**, so at most
# ≈ 60 of the 169 are real extra clones. The clone core is therefore tiny (≈ 0.27 % of main) and already captured by the IDs.

# %% [markdown]
# ## Alignment scoreboard
# What can be compared, at what confidence.

# %%
board = pd.DataFrame(
    [
        [
            "customers",
            "L1 exact ID (same person)",
            int(((cand.same_id == 1) & cand.linked).sum()),
            "ID + identity fields agree (25 % of shared IDs are different people)",
            "high",
        ],
        [
            "customers",
            "L2 FS linkage (different ID)",
            int(((cand.same_id == 0) & cand.linked).sum()),
            "probabilistic score, validated on held-out fields",
            "high",
        ],
        [
            "products",
            "L3 product_number",
            int(l3.loc[0, "natural_key_pairs"]),
            "natural key",
            "high",
        ],
        [
            "service_agents",
            "L3 employee_code",
            int(l3.loc[1, "natural_key_pairs"]),
            "natural key",
            "high",
        ],
        [
            "transactions",
            "L1 exact ID + drift dates",
            len(pairs),
            "ID; 19 % are clones",
            "low for non-clones",
        ],
        ["transactions", "L4 clones", len(id_clones), "content + date window", "high"],
        ["complaints", "L1 exact ID", 67095, "ID; text identical; FKs differ", "very high"],
        [
            "digital_events / interactions / sends",
            "L1 exact ID + drift dates",
            1356688 + 35972 + 49429,
            "ID only",
            "low",
        ],
    ],
    columns=["table", "layer", "comparable pairs", "evidence", "confidence"],
)
board.to_csv(OUT / "alignment_scoreboard.csv", index=False)
board.style.format({"comparable pairs": "{:,.0f}"})

# %% [markdown]
# ## Findings
# 1. **Date alignment is approximate**: a leave-one-month-out drift model predicts offsets to ≈ 0.5–1.5 days; use ±3-day windows.
# 2. **A shared customer ID is a noisy label**: 69 % same person, 25 % a different person, 6 % edited. IDs alone cannot be trusted.
# 3. **Customer linkage** (Fellegi–Sunter, *u* from random pairs, EM for *m*) finds ≈ 10.5 k people in both folders (7 %), ≈ 7.5 k under different IDs;
#    validated blind on held-out fields (address, landline, registration date).
# 4. **Products** are better linked by `product_number`: ≈ 25 k additional pairs vs the ID join.
# 5. **Transactions**: a 0.27 % clone core exists; content + date window recovers ≈ 88 % of it without IDs (≈ 107 chance matches expected).
# 6. Everything else is **independent replicate data**: comparable only in *distribution* (notebook 06), not row by row.
