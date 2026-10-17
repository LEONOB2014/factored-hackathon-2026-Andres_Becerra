"""Chapter 7 · Schema forensics, contracts and drift.

Recomputes the physical-layer census from the raw fingerprint cache (model_risk/01), reads the detector scorecard,
the schema change log and the propagation audit it stored, and the per-country contract results of
country_template/03. Adds report-only analyses: the calibration of the permutation change-point test under serial
dependence (simulation), the dispersion and autocorrelation of the empty-share series the circuit breaker monitors,
with and without conditioning on applicability, a noise-aware alternative to the fixed empty-share band, the
foreign-label test for the `Mexico` spelling, and the sampling-noise floor of the population stability index.

    uv run python scripts/claims/07_schema_forensics.py
"""

from __future__ import annotations

import inspect
import re

import numpy as np
import pandas as pd
from scipy import optimize, stats

from report_lib import db
from report_lib.build import Chapter
from report_lib.eda import change_detection as cd
from report_lib.eda import raw_forensics as rf
from report_lib.estimators import intervals
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

FP = REPO / "data" / "derived" / "raw_fingerprints"
MAIN = REPO / "data" / "parquet"
DRIFT_SQL = REPO / "platform" / "dbt" / "models" / "silver" / "quality" / "dq_schema_drift.sql"
CONTRACT = REPO / "platform" / "contracts" / "sources" / "campaign_sends.yml"
CD = REPO / "eda" / "src" / "latam_eda" / "change_detection.py"
RF = REPO / "eda" / "src" / "latam_eda" / "raw_forensics.py"
NB_COUNTRY = REPO / "eda" / "notebooks" / "country_template" / "03_contract_and_drift.py"
THIS = REPO / "report" / "scripts" / "claims" / "07_schema_forensics.py"
OUT = BUILD / "sources"

REFERENCE_DAYS = (
    180  # the country template's reference window, adopted for the conditional baselines
)
Z_RULE = 4.0  # the noise-aware report threshold the country template recommends
SIM_PHI = (0.0, 0.3, 0.6)
SIM_REPS = 200
PSI_LEVEL = 0.95  # coverage of the no-change bound on the largest monthly PSI
TRACKED = ("Email", "SMS", "Push")  # channels with open tracking (WhatsApp and Voice have none)


def defaults(fn) -> dict:
    return {
        k: v.default
        for k, v in inspect.signature(fn).parameters.items()
        if v.default is not inspect._empty
    }


def physical(ch: Chapter) -> None:
    """Every record accounted for: CRLF terminators minus headers equal CSV-grammar records, per table and copy."""
    rows = []
    for copy in ("main", "backup"):
        for p in sorted((FP / copy).glob("*__files.parquet")):
            f = pd.read_parquet(p)
            rows.append({"dataset": copy, "table": p.name.split("__")[0], "files": len(f), "records": int(f.records.sum()),
                         "line_terminators": int(f.crlf.sum()), "embedded_lf": int(f.lf.sum()),
                         "multiline_records": int(f.multiline_records.sum()), "headers": f.header.nunique(),
                         "defects": int(f.ragged.sum() + f.grammar_error.notna().sum() + f.utf8_errors.sum()
                                        + f.nul_bytes.sum() + f.cr_only.sum())})  # fmt: skip
    t = pd.DataFrame(rows)
    t["unexplained"] = t.line_terminators - t.files - t.records
    t.to_csv(OUT / "ch07_physical.csv", index=False)
    src = FP / "main" / "transactions__files.parquet"
    for copy in ("main", "backup"):
        s = t[t.dataset == copy]
        ch.count(f"files-{copy}", s.files.sum(), FP / copy / "transactions__files.parquet")
        ch.count(f"records-{copy}", s.records.sum(), FP / copy / "transactions__files.parquet")
        ch.count(f"tables-{copy}", len(s), FP / copy / "transactions__files.parquet")
    ch.count("tables-identity", int((t.unexplained == 0).sum()), src)
    ch.count("defects", int(t.defects.sum()), src)
    ch.count("multi-header-tables", int((t.headers > 1).sum()), src)
    tr = t[(t.dataset == "main") & (t.table == "call_transcripts")].iloc[0]
    ch.count("transcript-records", tr.records, FP / "main" / "call_transcripts__files.parquet")
    ch.count(
        "transcript-multiline",
        tr.multiline_records,
        FP / "main" / "call_transcripts__files.parquet",
    )
    ch.census("transcript-lf-per-record", tr.embedded_lf / tr.records, FP / "main" / "call_transcripts__files.parquet",
              digits=3)  # fmt: skip
    render_table(OUT / "ch07_physical.csv", "ch07-physical", "Physical layer of every raw file, per table and copy: "
                 "line terminators (CRLF), records by CSV grammar, bare line feeds inside quoted fields, distinct "
                 "headers, and defects (ragged rows, grammar, encoding, NUL and lone CR). Unexplained is terminators "
                 "minus headers minus records.",
                 columns=["dataset", "table", "files", "records", "line_terminators", "embedded_lf", "headers", "defects",
                          "unexplained"])  # fmt: skip


def lexical(ch: Chapter) -> None:
    an = pd.read_csv(TABLES / "raw_format_anomalies.csv")
    ch.constant("type-coverage", defaults(rf.infer_type)["coverage"], RF, digits=4)
    ch.count("typed-columns", len(an), TABLES / "raw_format_anomalies.csv", source_type="table")
    ch.count(
        "minority-values",
        int(an.minority_values.sum()),
        TABLES / "raw_format_anomalies.csv",
        source_type="table",
    )
    pa = pd.read_csv(TABLES / "propagation_audit.csv")
    pp = TABLES / "propagation_audit.csv"
    ch.count("audited-columns", len(pa), pp, source_type="table")
    ch.count(
        "empty-to-null",
        int(pa.losses.fillna("").str.contains("became NULL").sum()),
        pp,
        source_type="table",
    )
    ch.count("other-losses", int(pa.losses.fillna("").str.replace("'' became NULL", "").str.strip(", ").ne("").sum()),
             pp, source_type="table")  # fmt: skip
    ch.count(
        "leading-zero-columns", int((pa.raw_leading_zero_codes > 0).sum()), pp, source_type="table"
    )
    ch.count("tz-columns", int((pa.raw_tz_values > 0).sum()), pp, source_type="table")
    ch.count("null-token-columns", int((pa.raw_null_tokens > 0).sum()), pp, source_type="table")


def detectors(ch: Chapter) -> None:
    p, b, s, st = (
        defaults(cd.classify_presence),
        defaults(cd.binseg),
        defaults(cd.scale_steps),
        defaults(cd.detect_table),
    )
    ch.constant("presence-k", p["k"], CD)
    ch.constant("presence-alpha", p["alpha"], CD)
    ch.constant("presence-stable", p["stable_share"], CD)
    ch.constant("binseg-alpha", b["alpha"], CD)
    ch.constant("binseg-perm", b["n_perm"], CD)
    ch.constant("binseg-min-size", b["min_size"], CD)
    ch.constant("binseg-min-p", 1 / (b["n_perm"] + 1), CD, digits=2)
    ch.constant("share-delta", st["min_share_delta"], CD)
    ch.constant("scale-min-step", s["min_step"], CD)
    ch.constant("scale-min-factor", 10 ** s["min_step"], CD, digits=3)

    sc = pd.read_csv(TABLES / "forensics_detector_scorecard.csv")
    sp = TABLES / "forensics_detector_scorecard.csv"
    mut = sc[sc.mutation != "clean_copy"]
    det = int(mut.detected.astype(str).eq("True").sum())
    ch.proportion("recall", det, len(mut), intervals.wilson(det, len(mut)), sp, source_type="table")
    ch.count("mutations", len(mut), sp, source_type="table")
    ch.census("delay-max", float(mut.delay_days.max()), sp, source_type="table")
    ch.count("false-alarms", int(mut.false_alarms_before_change.sum()), sp, source_type="table")
    ch.count("clean-new-findings", int(sc.loc[sc.mutation == "clean_copy", "new_findings"].iloc[0]), sp,
             source_type="table")  # fmt: skip
    sc.assign(detected=sc.detected.fillna("")).to_csv(OUT / "ch07_scorecard.csv", index=False)
    render_table(OUT / "ch07_scorecard.csv", "ch07-scorecard", "Synthetic positive controls: each mutation injected "
                 "into copies of real daily transaction files from the middle of the window, the finding expected, "
                 "whether it was detected, the delay in days and the false alarms before the change (model risk, "
                 "notebook 01).", columns=["mutation", "expected", "detected", "delay_days",
                                           "false_alarms_before_change"])  # fmt: skip

    log = pd.read_csv(TABLES / "schema_change_log.csv")
    lp = TABLES / "schema_change_log.csv"
    ch.count("findings", len(log), lp, source_type="table")
    for kind in (
        "share_shift",
        "born",
        "episode",
        "died",
        "variant",
        "snapshot",
        "coexisting",
        "burst",
        "level_shift",
    ):
        ch.count(
            f"findings-{kind.replace('_', '-')}",
            int((log.kind == kind).sum()),
            lp,
            source_type="table",
        )
    ch.count(
        "findings-unit-change", int((log.kind == "unit_change").sum()), lp, source_type="table"
    )
    log.assign(column=log.column.fillna(""), change_date=log.change_date.fillna(""))[
        ["table", "level", "column", "signal", "kind", "change_date"]
    ].to_csv(OUT / "ch07_change_log.csv", index=False)
    render_table(OUT / "ch07_change_log.csv", "ch07-change-log", "Every finding of the change detectors on the "
                 "main copy's raw text, with its level, kind and change date (model risk, notebook 01).")  # fmt: skip


def simulate(ch: Chapter, days: int) -> None:
    """False-alarm rate of the permutation binary segmentation on change-free AR(1) series of the real length."""
    rng = np.random.default_rng(2026)
    rows = []
    for phi in SIM_PHI:
        alarms = 0
        for s in range(SIM_REPS):
            e = rng.normal(size=days)
            x = np.empty(days)
            x[0] = e[0] / np.sqrt(1 - phi**2)
            for i in range(1, days):
                x[i] = phi * x[i - 1] + e[i]
            alarms += bool(cd.binseg(x, seed=s))
        rows.append({"phi": phi, "false_alarms": alarms, "series": SIM_REPS})
        tag = f"{int(round(10 * phi))}"
        ch.proportion(
            f"sim-alarm-phi{tag}", alarms, SIM_REPS, intervals.wilson(alarms, SIM_REPS), THIS
        )
    for phi in SIM_PHI[1:]:
        ch.constant(f"sim-phi{int(round(10 * phi))}", phi, THIS)
    ch.constant("sim-reps", SIM_REPS, THIS)
    pd.DataFrame(rows).to_csv(OUT / "ch07_binseg_sim.csv", index=False)


def dispersion(share: np.ndarray, n: np.ndarray) -> float:
    """Pearson dispersion of daily binomial shares: X^2 / (D - 1); about one when days are binomial draws."""
    ok = n > 0
    s, n = share[ok], n[ok]
    p = float((s * n).sum() / n.sum())
    return float((n * (s - p) ** 2 / (p * (1 - p))).sum() / (len(s) - 1))


def empty_share(ch: Chapter, con) -> int:
    d = con.sql(f"""
        select process_date as day, count(*) as sends,
               count(*) filter (where subject is null) as subject_empty,
               count(*) filter (where was_opened is null) as was_opened_empty,
               count(*) filter (where send_channel = 'Email') as subject_applicable,
               count(*) filter (where send_channel = 'Email' and subject is null) as subject_applicable_empty,
               count(*) filter (where send_channel in {TRACKED}) as was_opened_applicable,
               count(*) filter (where send_channel in {TRACKED} and was_opened is null) as was_opened_applicable_empty
        from m_campaign_sends group by 1 order by 1""").df()  # fmt: skip
    src = MAIN / "campaign_sends.parquet"
    contract = CONTRACT.read_text()
    sql = DRIFT_SQL.read_text()
    assert "abs(n_empty / n_rows - empty_share) >= 0.3" in sql
    band = 0.3
    ch.constant("band", band, DRIFT_SQL)
    ch.count("days", len(d), src)
    ch.count("days-no-email", int((d.subject_applicable == 0).sum()), src)
    ch.count("days-no-tracked", int((d.was_opened_applicable == 0).sum()), src)
    ch.census("email-share-median", float((d.subject_applicable / d.sends).median()), src, digits=2)
    ch.constant("reference-days", REFERENCE_DAYS, NB_COUNTRY, source_type="notebook")
    ch.constant("z-rule", Z_RULE, NB_COUNTRY, source_type="notebook")
    rows, daily = [], {"day": d.day}
    for col in ("subject", "was_opened"):
        tag = col.replace("_", "-")
        base = float(
            re.search(rf"\n  {col}:\n(?:    .*\n)*?    empty_share: ([0-9.]+)", contract).group(1)
        )
        ch.constant(f"baseline-{tag}", base, CONTRACT, digits=3)
        n, e = d.sends.to_numpy(float), d[f"{col}_empty"].to_numpy(float)
        na, ea = (
            d[f"{col}_applicable"].to_numpy(float),
            d[f"{col}_applicable_empty"].to_numpy(float),
        )
        s = e / n
        with np.errstate(invalid="ignore", divide="ignore"):
            sa = np.where(na > 0, ea / na, np.nan)
        ref = slice(0, REFERENCE_DAYS)
        b0 = float(ea[ref].sum() / na[ref].sum())
        with np.errstate(invalid="ignore", divide="ignore"):
            z_cond = (sa - b0) / np.sqrt(b0 * (1 - b0) / na)
        z_all = (s - base) / np.sqrt(base * (1 - base) / n)
        after = z_cond[REFERENCE_DAYS:]
        sav = sa[~np.isnan(sa)]
        mde = Z_RULE * np.sqrt(b0 * (1 - b0) / na[na > 0])
        reports = int((np.abs(s - base) >= band).sum())
        res = {
            "all rows": dict(reports=reports, phi=dispersion(s, n), lag1=float(np.corrcoef(s[:-1], s[1:])[0, 1]),
                             cps=len(cd.binseg(s)), z=int((np.abs(z_all) > Z_RULE).sum())),
            "applicable rows": dict(reports=int((np.abs(after) > Z_RULE).sum()), phi=dispersion(sav, na[na > 0]),
                                    lag1=float(np.corrcoef(sav[:-1], sav[1:])[0, 1]), cps=len(cd.binseg(sav)),
                                    z=int((np.abs(after) > Z_RULE).sum())),
        }  # fmt: skip
        for view, r in res.items():
            v = "all" if view == "all rows" else "cond"
            ch.census(f"{tag}-{v}-dispersion", r["phi"], src, digits=3)
            ch.census(f"{tag}-{v}-lag1", r["lag1"], src, digits=2)
            ch.count(f"{tag}-{v}-cps", r["cps"], src)
            ch.count(f"{tag}-{v}-z", r["z"], src)
            rows.append({"column": col, "rows judged": view,
                         "baseline": base if v == "all" else b0,
                         "rule": f"|share − baseline| ≥ {band:g}" if v == "all" else f"|z| > {Z_RULE:g} after day {REFERENCE_DAYS}",
                         "days reported": r["reports"], "dispersion": r["phi"], "lag-1 autocorrelation": r["lag1"],
                         "change points": r["cps"],
                         "median detectable shift": float(np.median(band if v == "all" else mde))})  # fmt: skip
        ch.count(f"{tag}-reports", reports, src)
        ch.census(
            f"{tag}-band-sd", float(np.median(band / np.sqrt(base * (1 - base) / n))), src, digits=3
        )
        ch.census(f"{tag}-cond-baseline", b0, src, digits=3)
        ch.count(f"{tag}-cond-days-judged", int((~np.isnan(after)).sum()), src)
        ch.census(f"{tag}-mde", float(np.median(mde)), src, digits=2)
        half = Z_RULE * np.sqrt(b0 * (1 - b0) / np.where(na > 0, na, np.nan))
        daily |= {f"{col}_all": s, f"{col}_cond": sa, f"{col}_cond_lo": b0 - half, f"{col}_cond_hi": b0 + half,
                  f"{col}_baseline": base,
                  f"{col}_cond_baseline": b0}  # fmt: skip
        if col == "subject":
            # the share of e-mails that must lose their subject on a day before the band reports it
            with_subject = (na - ea) / n
            need = np.clip(
                (band + base - s) / np.where(with_subject > 0, with_subject, np.nan), 0, None
            )
            need = need[~np.isnan(need)]
            ch.census("outage-needed-median", float(np.median(need)), src, digits=2)
            ch.census("outage-needed-p10", float(np.quantile(need, 0.1)), src, digits=2)
            ch.census("outage-needed-p90", float(np.quantile(need, 0.9)), src, digits=2)
            no_email = d.loc[d.subject_applicable == 0, "day"]
            ch.count("no-email-reported", int((np.abs(s - base) >= band)[d.subject_applicable.to_numpy() == 0].sum()),
                     src)  # fmt: skip
            assert len(no_email)
    pd.DataFrame(rows).to_csv(OUT / "ch07_empty_share.csv", index=False)
    pd.DataFrame(daily).to_csv(OUT / "ch07_empty_share_daily.csv", index=False)
    render_table(OUT / "ch07_empty_share.csv", "ch07-empty-share", "The empty-share check on campaign sends, judged "
                 "on all rows against the contract baseline with the fixed band, and on the rows where the field "
                 "applies against a reference-window baseline with a binomial z rule: days reported, Pearson "
                 "dispersion, lag-1 autocorrelation and change points of the daily share, and the median shift a day "
                 "must show to be reported.", digits=3)  # fmt: skip
    return len(d)


def labels(ch: Chapter, con) -> None:
    src = MAIN / "transactions.parquet"
    f = con.sql("""select t.customer_id as cid, c.country as customer_country, t.transaction_country as label
                   from m_transactions t join m_customers c using (customer_id)
                   where t.transaction_country in ('Mexico', 'USA', 'Spain', 'Brazil')""").df()  # fmt: skip
    rows = []
    for ctry, g in f.groupby("customer_country"):
        is_mx = (g.label == "Mexico").to_numpy(float)
        iv = intervals.cluster_bootstrap_ratio(is_mx, np.ones(len(g)), g.cid.to_numpy(), seed=7)
        tag = {"Argentina": "ar", "Colombia": "co", "México": "mx"}[ctry]
        ch.proportion(
            f"mexico-label-{tag}", is_mx.sum(), len(g), iv, src, cluster_unit="customer", digits=3
        )
        rows.append({"customer country": ctry, "foreign-labelled transactions": len(g),
                     "labelled Mexico": int(is_mx.sum()), "share": iv.estimate, "lower": iv.lo, "upper": iv.hi,
                     "customers": g.cid.nunique()})  # fmt: skip
    pd.DataFrame(rows).to_csv(OUT / "ch07_foreign_labels.csv", index=False)
    render_table(OUT / "ch07_foreign_labels.csv", "ch07-foreign-labels", "Transactions labelled with one of the "
                 "four foreign countries, by the customer's country: the share labelled Mexico, with a 95\\,\\% percentile "
                 "interval from resampling customers.", digits=3)  # fmt: skip
    mx = rows[[r["customer country"] for r in rows].index("México")]
    ch.count("mx-foreign", mx["foreign-labelled transactions"], src)
    ch.count("mx-foreign-mexico", mx["labelled Mexico"], src)
    acc = con.sql("""select count(*) filter (where c.country <> 'México' and t.transaction_country = 'México'),
                            count(*) filter (where t.transaction_country = 'Mexico')
                     from m_transactions t join m_customers c using (customer_id)""").fetchone()  # fmt: skip
    ch.count("accented-non-mexican", acc[0], src)
    ch.count("unaccented-total", acc[1], src)
    ev = MAIN / "digital_events.parquet"
    r = con.sql("""select count(*) filter (where customer_id is not null),
                          count(*) filter (where customer_id is not null and ip_country = 'Mexico'),
                          count(*) filter (where customer_id is null and ip_country = 'Mexico'),
                          count(*) filter (where customer_id is null and ip_country = 'México'),
                          count(*) filter (where customer_id is null)
                   from m_digital_events""").fetchone()  # fmt: skip
    ch.count("events-identified", r[0], ev)
    ch.count("events-identified-mexico", r[1], ev)
    ch.count("events-anon-mexico", r[2], ev)
    ch.count("events-anon-accented", r[3], ev)
    ch.census("events-anon-mexico-share", 100 * r[2] / r[4], ev, unit="percent", digits=3)
    xb = con.sql("""select count(*) filter (where e.ip_country <> c.country)
                    from m_digital_events e join m_customers c using (customer_id)""").fetchone()[0]  # fmt: skip
    ch.count("events-cross-border", xb, ev)
    cs = MAIN / "campaign_sends.parquet"
    n = con.sql("""select count(*), count(subject), count(*) filter (where subject = '¡Oferta especial en nan!')
                   from m_campaign_sends""").fetchone()  # fmt: skip
    ch.count("nan-subjects", n[2], cs)
    ch.census("nan-share-with-subject", 100 * n[2] / n[1], cs, unit="percent", digits=3)
    ch.census("nan-share-sends", 100 * n[2] / n[0], cs, unit="percent", digits=3)


def psi_null_max(
    cats: list[int], n_ref: float, n_months: np.ndarray, level: float = PSI_LEVEL
) -> float:
    """Quantile of the largest monthly PSI over all months and columns when nothing changed.

    Under no change, the PSI of a column with B categories is asymptotically chi-square with B - 1 degrees of freedom
    scaled by 1/n_ref + 1/n_month (Yurdakul 2018). Months and columns are treated as independent; they share the
    reference and the rows, so the true maximum is less spread and the bound is conservative.
    """
    scale = 1 / n_ref + 1 / np.asarray(n_months, float)

    def cdf(x: float) -> float:
        return float(
            np.prod([np.prod(stats.chi2.cdf(x / scale, b - 1)) for b in cats if b > 1])
        )  # a constant column has PSI 0

    return float(optimize.brentq(lambda x: cdf(x) - level, 1e-9, 1.0))


def countries(ch: Chapter, con) -> None:
    rows = []
    for prefix in ("country", "backup"):
        for code in ("all", "mx", "co", "ar"):
            p = TABLES / f"{prefix}_{code}_contract.csv"
            r = pd.read_csv(p).iloc[0]
            tag = f"{prefix}-{code}"
            ch.count(
                f"held-global-{tag}", int(r.partitions_held_global_contract), p, source_type="table"
            )
            ch.count(
                f"held-country-{tag}",
                int(r.partitions_held_country_contract),
                p,
                source_type="table",
            )
            ch.count(f"b-reports-{tag}", int(r.b_reports_country_contract), p, source_type="table")
            ch.census(f"amount-scale-{tag}", float(r.amount_scale_country_over_global), p, source_type="table",
                      digits=3)  # fmt: skip
            ch.census(f"max-psi-{tag}", float(r.max_monthly_psi), p, source_type="table", digits=2)
            rows.append({"dataset": r.dataset, "scope": r.country,
                         "held, global contract": int(r.partitions_held_global_contract),
                         "held, scope contract": int(r.partitions_held_country_contract),
                         "B reports, scope contract": int(r.b_reports_country_contract),
                         "amount scale, scope over global": float(r.amount_scale_country_over_global),
                         "largest monthly PSI": float(r.max_monthly_psi), "column": r.max_psi_column})  # fmt: skip
    t = pd.DataFrame(rows)
    # the sampling floor of the stored main PSIs: the same quarter sample, first six months as the reference
    m = con.sql("""select c.country, date_trunc('month', t.transaction_date) as month, count(*) as k
                   from m_transactions t join m_customers c using (customer_id)
                   where hash(t.transaction_id) % 4 = 0 group by all""").df()  # fmt: skip
    psi_cols = ("transaction_type", "channel", "currency", "transaction_status")
    cats = con.sql(f"""select c.country, {", ".join(f"count(distinct t.{x})" for x in psi_cols)}
                       from m_transactions t join m_customers c using (customer_id) group by 1""").df()  # fmt: skip
    cats = {
        r[0]: [10, *map(int, r[1:])] for r in cats.itertuples(index=False)
    }  # amount deciles, then categories
    cats["ALL"] = [10, *(int(con.sql(f"select count(distinct {x}) from m_transactions").fetchone()[0])
                         for x in psi_cols)]  # fmt: skip
    code = {"México": "MX", "Colombia": "CO", "Argentina": "AR"}
    m["scope"] = m.country.map(code)
    m = pd.concat([m, m.groupby("month", as_index=False).k.sum().assign(scope="ALL")])
    floor = {}
    for scope, g in m.groupby("scope"):
        g = g.sort_values("month")
        key = {v: k for k, v in code.items()}.get(scope, "ALL")
        floor[scope] = psi_null_max(cats[key], g.k.iloc[:6].sum(), g.k.iloc[6:].to_numpy())
        ch.census(
            f"psi-floor-{scope.lower()}", floor[scope], MAIN / "transactions.parquet", digits=2
        )
    t["no-change 95 % bound"] = t.scope.map(floor).where(t.dataset == "main")
    t.to_csv(OUT / "ch07_country_contracts.csv", index=False)
    ch.count("psi-columns", 1 + len(psi_cols), NB_COUNTRY, source_type="notebook")
    ch.constant("psi-level", 100 * PSI_LEVEL, THIS, unit="percent")
    ch.constant("psi-stable", 0.10, NB_COUNTRY, source_type="notebook")
    ch.constant("psi-shift", 0.25, NB_COUNTRY, source_type="notebook")
    render_table(OUT / "ch07_country_contracts.csv", "ch07-country-contracts", "The circuit breaker per scope: "
                 "partitions held under the bank-wide contract and under baselines re-estimated on the scope's first "
                 "180 days, severity-B reports, the scope's typical amount as a multiple of the global baseline, the "
                 "largest monthly population stability index over five columns and the column that reaches it, and "
                 "(main copy) the bound that largest index stays below in 95\\,\\% of histories with no change (country template, notebook 03).",
                 digits=3)  # fmt: skip


def thresholds(ch: Chapter) -> None:
    sql = DRIFT_SQL.read_text()
    for literal in ("0.001 * n_nonempty", "n_unknown > 0.2 * n_nonempty", ">= 0.5", "> 6", "1.4826 * scale_mad, 0.05",
                    "n_empty > 0.001 * n_rows", "n_nonzero >= 30"):  # fmt: skip
        assert literal in sql, literal
    ch.constant("t-format", 0.001, DRIFT_SQL)
    ch.constant("t-vocabulary", 0.2, DRIFT_SQL)
    ch.constant("t-scale-log", 0.5, DRIFT_SQL)
    ch.constant("t-scale-factor", 10**0.5, DRIFT_SQL, digits=2)
    ch.constant("t-scale-z", 6, DRIFT_SQL)
    ch.constant("t-mad-floor", 0.05, DRIFT_SQL)
    ch.constant("t-min-nonzero", 30, DRIFT_SQL)


def main() -> None:
    con = db.connect()
    ch = Chapter(7, "ch07")
    OUT.mkdir(parents=True, exist_ok=True)
    physical(ch)
    lexical(ch)
    detectors(ch)
    thresholds(ch)
    days = empty_share(ch, con)
    simulate(ch, days)
    labels(ch, con)
    countries(ch, con)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
