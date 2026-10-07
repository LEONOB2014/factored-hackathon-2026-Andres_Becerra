"""Chapter 4 · Time: shift diagnostics and the delivery clock.

Re-runs notebook 03's global-lag tests (weekday rotation, de-seasonalised cross-correlation), its matched filter and
clone split from the pinned parquet; reads its stored offset and drift tables, the clock scan and the calendar
reconciliation; and computes the report-only business-date flip rate by country.

    uv run python scripts/claims/04_time_and_clocks.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from report_lib import db, protocol
from report_lib.build import Chapter
from report_lib.estimators import bh
from report_lib.manifest import Claim
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

MAIN, BACKUP = REPO / "data" / "parquet", REPO / "data" / "parquet_backup"
OUT = BUILD / "sources"
TS = {  # process -> (timestamp column, protocol clock key)
    "transactions": ("transaction_date", "offset_hours_transactions"),
    "digital_events": ("event_date", "offset_hours_digital_events"),
    "campaign_sends": ("send_date", "offset_hours_campaign_sends"),
    "call_center_interactions": ("interaction_date", "offset_hours_contacts"),
    "complaints": ("creation_date", "offset_hours_complaints"),
}
LEGAL_KEYS = {  # the markets' legal clocks, read from the protocol (amended 2026-10-07)
    "México": "legal_offset_hours_mexico",
    "Colombia": "legal_offset_hours_colombia",
    "Argentina": "legal_offset_hours_argentina",
}


def daily(con, p, t):
    return (
        con.sql(f"select process_date d, count(*) n from {p}_{t} group by 1 order by 1")
        .df()
        .set_index("d")
        .n
    )


def global_lag(con) -> pd.DataFrame:
    """Notebook 03, H1a: best weekday rotation per quarter, and the cross-correlation of weekday-adjusted counts."""
    rows = []
    for t in (
        "transactions",
        "call_center_interactions",
        "digital_events",
        "campaign_sends",
        "complaints",
    ):
        m, b = daily(con, "m", t), daily(con, "b", t)
        idx = m.index.intersection(b.index)
        idx = pd.DatetimeIndex(idx)
        m.index, b.index = pd.DatetimeIndex(m.index), pd.DatetimeIndex(b.index)
        quarters = zero = 0
        for _, g in pd.Series(1, index=idx).groupby(idx.to_period("Q")):
            if len(g) < 60:
                continue
            pm = m[g.index].groupby(g.index.dayofweek).mean()
            pb = b[g.index].groupby(g.index.dayofweek).mean()
            pm, pb = (pm - pm.mean()) / pm.std(), (pb - pb.mean()) / pb.std()
            corr = [np.dot(np.roll(pm.to_numpy(), r), pb.to_numpy()) / 7 for r in range(7)]
            quarters += 1
            zero += int(np.argmax(corr) == 0)

        def resid(s):
            return s - s.groupby(s.index.dayofweek).transform("mean")

        a, c = resid(m[idx]).to_numpy(), resid(b[idx]).to_numpy()
        a, c = (a - a.mean()) / a.std(), (c - c.mean()) / c.std()
        ccf = np.array([np.mean(a[max(0, k) : len(a) + min(0, k)] * c[max(0, -k) : len(c) - max(0, k)])
                        for k in range(-30, 31)])  # fmt: skip
        band = 1.96 / np.sqrt(len(idx))
        rows.append({"table": t, "days": len(idx), "quarters": quarters, "rotation_zero": zero,
                     "max_abs_ccf": float(np.abs(ccf).max()), "ccf_lag0": float(ccf[30]), "band": band,
                     "lags_outside_band": int((np.abs(ccf) > band).sum()), "lags": len(ccf)})  # fmt: skip
    return pd.DataFrame(rows)


def main() -> None:
    con = db.connect()
    clock = protocol.load()["clock"]
    ch = Chapter(4, "ch04")
    OUT.mkdir(parents=True, exist_ok=True)

    # --- H1a, global lag (re-run of notebook 03 from the pinned parquet)
    lag = global_lag(con)
    lag_path = OUT / "ch04_global_lag.csv"
    lag.to_csv(lag_path, index=False)
    src = MAIN / "transactions.parquet"
    for r in lag.itertuples():
        s = r.table.replace("_", "-")
        ch.count(f"rot-quarters-{s}", r.quarters, src)
        ch.count(f"rot-zero-{s}", r.rotation_zero, src)
        ch.count(f"ccf-outside-{s}", r.lags_outside_band, src)
    ch.count("ccf-lags", int(lag.lags.iloc[0]), src)
    shift = lag[
        lag.table != "complaints"
    ]  # complaints are identical in both copies: correlation 1 at lag 0
    ch.census("ccf-max-abs", float(shift.max_abs_ccf.max()), src, digits=2)
    ch.census("ccf-band-min", float(shift.band.min()), src, digits=2)
    ch.census("ccf-band-max", float(shift.band.max()), src, digits=2)
    ch.census("ccf-expected-outside", 0.05 * int(lag.lags.iloc[0]), src, digits=2)
    ch.count("ccf-outside-max", int(shift.lags_outside_band.max()), src)
    ch.census(
        "ccf-complaints-lag0",
        float(lag.set_index("table").loc["complaints", "ccf_lag0"]),
        src,
        digits=3,
    )

    # --- H1b, row offsets and drift (stored tables of notebook 03)
    off = pd.read_csv(TABLES / "time_offsets_summary.csv").set_index("table")
    for t in off.index:
        s = t.replace("_", "-")
        ch.count(
            f"pairs-{s}",
            off.loc[t, "pairs"],
            TABLES / "time_offsets_summary.csv",
            source_type="table",
        )
        ch.census(f"whole-day-{s}", off.loc[t, "whole_day_ts_pct"], TABLES / "time_offsets_summary.csv",
                  source_type="table", unit="percent", digits=3)  # fmt: skip
        ch.count(
            f"offset-min-{s}",
            off.loc[t, "min_days"],
            TABLES / "time_offsets_summary.csv",
            source_type="table",
        )
        ch.count(
            f"offset-max-{s}",
            off.loc[t, "max_days"],
            TABLES / "time_offsets_summary.csv",
            source_type="table",
        )
    ch.census("spearman-min", float(off.spearman_dates.min()), TABLES / "time_offsets_summary.csv",
              source_type="table", digits=6)  # fmt: skip
    drift = pd.read_csv(TABLES / "time_shift_model_comparison.csv").set_index("table")
    for t in drift.index:
        s = t.replace("_", "-")
        best = min(drift.loc[t, ["bic_linear", "bic_piecewise"]])
        ch.census(f"bic-gap-{s}", drift.loc[t, "bic_constant"] - best, TABLES / "time_shift_model_comparison.csv",
                  source_type="table", digits=3)  # fmt: skip
        ch.census(f"slope-{s}", drift.loc[t, "slope_days_per_month"], TABLES / "time_shift_model_comparison.csv",
                  source_type="table", digits=2)  # fmt: skip
        ch.census(f"r2-{s}", drift.loc[t, "r2_linear"], TABLES / "time_shift_model_comparison.csv",
                  source_type="table", digits=2)  # fmt: skip

    # --- H1c, matched filter and clones (re-run of notebook 03)
    cols = "amount, currency, transaction_type, channel, transaction_country, merchant_name, fraud_score"
    mf = con.sql(f"""with a as (select hash({cols}) h, process_date d from m_transactions),
                          b as (select hash({cols}) h, process_date d from b_transactions)
                     select date_diff('day', a.d, b.d) k, count(*) n from a join b using (h)
                     group by 1 order by 1""").df()  # fmt: skip
    mf_path = OUT / "ch04_matched_filter.csv"
    mf.to_csv(mf_path, index=False)
    total = int(mf.n.sum())
    mode = mf.loc[mf.n.idxmax()]
    width = int(mf.k.max() - mf.k.min() + 1)
    ch.count("mf-pairs", total, BACKUP / "transactions.parquet")
    ch.count("mf-mode", int(mode.k), BACKUP / "transactions.parquet")
    ch.census(
        "mf-mode-share",
        100 * mode.n / total,
        BACKUP / "transactions.parquet",
        unit="percent",
        digits=2,
    )
    ch.census("mf-within-week", 100 * mf[mf.k.abs() <= 7].n.sum() / total, BACKUP / "transactions.parquet",
              unit="percent", digits=3)  # fmt: skip
    ch.census(
        "mf-uniform-week",
        100 * 15 / width,
        BACKUP / "transactions.parquet",
        unit="percent",
        digits=2,
    )
    ch.count("mf-support-days", width, BACKUP / "transactions.parquet")
    pairs = con.sql("""select date_diff('day', m.process_date, b.process_date) k,
               (m.amount = b.amount and m.currency = b.currency and m.transaction_type = b.transaction_type
                and m.channel = b.channel and m.fraud_score is not distinct from b.fraud_score
                and m.merchant_name is not distinct from b.merchant_name) clone,
               (m.customer_id = b.customer_id) same_customer, (m.product_id = b.product_id) same_product
        from m_transactions m join b_transactions b using (transaction_id)""").df()
    n_main = con.sql("select count(*) from m_transactions").fetchone()[0]
    clones = pairs[pairs.clone]
    ch.count("clones", len(clones), BACKUP / "transactions.parquet")
    ch.census("clones-of-shared", 100 * len(clones) / len(pairs), BACKUP / "transactions.parquet", unit="percent",
              digits=3)  # fmt: skip
    ch.census(
        "clones-of-main",
        100 * len(clones) / n_main,
        BACKUP / "transactions.parquet",
        unit="percent",
        digits=2,
    )
    ch.census("clones-same-customer", 100 * clones.same_customer.mean(), BACKUP / "transactions.parquet",
              unit="percent", digits=3)  # fmt: skip
    ch.census("clones-same-product", 100 * clones.same_product.mean(), BACKUP / "transactions.parquet",
              unit="percent", digits=3)  # fmt: skip
    for flag, name in ((True, "clone"), (False, "collision")):
        d = pairs[pairs.clone == flag].k
        ch.census(f"{name}-offset-mean", d.mean(), BACKUP / "transactions.parquet", digits=3)
        ch.census(f"{name}-offset-sd", d.std(), BACKUP / "transactions.parquet", digits=3)

    # --- the delivery clock: process_date reproduced at 0 h and at each process's delivery offset
    match = []
    for t, (ts, key) in TS.items():
        off_h = int(clock[key])
        for p, copy, base in (("m", "main", MAIN), ("b", "backup", BACKUP)):
            if not (base / f"{t}.parquet").exists():
                continue
            raw, shifted, six = con.sql(f"""select avg((cast({ts} as date) = process_date)::int),
                     avg((cast({ts} + interval ({off_h}) hour as date) = process_date)::int),
                     avg((cast({ts} - interval 6 hour as date) = process_date)::int) from {p}_{t}""").fetchone()
            match.append({"process": t, "dataset": copy, "delivery_offset_h": off_h, "raw_pct": 100 * raw,
                          "minus6_pct": 100 * six, "delivery_pct": 100 * shifted})  # fmt: skip
    match = pd.DataFrame(match)
    match_path = OUT / "ch04_delivery_clock.csv"
    match.to_csv(match_path, index=False)
    ch.census(
        "clock-raw-min",
        match.raw_pct.min(),
        MAIN / "transactions.parquet",
        unit="percent",
        digits=3,
    )
    ch.census("clock-delivery-min", match.delivery_pct.min(), MAIN / "transactions.parquet", unit="percent",
              digits=4)  # fmt: skip
    for t in ("call_center_interactions", "complaints"):
        r = match[(match.process == t) & (match.dataset == "main")].iloc[0]
        ch.census(f"clock-minus6-{t.replace('_', '-')}", r.minus6_pct, MAIN / f"{t}.parquet", unit="percent",
                  digits=3)  # fmt: skip

    # --- the clock scan (stored, granularity_time notebook 01)
    scan = pd.read_csv(TABLES / "granularity_time_clock.csv")
    expect = {t: int(clock[key]) for t, (_, key) in TS.items()}
    core = scan[scan.process.isin(expect)]
    agree = int(sum(r["best shift (h)"] == expect[r.process] for _, r in core.iterrows()))
    clean = core[core.process != "digital_events"]
    sp = TABLES / "granularity_time_clock.csv"
    ch.count("scan-cells", len(core), sp, source_type="table")
    ch.count("scan-agree", agree, sp, source_type="table")
    ch.count("scan-dof", 6 * 23, sp, source_type="table")
    ch.census("scan-best-min", clean["χ²/dof at best"].min(), sp, source_type="table", digits=2)
    ch.census("scan-best-max", clean["χ²/dof at best"].max(), sp, source_type="table", digits=2)
    ev = core[core.process == "digital_events"]
    ch.census("scan-events-min", ev["χ²/dof at best"].min(), sp, source_type="table", digits=2)
    ch.census("scan-events-max", ev["χ²/dof at best"].max(), sp, source_type="table", digits=2)
    ch.census(
        "scan-raw-min", core["χ²/dof at raw clock (0 h)"].min(), sp, source_type="table", digits=2
    )
    sv = scan[scan.process == "satisfaction_surveys"]
    ch.count("scan-surveys-shift-min", sv["best shift (h)"].min(), sp, source_type="table")
    ch.count("scan-surveys-shift-max", sv["best shift (h)"].max(), sp, source_type="table")
    render_table(sp, "ch04-clock-scan", "The clock scan: for each process and market, the shift that makes hour "
                 "independent of weekday, and the chi-square statistic per degree of freedom at that shift, at the "
                 "legal local time and at the raw timestamp.", digits=3)  # fmt: skip

    # --- report-only estimator: the business-date flip rate by country
    flips = []
    for t, (ts, key) in TS.items():
        off_h = int(clock[key])
        for country, lkey in LEGAL_KEYS.items():
            legal = int(clock[lkey])
            n, f = (
                con.sql(f"""select count(*), count(*) filter (where cast(x.{ts} + interval ({legal}) hour as date)
                                <> cast(x.{ts} + interval ({off_h}) hour as date))
                               from m_{t} x join m_customers c using (customer_id) where c.country = '{country}'""").fetchone()
            )
            flips.append(
                {"process": t, "country": country, "rows": n, "flipped": f, "flip_pct": 100 * f / n}
            )
    flips = pd.DataFrame(flips)
    flips_path = OUT / "ch04_business_date_flips.csv"
    flips.to_csv(flips_path, index=False)
    for country, code in (("Colombia", "co"), ("Argentina", "ar"), ("México", "mx")):
        r = flips[(flips.process == "transactions") & (flips.country == country)].iloc[0]
        ch.census(
            f"flip-tx-{code}", r.flip_pct, MAIN / "transactions.parquet", unit="percent", digits=3
        )
    ar = flips[flips.country == "Argentina"]
    ch.census(
        "flip-ar-min", ar.flip_pct.min(), MAIN / "transactions.parquet", unit="percent", digits=3
    )
    ch.census(
        "flip-ar-max", ar.flip_pct.max(), MAIN / "transactions.parquet", unit="percent", digits=3
    )
    ch.count(
        "flip-mx-flipped",
        int(flips[flips.country == "México"].flipped.sum()),
        MAIN / "transactions.parquet",
    )
    render_table(flips_path, "ch04-flips", "Business-date flip rate: share of rows whose date on the country's legal "
                 "clock differs from their delivery-clock date (report-only estimator).",
                 columns=["process", "country", "rows", "flip_pct"])  # fmt: skip

    # --- what the wrong clock did: calendar regression on both clocks (stored), with family q-values
    rec = pd.read_csv(TABLES / "granularity_time_reconciliation.csv")
    rp = TABLES / "granularity_time_reconciliation.csv"
    for code, mk in (("ar", "AR"), ("co", "CO")):
        for clk, name in (("local", "local"), ("business", "business")):
            r = rec[(rec.market == mk) & rec.clock.str.startswith(clk)].iloc[0]
            ch.census(
                f"sat-{code}-{name}",
                r["Saturday %"],
                rp,
                source_type="table",
                unit="percent",
                digits=3,
            )
            ch.census(
                f"mon-{code}-{name}",
                r["Monday vs Tue–Fri %"],
                rp,
                source_type="table",
                unit="percent",
                digits=2,
            )
    fam = next(f for f in protocol.load()["families"] if f["id"] == "country-calendar-main")
    frames = [
        pd.read_csv(TABLES / f"country_{c}_calendar_effects.csv") for c in ("all", "ar", "co", "mx")
    ]
    allp = pd.concat(frames, ignore_index=True)
    allp["q"] = bh.adjust(allp.p_value.to_numpy())
    assert len(allp) == fam["size"], "family size drifted from the frozen protocol"
    allp_path = OUT / "ch04_calendar_family.csv"
    allp.to_csv(allp_path, index=False)
    whole = allp[allp.country == "ALL"].set_index("term")
    for term, topic in (
        ("is_holiday", "holiday"),
        ("payday_window", "payday"),
        ("C(iso_weekday)[T.6]", "saturday"),
    ):
        r = whole.loc[term]
        ch.claims.append(Claim(
            id=f"ch04.cal-{topic}", kind="difference", estimate=float(r["effect %"]),
            lo=100 * float(np.expm1(r.ci_low)), hi=100 * float(np.expm1(r.ci_high)), interval_method="naive-iid",
            cluster_unit="none", p=float(r.p_value), q=float(r.q), family_id=fam["id"], family_size=fam["size"],
            unit="percent", digits=3, status="exploratory", source_type="table",
            source_path="eda/reports/tables/country_all_calendar_effects.csv",
            source_sha256=__import__("report_lib.sources", fromlist=["sha256"]).sha256(
                TABLES / "country_all_calendar_effects.csv"), chapter=4,
        ))  # fmt: skip
    ch.count("cal-rejected", int((allp.q <= 0.05).sum()), allp_path)
    ch.count(
        "cal-rejected-weekday",
        int(((allp.q <= 0.05) & allp.term.str.startswith("C(iso_weekday)")).sum()),
        allp_path,
    )
    ch.count("cal-family-size", fam["size"], allp_path)
    render_table(lag_path, "ch04-global-lag", "Global-lag tests re-run from the pinned parquet: quarters whose best "
                 "weekday rotation is zero, and lags (of the cross-correlation of weekday-adjusted daily counts) "
                 "outside the band.", columns=["table", "days", "quarters", "rotation_zero", "max_abs_ccf", "band",
                 "lags_outside_band", "lags"])  # fmt: skip
    render_table(TABLES / "time_offsets_summary.csv", "ch04-offsets", "Row-level date offsets (backup minus main) "
                 "of rows that share a key (notebook 03).", columns=["table", "pairs", "whole_day_ts_pct", "median_days",
                 "min_days", "max_days", "spearman_dates"], digits=4)  # fmt: skip
    render_table(TABLES / "time_shift_model_comparison.csv", "ch04-drift-models", "Monthly median offset: constant, "
                 "linear and piecewise-constant models compared by BIC (notebook 03).", columns=["table", "months",
                 "bic_constant", "bic_linear", "bic_piecewise", "winner", "slope_days_per_month", "r2_linear"])  # fmt: skip
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
