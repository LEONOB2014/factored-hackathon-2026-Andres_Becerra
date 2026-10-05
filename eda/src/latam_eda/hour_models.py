"""The candidate models of the hour-grain star (granularity series III), trained whatever the signal.

Each scenario trains its models out of time against a transparent benchmark and returns readiness rows
(`granularity.readiness_row`): green, amber or red with a root cause and what the data would need to turn it green.
The same functions serve the notebooks (one scenario each), the scorecard (notebook 08) and the re-run command
`scripts/readiness_check.py`, so a new source is judged exactly like this one.

Every function takes a `granularity.Star` over a scratch lakehouse whose hour star is built
(`open_star(pl, [SQL_DIR_TIME, SQL_DIR_HOUR])`), and is deterministic (fixed seeds, hash-based samples, sorted rows).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import mean_absolute_error, roc_auc_score

from latam_eda import granularity as g

if TYPE_CHECKING:
    from latam_eda.granularity import Star

B = 200  # bootstrap resamples per gate
SEED = 2026

# what each red model would need, by scenario and model (the data-collection audit reads these)
REQUIREMENTS = {
    ("02 customer", "dormancy from the time-of-day profile"): (
        "customer activity with a real daily rhythm (true local timestamps, declared clock); a profile only predicts "
        "when customers have habits"
    ),
    ("02 customer", "daypart of the next transaction"): (
        "per-customer time-of-day habits (true local timestamps; card, app and branch events for the same customer)"
    ),
    ("03 market and channel", "hourly volume per market × channel"): (
        "an intraday arrival profile (real timestamps in local time); at least 26 weeks of hourly history per series"
    ),
    ("04 branch", "teller transaction outside opening hours"): (
        "teller sessions tied to the branch schedule (opening days and hours per branch, holiday closures) and a "
        "teller or terminal identifier per transaction"
    ),
    ("04 branch", "branch-hour ATM cash"): (
        "ATM-level cash events (terminal id, dispense, replenishment) with an intraday withdrawal profile"
    ),
    ("05 agent and queue", "handle time per agent-hour"): (
        "workforce data: rostered shifts per agent and day, login/logout and state logs (available, on break, in "
        "call), so occupancy and adherence can be measured"
    ),
    ("05 agent and queue", "hourly contact arrivals per queue"): (
        "an intraday contact profile (real timestamps); queue and abandonment events from the telephony system"
    ),
    ("06 case clock", "time to first response"): (
        "case work queues and assignment rules, agent capacity per hour, and the regulatory deadline per case type "
        "and country"
    ),
    ("06 case clock", "SLA breach at creation"): (
        "an SLA flag consistent with the measured clock (deadline per case type and country, business-hours "
        "calendar), and the case's linked contact (origin_interaction_id)"
    ),
    ("07 session and send", "session purchase from the event sequence"): (
        "real clickstream order (events in the order the customer produced them, page and product per event) and "
        "funnel step identifiers"
    ),
    ("07 session and send", "open within 24 h by send hour"): (
        "opens with a real delay distribution (tracked opens for every channel, device and local time of the open) "
        "and randomised send times to learn the effect of the hour"
    ),
}


# who owns each requirement and the test that proves it on a new feed (the audit of the data collection process)
AUDIT = {
    ("02 customer", "dormancy from the time-of-day profile"): (
        "data platform (source contract)",
        "clock scan per process: hour × weekday χ²/dof ≈ 1 at the declared offset; a daily rhythm (hour-of-day Cohen's w "
        "> 0.1)",
    ),
    ("02 customer", "daypart of the next transaction"): (
        "data platform (source contract)",
        "share of customers rejecting uniform hours at 1 % well above 1 % (per-customer χ²)",
    ),
    ("03 market and channel", "hourly volume per market × channel"): (
        "channel owners (cards, ATM, digital)",
        "uniform-hours test per channel with Cohen's w > 0.1; 26 weeks of dense hourly history",
    ),
    ("04 branch", "teller transaction outside opening hours"): (
        "branch network operations",
        "teller transactions outside the declared schedule below 0.5 %; schedule seed with opening days and holiday "
        "closures per branch",
    ),
    ("04 branch", "branch-hour ATM cash"): (
        "cash logistics",
        "terminal-level dispense events reconcile to the ledger; intraday dispense profile with Cohen's w > 0.1",
    ),
    ("05 agent and queue", "handle time per agent-hour"): (
        "workforce management (contact centre)",
        "rostered shift per agent and day; ≥ 95 % of contacts inside the agent's rostered hours; agent state logs",
    ),
    ("05 agent and queue", "hourly contact arrivals per queue"): (
        "contact-centre telephony",
        "queue events (offered, answered, abandoned) per interval reconcile to interactions; intraday profile w > 0.1",
    ),
    ("06 case clock", "time to first response"): (
        "complaints management and compliance",
        "case assignment events and queue capacity per hour; deadline seed per case type and country",
    ),
    ("06 case clock", "SLA breach at creation"): (
        "complaints management and compliance",
        "SLA flag agrees with the regulatory business-day clock (Cohen's κ > 0.9); origin_interaction_id populated",
    ),
    ("07 session and send", "session purchase from the event sequence"): (
        "digital analytics",
        "event order test: transitions between event types depart from independence (Cramér's V > 0.1)",
    ),
    ("07 session and send", "open within 24 h by send hour"): (
        "marketing technology",
        "send-to-open delay departs from uniform over 7 days (KS); a randomised send-time experiment per campaign",
    ),
}


def _sample(df: pd.DataFrame, key: str, share: float) -> pd.DataFrame:
    """A deterministic hash sample of rows (the same rows on every run)."""
    h = pd.util.hash_pandas_object(df[key], index=False).to_numpy() % 10_000
    return df[h < share * 10_000]


def _row(
    scenario,
    model,
    metric,
    value,
    bench_name,
    bench_value,
    delta,
    boot,
    material,
    cause,
    n_train,
    n_test,
):
    gate = g.readiness_verdict(boot, delta, material, cause)
    req = REQUIREMENTS[(scenario, model)]
    row = g.readiness_row(
        scenario, model, metric, value, bench_name, bench_value, gate, req, n_train, n_test
    )
    row["n_test_needed"] = (
        int(np.ceil(n_test * (gate["mde"] / material) ** 2)) if gate["mde"] > material else n_test
    )
    return row


def _auc_gate(scenario, model, y_tr_n, y, p_model, p_bench, bench_name, material, cause):
    delta, boot = g.paired_boot(roc_auc_score, y, p_model, p_bench, B=B, seed=SEED)
    auc_m, auc_b = roc_auc_score(y, p_model), roc_auc_score(y, p_bench)
    return _row(
        scenario,
        model,
        "AUC",
        auc_m,
        bench_name,
        auc_b,
        delta,
        boot,
        material,
        cause,
        y_tr_n,
        len(y),
    )


# ------------------------------------------------------------------------------------------------ 02 the customer
def customer(star: Star) -> tuple[list[dict], dict]:
    """Dormancy in the next 90 days from the time-of-day profile, and the daypart of the next transaction."""
    tx = star.q("""select customer_id, transaction_ts_utc - interval 6 hour as ts from {int_transactions_enriched}
                   order by customer_id, ts""")
    end = tx.ts.max()
    rows, detail = [], {}

    def features(cut):
        past = tx[(tx.ts <= cut) & (tx.ts > cut - pd.Timedelta(days=180))]
        f = past.groupby("customer_id").agg(n_180=("ts", "size"), last=("ts", "max"))
        f["hours_since_last"] = (cut - f["last"]).dt.total_seconds() / 3600
        dp = pd.crosstab(past.customer_id, g.daypart(past.ts.dt.hour.to_numpy()), normalize="index")
        dp = dp.reindex(columns=list(g.DAYPARTS), fill_value=0).add_prefix("share_")
        hh = pd.crosstab(past.customer_id, past.ts.dt.hour, normalize="index")
        ent = -(hh * np.log(hh.where(hh > 0, 1))).sum(axis=1).rename("hour_entropy")
        f = f.join(dp).join(ent).drop(columns="last")
        fut = tx[(tx.ts > cut) & (tx.ts <= cut + pd.Timedelta(days=90))].customer_id.unique()
        f["dormant"] = (~f.index.isin(fut)).astype(int)
        return f.sort_index()

    tr, te = features(end - pd.Timedelta(days=270)), features(end - pd.Timedelta(days=90))
    cols = ["n_180", "hours_since_last", *[f"share_{d}" for d in g.DAYPARTS], "hour_entropy"]
    m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=SEED).fit(
        tr[cols], tr.dormant
    )
    b = LogisticRegression().fit(np.log1p(tr[["n_180"]]), tr.dormant)
    p_m, p_b = m.predict_proba(te[cols])[:, 1], b.predict_proba(np.log1p(te[["n_180"]]))[:, 1]
    rows.append(
        _auc_gate(
            "02 customer",
            "dormancy from the time-of-day profile",
            len(tr),
            te.dormant.to_numpy(),
            p_m,
            p_b,
            "six-month count (logistic)",
            0.02,
            "generator independence",
        )
    )
    detail["dormancy_base_rate"] = float(te.dormant.mean())

    # the daypart of each customer's next transaction: the customer's own past shares against the bank's shares
    cut = end - pd.Timedelta(days=90)
    past, fut = tx[tx.ts <= cut], tx[tx.ts > cut]
    shares = pd.crosstab(past.customer_id, g.daypart(past.ts.dt.hour.to_numpy())).reindex(
        columns=list(g.DAYPARTS), fill_value=0
    )
    first = fut.groupby("customer_id").ts.min()
    y = pd.Series(g.daypart(first.dt.hour.to_numpy()), index=first.index)
    common = shares.index.intersection(y.index)
    k = shares.loc[common]
    glob = shares.sum() / shares.to_numpy().sum()
    # the customer's own profile shrunk towards the bank's shares (a prior worth 20 transactions)
    p_cust = ((k + 20 * glob) / (k.sum(axis=1).to_numpy()[:, None] + 20)).to_numpy()
    p_glob = np.tile(glob.to_numpy(), (len(common), 1))
    yi = pd.Categorical(y.loc[common], categories=list(g.DAYPARTS)).codes

    rr = np.arange(len(yi))
    l_c = -np.log(np.clip(p_cust[rr, yi], 1e-12, 1))  # per-customer log loss of the own profile
    l_g = -np.log(np.clip(p_glob[rr, yi], 1e-12, 1))
    gain = l_g - l_c  # nats per customer saved by the profile (higher is better)
    rng = np.random.default_rng(SEED)
    boot = np.array([gain[rng.integers(0, len(gain), len(gain))].mean() for _ in range(B)])
    rows.append(
        _row(
            "02 customer",
            "daypart of the next transaction",
            "log loss",
            l_c.mean(),
            "bank-wide daypart shares",
            l_g.mean(),
            gain.mean(),
            boot,
            0.005,
            "generator independence",
            len(past),
            len(yi),
        )
    )
    return rows, detail


# ------------------------------------------------------------------------------------------------ 03 market × channel
def _weekly_scale(y: np.ndarray) -> float:
    """MASE scale of an hourly series: the mean absolute change from the same hour one week earlier (in sample)."""
    return float(np.mean(np.abs(y[168:] - y[:-168]))) or 1.0


def _hourly_forecast(y: pd.Series, how: pd.Series, dayid: pd.Series, test_hours: int, scale: float):
    """Day/24 (last week's same delivery day spread flat), Poisson GLM on hour-of-week, and boosting with weekly lags.

    The series is dense and hourly, so 168 rows back is the same hour of the same weekday last week.
    """
    n = len(y)
    te = np.arange(n - test_hours, n)
    tr = np.arange(max(0, n - test_hours - 26 * 168), n - test_hours)
    day = y.groupby(dayid.to_numpy()).transform("sum").to_numpy()
    flat = np.r_[np.full(168, np.nan), day[:-168]] / 24
    # the same information as the hourly models except the hour: each weekday's mean day over the training window,
    # spread flat (it isolates what an intraday profile adds)
    wd = how.to_numpy() // 24
    first = np.r_[True, dayid.to_numpy()[1:] != dayid.to_numpy()[:-1]]
    trd = np.zeros(n, bool)
    trd[tr] = True
    per_wd = pd.Series(day[first & trd]).groupby(wd[first & trd]).mean()
    wd_flat = pd.Series(wd).map(per_wd).to_numpy() / 24
    X = pd.get_dummies(how.astype("category")).to_numpy(dtype=float)
    glm = PoissonRegressor(alpha=1e-4, max_iter=500).fit(X[tr], y.to_numpy()[tr])
    lag = pd.DataFrame(
        {"how": how.to_numpy(), "l168": y.shift(168).to_numpy(), "l336": y.shift(336).to_numpy()}
    )
    gb = HistGradientBoostingRegressor(loss="poisson", max_iter=200, random_state=SEED).fit(
        lag.iloc[tr].fillna(0), y.to_numpy()[tr]
    )
    return {
        "y": y.to_numpy()[te],
        "day/24": flat[te],
        "weekday mean / 24": wd_flat[te],
        "Poisson GLM hour-of-week": glm.predict(X[te]),
        "boosting with weekly lags": gb.predict(lag.iloc[te].fillna(0)),
        "scale": scale,
    }


def _forecast_gate(scenario, model, frames, material, cause, n_train):
    """Pooled scaled absolute error of the best hourly model against the weekday mean spread flat (the same level
    information without an hourly profile), bootstrapped over test days."""
    best_name, best = None, None
    for name in ["Poisson GLM hour-of-week", "boosting with weekly lags"]:
        e = np.concatenate([np.abs(f["y"] - f[name]) / f["scale"] for f in frames])
        if best is None or e.mean() < best.mean():
            best_name, best = name, e
    e0 = np.concatenate([np.abs(f["y"] - f["weekday mean / 24"]) / f["scale"] for f in frames])
    ok = ~np.isnan(e0) & ~np.isnan(best)
    e0, best = e0[ok], best[ok]
    day = np.arange(len(e0)) // 24
    rng = np.random.default_rng(SEED)
    ud = np.unique(day)
    boot = np.empty(B)
    for k in range(B):
        pick = np.isin(day, rng.choice(ud, len(ud)))
        boot[k] = e0[pick].mean() - best[pick].mean()
    row = _row(
        scenario,
        model,
        "MASE (pooled)",
        best.mean(),
        "weekday mean / 24",
        e0.mean(),
        e0.mean() - best.mean(),
        boot,
        material,
        cause,
        n_train,
        len(e0),
    )
    row["best_variant"] = best_name
    return row


def forecast_variants(frames: list[dict]) -> pd.DataFrame:
    """Pooled MASE of every forecast variant over the test hours of the given series (for display)."""
    names = ["day/24", "weekday mean / 24", "Poisson GLM hour-of-week", "boosting with weekly lags"]
    out = {}
    for n in names:
        e = np.concatenate([np.abs(f["y"] - f[n]) / f["scale"] for f in frames])
        out[n] = float(np.nanmean(e))
    return pd.Series(out, name="pooled MASE").to_frame()


def channel(star: Star) -> tuple[list[dict], dict]:
    ch = star.q("""select country_code, channel, hour_start, hour_of_day, delivery_weekday, delivery_day, n_tx
                   from {fct_channel_hour} order by country_code, channel, hour_start""")
    frames = []
    for (_, _), d in ch.groupby(["country_code", "channel"], sort=True):
        y = d.n_tx.astype(float).reset_index(drop=True)
        how = ((d.delivery_weekday - 1) * 24 + d.hour_of_day).reset_index(drop=True)
        scale = _weekly_scale(y.to_numpy()[: -56 * 24])
        frames.append(
            _hourly_forecast(y, how, d.delivery_day.reset_index(drop=True), 56 * 24, scale)
        )
    row = _forecast_gate(
        "03 market and channel",
        "hourly volume per market × channel",
        frames,
        0.05,
        "generator independence",
        26 * 168 * len(frames),
    )
    return [row], {"series": len(frames), "variants": forecast_variants(frames)}


# ------------------------------------------------------------------------------------------------ 04 the branch
def branch(star: Star) -> tuple[list[dict], dict]:
    t = star.q("""select t.transaction_id, t.transaction_ts_utc, t.amount_usd, t.transaction_type, t.transaction_category,
                         t.is_cash, p.segment, p.age_years, b.branch_type, s.open_fraction
                  from {int_transactions_enriched} t
                  join {int_customer_profile} p using (customer_id)
                  join {stg_branches} b using (branch_id)
                  join {dim_hour} h on h.hour_start = date_trunc('hour', t.transaction_ts_utc)
                  join {dim_branch_schedule} s on s.branch_id = t.branch_id and s.iso_weekday = h.delivery_weekday
                       and s.hour_of_day = h.hour_of_day
                  where t.channel = 'Branch' order by t.transaction_ts_utc, t.transaction_id""")
    t["outside"] = (t.open_fraction == 0).astype(int)
    cut = t.transaction_ts_utc.quantile(2 / 3)
    X = (
        pd.get_dummies(
            t[["transaction_type", "transaction_category", "segment", "branch_type"]].astype(str)
        )
        .join(t[["amount_usd", "age_years"]].astype(float))
        .assign(is_cash=t.is_cash.astype(float))
    )
    tr, te = t.transaction_ts_utc <= cut, t.transaction_ts_utc > cut
    m = HistGradientBoostingClassifier(max_iter=200, random_state=SEED).fit(X[tr], t.outside[tr])
    rng = np.random.default_rng(SEED)
    p_b = np.full(int(te.sum()), t.outside[tr].mean()) + rng.normal(0, 1e-9, int(te.sum()))
    rows = [
        _auc_gate(
            "04 branch",
            "teller transaction outside opening hours",
            int(tr.sum()),
            t.outside[te].to_numpy(),
            m.predict_proba(X[te])[:, 1],
            p_b,
            "base rate",
            0.02,
            "data defect",
        )
    ]

    bh = star.q("""select branch_id, hour_start, hour_of_day, delivery_weekday, delivery_day, atm_cash_out_usd
                   from {fct_branch_hour} where n_atm > 0 order by branch_id, hour_start""")
    days = sorted(bh.delivery_day.unique())
    test_days = set(days[-28:])
    br = (
        bh.groupby(["branch_id", "delivery_day"])
        .atm_cash_out_usd.sum()
        .rename("day_cash")
        .reset_index()
    )
    br = br.sort_values(["branch_id", "delivery_day"])
    br["mean28"] = br.groupby("branch_id").day_cash.transform(
        lambda s: s.shift(1).rolling(28, min_periods=7).mean()
    )
    prof = (
        (
            bh[~bh.delivery_day.isin(test_days)]
            .groupby(["branch_id", "hour_of_day"])
            .atm_cash_out_usd.sum()
            / bh[~bh.delivery_day.isin(test_days)].groupby("branch_id").atm_cash_out_usd.sum()
        )
        .rename("hour_share")
        .reset_index()
    )
    full = (
        br[br.delivery_day.isin(test_days)][["branch_id", "delivery_day", "mean28"]]
        .merge(pd.DataFrame({"hour_of_day": range(24)}), how="cross")
        .merge(
            bh[["branch_id", "delivery_day", "hour_of_day", "atm_cash_out_usd"]],
            on=["branch_id", "delivery_day", "hour_of_day"],
            how="left",
        )
        .merge(prof, on=["branch_id", "hour_of_day"], how="left")
        .fillna({"atm_cash_out_usd": 0, "hour_share": 1 / 24})
        .dropna(subset=["mean28"])
        .sort_values(["branch_id", "delivery_day", "hour_of_day"])
    )
    y, flat, shaped = (
        full.atm_cash_out_usd.to_numpy(),
        full.mean28.to_numpy() / 24,
        (full.mean28 * full.hour_share).to_numpy(),
    )
    day = pd.factorize(full.delivery_day)[0]
    ud = np.unique(day)
    e0, e1 = np.abs(y - flat), np.abs(y - shaped)
    boot = np.empty(B)
    for k in range(B):
        pick = np.isin(day, rng.choice(ud, len(ud)))
        boot[k] = (e0[pick].mean() - e1[pick].mean()) / e0[pick].mean()
    rows.append(
        _row(
            "04 branch",
            "branch-hour ATM cash",
            "MAE (USD)",
            e1.mean(),
            "28-day mean / 24",
            e0.mean(),
            (e0.mean() - e1.mean()) / e0.mean(),
            boot,
            0.02,
            "generator independence",
            len(bh) - len(full),
            len(full),
        )
    )
    return rows, {
        "teller_outside_share": float(t.outside.mean()),
        "open_share": float((t.open_fraction > 0).mean()),
    }


# ------------------------------------------------------------------------------------------------ 05 agent and queue
def agent(star: Star) -> tuple[list[dict], dict]:
    a = star.q("""select f.agent_id, f.hour_start, f.contacts, f.handle_seconds, f.in_shift, f.contact_hour_of_day,
                         d.experience_level, d.agent_type, d.specialty
                  from {fct_agent_hour} f join {dim_agent} d using (agent_id) order by f.hour_start, f.agent_id""")
    a["aht"] = a.handle_seconds / a.contacts
    cut = a.hour_start.quantile(2 / 3)
    tr, te = a[a.hour_start <= cut], a[a.hour_start > cut]
    cols = [
        "contacts",
        "in_shift",
        "contact_hour_of_day",
        "experience_level",
        "agent_type",
        "specialty",
    ]
    X = pd.get_dummies(
        a[cols].astype({"in_shift": float}), columns=["experience_level", "agent_type", "specialty"]
    )
    m = HistGradientBoostingRegressor(max_iter=200, random_state=SEED).fit(X.loc[tr.index], tr.aht)
    bench = te.agent_id.map(tr.groupby("agent_id").aht.mean()).fillna(tr.aht.mean()).to_numpy()
    pm = m.predict(X.loc[te.index])
    y = te.aht.to_numpy()
    delta, boot = g.paired_boot(
        lambda yy, p: -mean_absolute_error(yy, p), y, pm, bench, B=B, seed=SEED
    )
    rel = delta / mean_absolute_error(y, bench)
    rows = [
        _row(
            "05 agent and queue",
            "handle time per agent-hour",
            "MAE (s)",
            mean_absolute_error(y, pm),
            "agent's own mean",
            mean_absolute_error(y, bench),
            rel,
            boot / mean_absolute_error(y, bench),
            0.02,
            "missing field",
            len(tr),
            len(te),
        )
    ]

    q = star.q("""select country_code, channel, hour_start, contact_hour_of_day, contact_weekday, contact_day, inbound
                  from {fct_contact_queue_hour} order by country_code, channel, hour_start""")
    frames = []
    for (_, _), d in q.groupby(["country_code", "channel"], sort=True):
        yy = d.inbound.astype(float).reset_index(drop=True)
        if yy.sum() < 1000:
            continue
        how = ((d.contact_weekday - 1) * 24 + d.contact_hour_of_day).reset_index(drop=True)
        scale = _weekly_scale(yy.to_numpy()[: -56 * 24])
        frames.append(
            _hourly_forecast(yy, how, d.contact_day.reset_index(drop=True), 56 * 24, scale)
        )
    rows.append(
        _forecast_gate(
            "05 agent and queue",
            "hourly contact arrivals per queue",
            frames,
            0.05,
            "generator independence",
            26 * 168 * len(frames),
        )
    )
    return rows, {
        "in_shift_share": float(a.contacts[a.in_shift].sum() / a.contacts.sum()),
        "variants": forecast_variants(frames),
    }


# ------------------------------------------------------------------------------------------------ 06 the case clock
def case_clock(star: Star) -> tuple[list[dict], dict]:
    from lifelines import CoxPHFitter
    from lifelines.utils import concordance_index

    c = star.q("""select complaint_id, created_clock, created_hour_of_day, created_weekday, priority, category,
                         reception_channel, country_code, hours_to_first_response, hours_observed_response,
                         responded_event, sla_breached
                  from {fct_case_clock} order by created_clock, complaint_id""")
    c = c[c.hours_observed_response > 0].reset_index(drop=True)
    X = pd.get_dummies(
        c[["priority", "category", "reception_channel", "country_code"]].astype(str),
        drop_first=True,
    ).astype(float)
    X["created_hour_of_day"] = c.created_hour_of_day.astype(float)
    X["weekend"] = (c.created_weekday >= 6).astype(float)
    cut = c.created_clock.quantile(2 / 3)
    tr, te = c.created_clock <= cut, c.created_clock > cut
    d = X[tr].assign(T=c.hours_observed_response[tr], E=c.responded_event[tr].astype(int))
    cox = CoxPHFitter(penalizer=0.01).fit(d, "T", "E")
    risk = cox.predict_partial_hazard(X[te]).to_numpy()
    T, E = c.hours_observed_response[te].to_numpy(), c.responded_event[te].astype(int).to_numpy()
    rng = np.random.default_rng(SEED)
    cidx = concordance_index(T, -risk, E)
    boot = np.empty(B)
    for k in range(B):
        i = rng.integers(0, len(T), len(T))
        boot[k] = concordance_index(T[i], -risk[i], E[i]) - 0.5
    rows = [
        _row(
            "06 case clock",
            "time to first response",
            "concordance",
            cidx,
            "no information",
            0.5,
            cidx - 0.5,
            boot,
            0.03,
            "generator independence",
            int(tr.sum()),
            int(te.sum()),
        )
    ]

    y = c.sla_breached.fillna(False).astype(int)
    m = HistGradientBoostingClassifier(max_iter=200, random_state=SEED).fit(X[tr], y[tr])
    p_b = np.full(int(te.sum()), y[tr].mean()) + rng.normal(0, 1e-9, int(te.sum()))
    rows.append(
        _auc_gate(
            "06 case clock",
            "SLA breach at creation",
            int(tr.sum()),
            y[te].to_numpy(),
            m.predict_proba(X[te])[:, 1],
            p_b,
            "base rate",
            0.02,
            "generator independence",
        )
    )
    return rows, {"cases": len(c), "responded_share": float(c.responded_event.mean())}


# ------------------------------------------------------------------------------------------------ 07 session and send
def session_send(star: Star) -> tuple[list[dict], dict]:
    s = star.q("""select session_id, session_start_utc, hour_of_day, n_pageviews, n_clicks, n_forms, n_errors,
                         first_error_position, has_purchase
                  from {fct_session} order by session_start_utc, session_id""")
    s = _sample(s, "session_id", 0.25)
    s["length"] = s.n_pageviews + s.n_clicks + s.n_forms + s.n_errors
    s["err_pos_rel"] = (s.first_error_position / (s.length + 2)).fillna(-1)
    cut = s.session_start_utc.quantile(2 / 3)
    tr, te = s.session_start_utc <= cut, s.session_start_utc > cut
    full = [
        "length",
        "n_pageviews",
        "n_clicks",
        "n_forms",
        "n_errors",
        "err_pos_rel",
        "hour_of_day",
    ]
    m = HistGradientBoostingClassifier(max_iter=200, random_state=SEED).fit(
        s.loc[tr, full], s.has_purchase[tr]
    )
    b = HistGradientBoostingClassifier(max_iter=100, random_state=SEED).fit(
        s.loc[tr, ["length"]], s.has_purchase[tr]
    )
    rows = [
        _auc_gate(
            "07 session and send",
            "session purchase from the event sequence",
            int(tr.sum()),
            s.has_purchase[te].astype(int).to_numpy(),
            m.predict_proba(s.loc[te, full])[:, 1],
            b.predict_proba(s.loc[te, ["length"]])[:, 1],
            "session length only",
            0.02,
            "generator independence",
        )
    ]

    r = star.q("""select send_id, send_channel, send_hour_of_day, send_weekday, opened, hours_to_open,
                         send_ts.send_ts_utc
                  from {fct_send_response} f join (select send_id, send_ts_utc from {fct_campaign_send}) send_ts
                  using (send_id) where open_tracked and was_delivered order by send_ts_utc, send_id""")
    r = _sample(r, "send_id", 0.4)
    r["open24"] = ((r.opened == 1) & (r.hours_to_open <= 24)).astype(int)
    cut = r.send_ts_utc.quantile(2 / 3)
    tr, te = r.send_ts_utc <= cut, r.send_ts_utc > cut
    Xf = pd.get_dummies(r[["send_channel", "send_hour_of_day", "send_weekday"]].astype(str)).astype(
        float
    )
    Xb = pd.get_dummies(r[["send_channel"]].astype(str)).astype(float)
    m = LogisticRegression(max_iter=1000).fit(Xf[tr], r.open24[tr])
    b = LogisticRegression(max_iter=1000).fit(Xb[tr], r.open24[tr])
    rows.append(
        _auc_gate(
            "07 session and send",
            "open within 24 h by send hour",
            int(tr.sum()),
            r.open24[te].to_numpy(),
            m.predict_proba(Xf[te])[:, 1],
            b.predict_proba(Xb[te])[:, 1],
            "channel only",
            0.02,
            "generator independence",
        )
    )
    return rows, {"sessions_sampled": len(s), "sends_sampled": len(r)}


SCENARIOS = {
    "02 customer": customer,
    "03 market and channel": channel,
    "04 branch": branch,
    "05 agent and queue": agent,
    "06 case clock": case_clock,
    "07 session and send": session_send,
}


def scorecard(star: Star) -> pd.DataFrame:
    """Every scenario's models and gates, in a stable order: the readiness scorecard of the hour grain."""
    rows = []
    for fn in SCENARIOS.values():
        rows.extend(fn(star)[0])
    out = pd.DataFrame(rows)
    num = out.select_dtypes("number").columns
    out[num] = out[num].round(6)
    return out.sort_values(["scenario", "model"], kind="stable").reset_index(drop=True)
