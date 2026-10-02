# %% [markdown]
# # 07 · Anomaly detection — classical methods
# **CRISP-DM phases 3–5** · rules, robust statistics, time-series methods and robust multivariate distance.
#
# Banking anomaly work has three families of problem, and each needs a different tool:
#
# | family | question | tools in this notebook |
# |---|---|---|
# | **data integrity** | does the record break a business/logical rule? | declarative rule library (SQL) |
# | **point & contextual outliers** | is this value/behaviour unusual *for its context*? | robust z (MAD), Tukey fences, Benford, velocity, impossible travel |
# | **volume / regime anomalies** | is *this day* abnormal? did the level change? | STL residuals, generalized ESD, CUSUM, EWMA, PELT change-points |
# | **entity anomalies** | is *this customer* unusual across many dimensions? | robust Mahalanobis distance (MCD) |
#
# Everything is run on **main** (the authoritative folder) **and** on **backup**, so that notebook 10 can ask whether the same findings appear in both.

# %%
import sys
import warnings

sys.path.insert(0, "../src")
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import ruptures as rpt
from IPython.display import display
from plotly.subplots import make_subplots
from scipy import stats
from sklearn.covariance import MinCovDet
from statsmodels.tsa.seasonal import STL

from latam_eda import theme
from latam_eda.data import ROOT, connect

theme.register()
con = connect()
OUT = ROOT / "reports" / "tables"

# %% [markdown]
# ## 1 · Integrity rule library
# Each rule is a SQL predicate that *should never be true*. We count violations in both folders. `rate_%` is relative to the rows the rule applies to,
# so rates are comparable between folders even though the backup's `transactions` are truncated.
# Severity: **A** breaks accounting/regulatory logic, **B** breaks business plausibility, **C** is a data-quality smell.

# %%
RULES = [
    # id, sev, table, description, base-from, violation predicate  ({p} = m or b)
    (
        "R01",
        "A",
        "transactions",
        "Transaction dated before the product was opened",
        "{p}_transactions t join {p}_products p using(product_id)",
        "cast(t.transaction_date as date) < p.opening_date",
    ),
    (
        "R02",
        "A",
        "products",
        "Product opened before the customer registered",
        "{p}_products p join {p}_customers c using(customer_id)",
        "p.opening_date < cast(c.registration_date as date)",
    ),
    (
        "R03",
        "A",
        "transactions",
        "Approved transaction without a response code",
        "{p}_transactions where transaction_status = 'Approved'",
        "response_code is null",
    ),
    (
        "R04",
        "A",
        "transactions",
        "Transaction currency differs from the product currency",
        "{p}_transactions t join {p}_products p using(product_id)",
        "t.currency <> p.currency",
    ),
    (
        "R05",
        "B",
        "customers",
        "Customer under 18 at registration",
        "{p}_customers",
        "date_diff('year', date_of_birth, cast(registration_date as date)) < 18",
    ),
    (
        "R06",
        "B",
        "customers",
        "`last_updated` later than the end of the data (2026-06-17)",
        "{p}_customers",
        "last_updated > timestamp '2026-06-17 23:59:59'",
    ),
    (
        "R07",
        "B",
        "products",
        "`last_updated` later than the end of the data",
        "{p}_products",
        "last_updated > timestamp '2026-06-17 23:59:59'",
    ),
    (
        "R08",
        "B",
        "products",
        "`credit_limit` present on a non-credit-card product",
        "{p}_products",
        "credit_limit is not null and product_type <> 'Tarjeta Crédito'",
    ),
    (
        "R09",
        "B",
        "products",
        "`days_past_due` present on a product that is not a loan",
        "{p}_products",
        "days_past_due is not null and product_type not like 'Pr%'",
    ),
    (
        "R10",
        "B",
        "transactions",
        "Branch-channel transaction without `branch_id`",
        "{p}_transactions where channel = 'Branch'",
        "branch_id is null",
    ),
    (
        "R11",
        "B",
        "complaints",
        "Resolved/closed case without a resolution date",
        "{p}_complaints where status in ('Resolved','Closed')",
        "resolution_date is null",
    ),
    (
        "R12",
        "B",
        "complaints",
        "Claimed amount without a currency",
        "{p}_complaints where claimed_amount is not null",
        "currency is null",
    ),
    (
        "R13",
        "B",
        "complaints",
        "SLA breached although resolved in ≤ 5 days",
        "{p}_complaints where sla_breached",
        "resolution_days <= 5",
    ),
    (
        "R14",
        "C",
        "transactions",
        "Time stamp − 6 h does not reproduce `process_date` (UTC−6 convention)",
        "{p}_transactions",
        "cast(transaction_date - interval 6 hour as date) <> process_date",
    ),
    (
        "R15",
        "C",
        "call_center_interactions",
        "Time stamp − 6 h does not reproduce `process_date`",
        "{p}_call_center_interactions",
        "cast(interaction_date - interval 6 hour as date) <> process_date",
    ),
    (
        "R16",
        "C",
        "complaints",
        "Time stamp − 6 h does not reproduce `process_date`",
        "{p}_complaints",
        "cast(creation_date - interval 6 hour as date) <> process_date",
    ),
    (
        "R17",
        "C",
        "transactions",
        "Currency label USD on a Mexican-country transaction (no MXN exists)",
        "{p}_transactions where transaction_country in ('México','Mexico')",
        "currency = 'USD'",
    ),
    (
        "R18",
        "C",
        "transactions",
        "`amount_usd` missing although currency is not USD",
        "{p}_transactions where currency <> 'USD'",
        "amount_usd is null",
    ),
    (
        "R19",
        "C",
        "transactions",
        "ATM/POS transaction without coordinates",
        "{p}_transactions where channel in ('ATM','POS')",
        "latitude is null",
    ),
    (
        "R20",
        "C",
        "digital_events",
        "Event without a customer id",
        "{p}_digital_events",
        "customer_id is null",
    ),
]
rows = []
for rid, sev, tab, desc, frm, pred in RULES:
    rec = dict(rule=rid, severity=sev, table=tab, description=desc)
    for p, lab in (("m", "main"), ("b", "backup")):
        base_from = frm.format(p=p)
        n_all, n_bad = con.sql(
            f"select count(*), count(*) filter (where {pred}) from {base_from}"
        ).fetchone()
        rec[f"viol_{lab}"] = n_bad
        rec[f"rate_{lab}_%"] = 100 * n_bad / max(n_all, 1)
    rows.append(rec)
rules = pd.DataFrame(rows)
rules.to_csv(OUT / "integrity_rules.csv", index=False)
rules.style.format(
    {
        "viol_main": "{:,.0f}",
        "viol_backup": "{:,.0f}",
        "rate_main_%": "{:.2f}",
        "rate_backup_%": "{:.2f}",
    }
).background_gradient(subset=["rate_main_%"], cmap="Blues")

# %%
r = rules.sort_values("rate_main_%")
fig = go.Figure()
fig.add_bar(
    y=r.rule + " · " + r.description.str.slice(0, 62),
    x=r["rate_main_%"],
    orientation="h",
    name="main",
    marker_color=theme.MAIN_C,
)
fig.add_bar(
    y=r.rule + " · " + r.description.str.slice(0, 62),
    x=r["rate_backup_%"],
    orientation="h",
    name="backup",
    marker_color=theme.BACKUP_C,
)
fig.update_layout(
    barmode="group",
    height=760,
    margin=dict(l=470),
    bargap=0.3,
    title="Rule violation rate (% of applicable rows)",
    xaxis_title="% of applicable rows",
)
fig.show()

# %% [markdown]
# **Interpretation.** Almost every violation is **structural and has the same rate in both folders** (±0.1 pp) — it comes from the generator, not from the backup path:
# * **R02 / R01 (severity A):** 50 % of products are opened *before* their owner registered and 18.7 % of transactions pre-date the product they use — customer, product and transaction timelines
#   are not causally consistent, so "tenure" or "time since opening" features are unreliable. (R01 reads 29 % in the backup only because its transactions are truncated to the *earlier* 2023–24 window,
#   where more activity precedes product opening — a denominator effect, not a new defect.)
# * **R03:** 5 % of approved transactions have **no response code** and **R18:** 5 % of non-USD transactions lack `amount_usd` — the ~5 % null injection the documentation announces, landing on fields that
#   should be mandatory. **R10:** 5 % of branch transactions lack `branch_id`; **R11/R12:** 4.8 % of resolved cases lack a date and of claims a currency.
# * **R17:** 99 % of Mexican transactions are labelled **USD** and no MXN exists (55 % of all transactions are `USD`): a mislabelled currency that also explains why `amount_usd` is null for USD rows.
# * **R05–R09:** 2 % of customers are minors at registration; 6 % of customers and products carry a `last_updated` **after the end of the data** (future-dated audit stamp); `credit_limit` sits on 7.6 % of non-card products and
#   `days_past_due` on 24 % of non-loans.
# * **R14–R16:** the UTC−6 timestamp convention holds for all but 51 of 4.4 M transactions but fails for ≈ 8.3 % of interactions and complaints (they need a larger offset).
# * **R04 = 0:** transaction currency always equals the product currency — one *good* control.
# The backup adds **no new violation** beyond the denominator effect above; its defects are the null/vocabulary changes found in notebook 06.

# %% [markdown]
# ## 2 · Point & contextual outliers in transactions
# **2a. Robust z-score (MAD) within context.** A $5,000 payment is normal for a `Transfer` and extreme for a `Purchase`. We therefore compute the modified z-score
# `0.6745 (x − median)/MAD` on `log(amount_usd)` **inside each (type, channel) group**. The classic 3.5 rule flags `|z| > 3.5`.

# %%
tx = con.sql("""
    select transaction_id, customer_id, transaction_type, channel, currency, transaction_country, process_date,
           transaction_date, is_fraud, fraud_score, transaction_status,
           case when currency = 'USD' then amount else amount_usd end as usd
    from m_transactions using sample 800000 rows""").df()
tx = tx[tx.usd > 0].copy()
tx["lu"] = np.log(tx.usd)
g = tx.groupby(["transaction_type", "channel"]).lu
med, mad = g.transform("median"), g.transform(lambda s: np.median(np.abs(s - np.median(s))))
tx["robust_z"] = 0.6745 * (tx.lu - med) / mad.replace(0, np.nan)
q1, q3 = g.transform(lambda s: s.quantile(0.25)), g.transform(lambda s: s.quantile(0.75))
tx["tukey"] = (tx.lu < q1 - 1.5 * (q3 - q1)) | (tx.lu > q3 + 1.5 * (q3 - q1))
tx["mad_flag"] = tx.robust_z.abs() > 3.5
print(
    f"{len(tx):,} transactions • MAD flags {tx.mad_flag.mean():.2%} • Tukey flags {tx.tukey.mean():.2%}"
)
summ = tx.groupby(["transaction_type"]).agg(
    rows=("lu", "size"),
    median_usd=("usd", "median"),
    p99_usd=("usd", lambda s: s.quantile(0.99)),
    mad_flag_pct=("mad_flag", lambda s: 100 * s.mean()),
    tukey_flag_pct=("tukey", lambda s: 100 * s.mean()),
)
summ.style.format(
    {
        "rows": "{:,.0f}",
        "median_usd": "{:,.0f}",
        "p99_usd": "{:,.0f}",
        "mad_flag_pct": "{:.2f}",
        "tukey_flag_pct": "{:.2f}",
    }
)

# %%
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=["Distribution of transaction USD value (log x)", "Share by 1,000-USD band"],
)
cnt, edg = np.histogram(np.log10(tx.usd), bins=140)
fig.add_bar(
    x=(edg[:-1] + edg[1:]) / 2, y=cnt, marker_color=theme.BLUE, showlegend=False, row=1, col=1
)
band = (tx.usd // 1000 * 1000).clip(upper=9000).value_counts(normalize=True).sort_index()
fig.add_bar(
    x=band.index.astype(int).astype(str),
    y=band.values,
    marker_color=theme.BLUE,
    showlegend=False,
    row=1,
    col=2,
)
fig.update_xaxes(title_text="log10(USD)", row=1, col=1)
fig.update_xaxes(title_text="USD band", row=1, col=2)
fig.update_layout(height=360, title="The amount distribution is a bounded mixture — no heavy tail")
fig.show()
print("max usd:", tx.usd.max())

# %% [markdown]
# **Interpretation.** Amounts are a **bounded mixture** (5 → 9,999.85 USD) with flat plateaus per 1,000-USD band, not a heavy-tailed distribution. MAD flags 2.8 % and Tukey 3.7 % of transactions,
# but those flags mark the **edges of the mixture bands** within each (type, channel) group, not risk: a real bank's amounts would have a Pareto tail far above any plateau.
# The hard cap just under 10,000 USD is itself suspicious (a **reporting-threshold ceiling**): nothing reaches the 10,000-USD AML reporting level, so threshold-*structuring* analysis has no signal here —
# a limitation we respect when interpreting later models.

# %% [markdown]
# **2b. Benford's law.** Fabricated figures often break the first-digit law. Compared across the native-currency amount and per currency.


# %%
def first_digit(s):
    s = s[s > 0]
    return (
        (s / 10 ** np.floor(np.log10(s)))
        .astype(int)
        .value_counts(normalize=True)
        .reindex(range(1, 10), fill_value=0)
    )


nat = con.sql(
    "select currency, amount from m_transactions where amount > 0 using sample 600000 rows"
).df()
benf = pd.Series({d: np.log10(1 + 1 / d) for d in range(1, 10)})
rows = []
fig = go.Figure(go.Bar(x=benf.index, y=benf.values, marker_color="#e6e5e1", name="Benford"))
cols = {"USD": theme.BLUE, "COP": theme.ORANGE, "ARS": theme.AQUA}
for cur, d in nat.groupby("currency"):
    fd = first_digit(d.amount)
    mad_b = (fd - benf).abs().mean()
    chi = stats.chisquare(fd * len(d), benf * len(d))[0]
    rows.append(
        dict(
            currency=cur,
            n=len(d),
            MAD=mad_b,
            chi2=chi,
            conformity="close (<0.006)"
            if mad_b < 0.006
            else "acceptable (<0.012)"
            if mad_b < 0.012
            else "marginal (<0.015)"
            if mad_b < 0.015
            else "NON-conforming",
        )
    )
    fig.add_scatter(
        x=fd.index, y=fd.values, mode="lines+markers", name=cur, line=dict(color=cols[cur], width=2)
    )
fig.update_layout(
    height=340,
    title="First-digit distribution of native-currency amounts vs Benford",
    xaxis_title="leading digit",
    yaxis_title="share",
)
fig.show()
pd.DataFrame(rows).style.format({"n": "{:,.0f}", "MAD": "{:.4f}", "chi2": "{:,.0f}"})

# %% [markdown]
# **Interpretation.** Amounts do **not** follow Benford's law: per-currency MAD is 0.024 (ARS), 0.026 (USD) and 0.029 (COP), all "non-conforming" on Nigrini's scale (> 0.015). For genuine bank data that would be a
# red flag, but here the explanation is the **bounded, uniformly-banded** generation of amounts, not manipulation. The test is kept as a *forensic baseline* and gives the same answer in the backup (notebook 06).

# %% [markdown]
# **2c. Velocity and impossible travel.** Two behavioural rules that are standard in card fraud engines:
# *velocity* — ≥ 5 transactions by one customer within 1 hour; *impossible travel* — consecutive transactions in **different countries** less than 2 hours apart.

# %%
beh = con.sql("""
    with t as (
      select customer_id, transaction_date ts, transaction_country ctry, amount_usd, currency, amount,
             lag(transaction_date) over w prev_ts, lag(transaction_country) over w prev_ctry
      from m_transactions window w as (partition by customer_id order by transaction_date))
    select count(*) n,
           count(*) filter (where date_diff('minute', prev_ts, ts) between 0 and 120 and ctry <> prev_ctry
                              and not (ctry in ('México','Mexico') and prev_ctry in ('México','Mexico'))) impossible_travel,
           count(*) filter (where date_diff('minute', prev_ts, ts) between 0 and 5) rapid_repeat_5min,
           count(*) filter (where prev_ts is null) first_txn
    from t""").df()
beh

# %% [markdown]
# **Interpretation.** Impossible-travel events (different country within 2 h) number 1,351 (0.03 % of transactions) and 5-minute repeats 697 (0.016 %). With ≈ 30 transactions per customer over three years,
# chance alone produces a few of each; we keep them as a **behavioural baseline** and reuse the same quantities as features in notebook 08.

# %% [markdown]
# ## 3 · Volume and regime anomalies in daily series
# For each fact table we model the daily row count with **STL** (weekly seasonality, robust), then flag days with
# **(i)** MAD-z > 3.5 on the residual, **(ii)** the **generalized ESD** test (Rosner, α = 0.05; ≤ 5 % outliers), and watch for **level shifts** with **CUSUM**, **EWMA** and **PELT** change-points.
# We run it on main and backup and compare the flagged dates.


# %%
def gesd(x, max_out, alpha=0.05):
    x = np.asarray(x, float).copy()
    idx = np.arange(len(x))
    n = len(x)
    R, lam, order = [], [], []
    xi = x.copy()
    ii = idx.copy()
    for i in range(1, max_out + 1):
        mu, sd = xi.mean(), xi.std(ddof=1)
        if sd == 0:
            break
        dev = np.abs(xi - mu) / sd
        j = dev.argmax()
        R.append(dev[j])
        order.append(ii[j])
        p = 1 - alpha / (2 * (n - i + 1))
        t = stats.t.ppf(p, n - i - 1)
        lam.append((n - i) * t / np.sqrt((n - i - 1 + t**2) * (n - i + 1)))
        xi = np.delete(xi, j)
        ii = np.delete(ii, j)
    k = max([i for i in range(len(R)) if R[i] > lam[i]], default=-1) + 1
    return set(order[:k])


series = {}
for t in [
    "transactions",
    "digital_events",
    "call_center_interactions",
    "campaign_sends",
    "complaints",
    "call_transcripts",
    "satisfaction_surveys",
]:
    for p, lab in (("m", "main"), ("b", "backup")):
        try:
            s = (
                con.sql(f"select process_date d, count(*) n from {p}_{t} group by 1 order by 1")
                .df()
                .set_index("d")
                .n
            )
        except Exception:
            continue
        s.index = pd.DatetimeIndex(s.index)
        s = s.asfreq("D").fillna(0)
        series[(t, lab)] = s

res, flagged = [], {}
for (t, lab), s in series.items():
    if len(s) < 60:
        continue
    stl = STL(np.log1p(s.values), period=7, robust=True).fit()
    resid = stl.resid
    mad = np.median(np.abs(resid - np.median(resid))) or 1e-9
    z = 0.6745 * (resid - np.median(resid)) / mad
    f_mad = set(np.where(np.abs(z) > 3.5)[0])
    f_esd = gesd(resid, max_out=max(5, int(0.05 * len(s))))
    cus = np.cumsum(resid - resid.mean()) / resid.std()
    ewma = pd.Series(resid).ewm(alpha=0.2).mean()
    ew_sd = resid.std() * np.sqrt(0.2 / 1.8)
    f_ew = set(np.where(np.abs(ewma - resid.mean()) > 3 * ew_sd)[0])
    bkps = (
        rpt.Pelt(model="rbf", min_size=14, jump=3)
        .fit(np.log1p(s.values).reshape(-1, 1))
        .predict(pen=8)[:-1]
    )
    flagged[(t, lab)] = dict(dates=s.index, mad=f_mad, esd=f_esd, z=z, stl=stl, bkps=bkps)
    res.append(
        dict(
            table=t,
            folder=lab,
            days=len(s),
            mad_days=len(f_mad),
            esd_days=len(f_esd),
            ewma_days=len(f_ew),
            both_mad_esd=len(f_mad & f_esd),
            pelt_changepoints=len(bkps),
            max_abs_cusum=float(np.abs(cus).max()),
            seasonal_strength=max(0, 1 - np.var(resid) / np.var(resid + stl.seasonal)),
        )
    )
ts_summary = pd.DataFrame(res)
ts_summary.to_csv(OUT / "daily_series_anomalies.csv", index=False)
ts_summary.style.format({"max_abs_cusum": "{:.1f}", "seasonal_strength": "{:.2f}"})

# %% [markdown]
# **Reading the table.** `seasonal_strength` (Hyndman: 1 − Var(R)/Var(R+S)) shows how much of each series is weekly pattern; `mad_days`/`esd_days` are days with an
# unusual residual; `pelt_changepoints` counts level shifts; `max_abs_cusum` is the largest standardised cumulative drift.

# %%
SEL = {
    "transactions": "transactions",
    "digital_events": "digital_events",
    "interactions": "call_center_interactions",
    "sends": "campaign_sends",
}
fig = make_subplots(
    rows=len(SEL),
    cols=1,
    shared_xaxes=False,
    vertical_spacing=0.06,
    subplot_titles=[f"{k}: STL residual z-score (MAD)" for k in SEL],
)
for i, (lab, t) in enumerate(SEL.items(), 1):
    for folder, col in (("main", theme.MAIN_C), ("backup", theme.BACKUP_C)):
        d = flagged.get((t, folder))
        if d is None:
            continue
        fig.add_scatter(
            x=d["dates"],
            y=d["z"],
            mode="lines",
            line=dict(color=col, width=1),
            name=folder,
            showlegend=(i == 1),
            row=i,
            col=1,
            hovertemplate="%{x|%Y-%m-%d}<br>z=%{y:.1f}<extra>" + folder + "</extra>",
        )
    fig.add_hline(y=3.5, line_dash="dot", line_color="#8a8984", row=i, col=1)
    fig.add_hline(y=-3.5, line_dash="dot", line_color="#8a8984", row=i, col=1)
fig.update_layout(
    height=170 * len(SEL) + 100, title="Daily-volume residuals: main vs backup (dotted = ±3.5)"
)
fig.show()

# %% [markdown]
# **Interpretation.** Daily volumes are *stationary around a strong weekly pattern* (seasonal strength 0.87–0.92 for transactions, interactions, sends, complaints, transcripts, surveys). The robust-z rule flags 5–48 days per
# series (0.5–4 %), but the stricter **generalized ESD** test confirms only **1–4 days per table**, and **PELT finds no level shift in any series** — there is no regime change in the volume. **`digital_events` is different**:
# its weekly pattern is weak (seasonal strength 0.39–0.46) and it is much noisier, producing days at 3–4× or ¼ of the typical level. Crucially, the flagged dates are **different in main and backup** (next cell): the spikes are random
# draws, not events that occurred on a particular calendar day.

# %%
rows = []
for (t, lab), d in flagged.items():
    if lab != "main" or (t, "backup") not in flagged:
        continue
    a = {d["dates"][i] for i in d["mad"] | d["esd"]}
    b_ = flagged[(t, "backup")]
    bb = {b_["dates"][i] for i in b_["mad"] | b_["esd"]}
    u = a | bb
    rows.append(
        dict(
            table=t,
            flagged_main=len(a),
            flagged_backup=len(bb),
            both=len(a & bb),
            jaccard=len(a & bb) / len(u) if u else np.nan,
        )
    )
pd.DataFrame(rows).style.format({"jaccard": "{:.2f}"})

# %% [markdown]
# A **Jaccard of ≈ 0** (transactions 0, events 0, sends 0, interactions 0.02) confirms that anomalous *days* do not replicate across folders — the daily volume noise is independent per run, consistent with notebook 06. **Complaints give
# Jaccard = 1.0**, the positive control: their series are identical, so the method reproduces itself when it should.

# %% [markdown]
# ## 4 · Entity anomalies: robust Mahalanobis distance over customer features
# Build one feature vector per customer from every table, fit a **Minimum Covariance Determinant** estimate (breakdown point 25 %), and score each customer by the squared robust Mahalanobis distance.
# Under multivariate normality that distance is χ²(p), so the 0.1 % tail is the natural cutoff — in practice far more customers exceed it, because the features are heavy-tailed counts.

# %%
cust = con.sql("""
    with trx as (select customer_id, count(*) n_trx, avg(ln(case when currency='USD' then amount else amount_usd end)) mean_log_amt,
                        avg((transaction_status='Declined')::int) declined_rate, avg((channel in ('Web','App'))::int) digital_share
                 from m_transactions where coalesce(amount_usd, amount) > 0 group by 1),
         ev as (select customer_id, count(*) n_events from m_digital_events where customer_id is not null group by 1),
         it as (select customer_id, count(*) n_calls, avg(sentiment_score) mean_sentiment from m_call_center_interactions group by 1),
         cp as (select customer_id, count(*) n_complaints from m_complaints group by 1),
         pr as (select customer_id, count(*) n_products from m_products group by 1)
    select c.customer_id, c.segment, c.country, c.credit_score, ln(c.estimated_monthly_income) log_income,
           date_diff('year', c.date_of_birth, date '2026-06-17') age,
           coalesce(n_trx,0) n_trx, mean_log_amt, coalesce(declined_rate,0) declined_rate, coalesce(digital_share,0) digital_share,
           coalesce(n_events,0) n_events, coalesce(n_calls,0) n_calls, mean_sentiment, coalesce(n_complaints,0) n_complaints, coalesce(n_products,0) n_products
    from m_customers c left join trx using(customer_id) left join ev using(customer_id) left join it using(customer_id)
         left join cp using(customer_id) left join pr using(customer_id)""").df()
feat = [
    "credit_score",
    "log_income",
    "age",
    "n_trx",
    "mean_log_amt",
    "declined_rate",
    "digital_share",
    "n_events",
    "n_calls",
    "mean_sentiment",
    "n_complaints",
    "n_products",
]
X = cust[feat].copy()
X["n_trx"], X["n_events"], X["n_calls"] = (
    np.log1p(X.n_trx),
    np.log1p(X.n_events),
    np.log1p(X.n_calls),
)
X = X.fillna(X.median())
Xs = (X - X.median()) / (X.quantile(0.75) - X.quantile(0.25)).replace(0, 1)
sub = Xs.sample(60000, random_state=0)
mcd = MinCovDet(support_fraction=0.75, random_state=0).fit(sub)
cust["maha2"] = mcd.mahalanobis(Xs)
cut = stats.chi2.ppf(0.999, len(feat))
cust["maha_flag"] = cust.maha2 > cut
print(
    f"customers: {len(cust):,} • flagged at χ²(0.999, df={len(feat)}) = {cut:.1f}: {cust.maha_flag.sum():,} ({cust.maha_flag.mean():.2%})"
)

# %%
top = cust.sort_values("maha2", ascending=False).head(12)
contrib = ((Xs.loc[top.index] - mcd.location_) ** 2 / np.diag(mcd.covariance_)).apply(
    lambda r: r.idxmax(), axis=1
)
tab = top[
    ["customer_id", "segment", "country", "maha2", "n_trx", "n_events", "credit_score", "age"]
].assign(driver=contrib)
display(tab.style.format({"maha2": "{:,.0f}", "n_trx": "{:,.0f}", "n_events": "{:,.0f}"}))
cnt, edg = np.histogram(np.log10(cust.maha2.clip(lower=0.1)), bins=100)
fig = go.Figure(go.Bar(x=(edg[:-1] + edg[1:]) / 2, y=cnt, marker_color=theme.BLUE))
fig.add_vline(x=np.log10(cut), line_dash="dash", line_color=theme.RED, annotation_text="χ² 99.9 %")
fig.update_layout(
    height=340, title="Robust Mahalanobis distance² of customers (log10)", xaxis_title="log10 d²"
)
fig.show()

# %% [markdown]
# **Interpretation.** At the χ² 99.9 % cutoff **12.3 % of customers (18,459)** are flagged instead of the nominal 0.1 %: the multivariate-normal assumption fails for count-type features (transactions, events), which is the
# classical weakness of Mahalanobis scoring. The ranking is still informative — the top entities are overwhelmingly customers with **zero transactions but dozens of digital events** (driver `n_trx`) or extreme decline rates —
# and gives a classical baseline for the distribution-free detectors in notebook 08.

# %% [markdown]
# ## Interactive explorer — flagged days
# A plain Plotly dropdown (works in the exported HTML too, no kernel needed): choose the table; markers show days beyond ±3.5 robust z.

# %%
fig = go.Figure()
tabs = list(SEL.items())
for k, (lab, t) in enumerate(tabs):
    for folder, col in (("main", theme.MAIN_C), ("backup", theme.BACKUP_C)):
        d = flagged.get((t, folder))
        if d is None:
            continue
        z = pd.Series(d["z"], index=d["dates"])
        hit = z[z.abs() > 3.5]
        fig.add_scatter(
            x=z.index,
            y=z.values,
            mode="lines",
            line=dict(color=col, width=1),
            name=f"{folder}",
            visible=(k == 0),
            legendgroup=folder,
        )
        fig.add_scatter(
            x=hit.index,
            y=hit.values,
            mode="markers",
            marker=dict(color=col, size=8, line=dict(color="white", width=1)),
            name=f"{folder} flagged ({len(hit)})",
            visible=(k == 0),
            legendgroup=folder,
        )
per = 4  # traces per table (2 folders x line+markers)
buttons = [
    dict(
        label=lab,
        method="update",
        args=[
            {"visible": [(i // per) == k for i in range(per * len(tabs))]},
            {"title": f"{lab}: STL residual z (flags beyond ±3.5)"},
        ],
    )
    for k, (lab, _) in enumerate(tabs)
]
fig.add_hline(y=3.5, line_dash="dot", line_color="#8a8984")
fig.add_hline(y=-3.5, line_dash="dot", line_color="#8a8984")
fig.update_layout(
    height=420,
    title=f"{tabs[0][0]}: STL residual z (flags beyond ±3.5)",
    yaxis_title="robust z",
    updatemenus=[dict(buttons=buttons, direction="down", x=0.0, y=1.18, xanchor="left")],
)
fig.show()

# %% [markdown]
# ## Findings
# 1. **Integrity (rules):** 20 rules; the large violations are *structural and identical in both folders* — temporal inconsistency between customers, products and transactions
#    (R02 50 %, R01 19 %), currency mislabelling of 99 % of Mexican transactions (R17), and the ~5 % null injection on mandatory fields (R03, R18, R10–R12); 6 % of audit stamps are future-dated.
# 2. **Point outliers:** amounts are a bounded mixture capped under 10,000 USD; MAD/Tukey/Benford carry little risk information here.
# 3. **Volume:** weekly pattern dominates; no level shifts; `digital_events` volume is erratic and flagged days **do not replicate** between folders (Jaccard ≈ 0; complaints = 1.0 as control).
# 4. **Entities:** robust Mahalanobis over-flags (12 % at the nominal 0.1 % cutoff) because features are heavy-tailed; it ranks customers by multivariate unusualness and is the classical baseline for notebook 08.
