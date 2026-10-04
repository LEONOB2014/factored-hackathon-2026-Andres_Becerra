"""Country-scoped replay of the platform (country series): cut the lake by country, rebuild, enrich, evaluate.

The country series runs the whole `dbt_lakehouse` pipeline once per country on a lake that contains only that
country's data, so every decision (imputation, drift baselines, anomaly thresholds, model learnability) is taken on
the reality of that country, not on a blend of three.

How the lake is cut (`build_country_lake`):
* `customers` by their country; every customer-owned table (products, transactions, contacts, transcripts,
  surveys, complaints, campaign sends) by `customer_id` in that set, so every join stays complete;
* digital events of identified customers by `customer_id`; **anonymous** events (no customer id) by the IP country,
  the only country signal they carry;
* enterprise-wide reference data (branches, service agents, campaigns, exchange rates) is shared, not cut: an agent
  serves every country and a rate is a rate;
* the quarantined backup copy is cut the same way (its own customers' country), the correction log and the bronze
  proof manifests are shared links (headers are file metadata and do not change with a row filter).

Rows are copied unchanged, lineage columns included (`_source_file`, `_record_no`, `_record_sha256`): a country lake
is a lossless subset of the lossless bronze.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from latam_eda import pipeline as pipe


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    raw_names: tuple[
        str, ...
    ]  # spellings in the source (customers, transaction_country, ip_country)
    customer_raw: str  # the spelling in customers.country
    home_currency: str
    utc_offset: int  # fixed offset; no DST: MX abolished it in 2022 (outside border cities), CO none, AR since 2009
    timezone: str


COUNTRIES = {
    "MX": Country("MX", "Mexico", ("México", "Mexico"), "México", "MXN", -6, "America/Mexico_City"),
    "CO": Country("CO", "Colombia", ("Colombia",), "Colombia", "COP", -5, "America/Bogota"),
    "AR": Country(
        "AR", "Argentina", ("Argentina",), "Argentina", "ARS", -3, "America/Argentina/Buenos_Aires"
    ),
}

CUSTOMER_TABLES = (
    "products",
    "transactions",
    "call_center_interactions",
    "call_transcripts",
    "satisfaction_surveys",
    "complaints",
    "campaign_sends",
)
SHARED_TABLES = ("branches", "service_agents", "marketing_campaigns", "daily_exchange_rates")
BACKUP_DIR = "quarantine/backup_20260831_raw"


def country_dir(repo: Path, code: str) -> Path:
    base = Path(os.environ.get("LATAM_COUNTRY_DIR", repo / "data" / "tmp" / "country"))
    return (base / code.lower()).resolve()


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _copy(con, src_glob: str, where: str, dest: Path) -> int:
    """Copy the rows of one bronze table that satisfy `where` into dest/<partition>/ (lineage kept)."""
    dest.mkdir(parents=True, exist_ok=True)
    rel = f"read_parquet('{src_glob}', union_by_name = true, hive_partitioning = false)"
    n = con.sql(f"SELECT count(*) FROM {rel} WHERE {where}").fetchone()[0]
    if n:
        con.sql(f"""COPY (SELECT * FROM {rel} WHERE {where}) TO '{dest}'
                    (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (_partition_date), WRITE_PARTITION_COLUMNS true,
                     OVERWRITE_OR_IGNORE true, FILENAME_PATTERN 'part-{{i}}')""")
    return n


def _link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        return
    dst.symlink_to(src, target_is_directory=src.is_dir())


def build_country_lake(code: str, lake: Path, out: Path, force: bool = False) -> pd.DataFrame:
    """Write the country's lossless subset of the lake to `out` and return rows kept per (zone, table)."""
    c = COUNTRIES[code]
    done = out / "_country_lake.json"
    if done.exists() and not force:
        return pd.DataFrame(json.loads(done.read_text()))
    con = duckdb.connect()
    con.sql("SET enable_progress_bar = false")
    con.sql("SET preserve_insertion_order = false")
    rows = []
    for zone, src_root in (("bronze_raw", lake / "bronze_raw"), ("backup", lake / BACKUP_DIR)):
        dst_root = out / ("bronze_raw" if zone == "bronze_raw" else BACKUP_DIR)
        if not src_root.exists():
            continue
        cust = f"{src_root}/customers/*/*.parquet"
        con.sql(f"""CREATE OR REPLACE TEMP TABLE ids AS SELECT DISTINCT customer_id
                    FROM read_parquet('{cust}', union_by_name = true, hive_partitioning = false)
                    WHERE country = {_q(c.customer_raw)}""")
        tables = sorted(p.name for p in src_root.iterdir() if p.is_dir())
        for t in tables:
            src = src_root / t
            total = con.sql(
                f"SELECT count(*) FROM read_parquet('{src}/*/*.parquet', union_by_name = true, hive_partitioning = false)"
            ).fetchone()[0]
            if t in SHARED_TABLES:
                _link(src, dst_root / t)
                kept, how = total, "shared (not cut)"
            elif t == "customers":
                kept = _copy(
                    con, f"{src}/*/*.parquet", f"country = {_q(c.customer_raw)}", dst_root / t
                )
                how = "customer country"
            elif t == "digital_events":
                names = ", ".join(_q(n) for n in c.raw_names)
                where = (
                    f"customer_id IN (SELECT customer_id FROM ids) OR "
                    f"(coalesce(customer_id, '') = '' AND ip_country IN ({names}))"
                )
                kept = _copy(con, f"{src}/*/*.parquet", where, dst_root / t)
                how = "customer, or IP country when anonymous"
            else:
                kept = _copy(
                    con,
                    f"{src}/*/*.parquet",
                    "customer_id IN (SELECT customer_id FROM ids)",
                    dst_root / t,
                )
                how = "customer of the country"
            rows.append(
                {"zone": zone, "table": t, "rows_total": total, "rows_kept": kept, "rule": how}
            )
        if zone == "bronze_raw":
            hold = lake / "holdout_raw"
            for t in sorted(p.name for p in hold.iterdir() if p.is_dir()):
                src = hold / t
                total = con.sql(
                    f"SELECT count(*) FROM read_parquet('{src}/*/*.parquet', union_by_name = true, hive_partitioning = false)"
                ).fetchone()[0]
                if t == "digital_events":
                    names = ", ".join(_q(n) for n in c.raw_names)
                    where = (
                        f"customer_id IN (SELECT customer_id FROM ids) OR "
                        f"(coalesce(customer_id, '') = '' AND ip_country IN ({names}))"
                    )
                else:
                    where = "customer_id IN (SELECT customer_id FROM ids)"
                kept = _copy(con, f"{src}/*/*.parquet", where, out / "holdout_raw" / t)
                rows.append(
                    {
                        "zone": "holdout_raw",
                        "table": t,
                        "rows_total": total,
                        "rows_kept": kept,
                        "rule": "as in bronze",
                    }
                )
    _link(lake / "corrections", out / "corrections")
    _link(lake / "manifests", out / "manifests")
    con.close()
    df = pd.DataFrame(rows)
    df["kept_pct"] = (100 * df.rows_kept / df.rows_total.replace(0, np.nan)).round(2)
    done.write_text(df.to_json(orient="records"))
    return df


def session(code: str, cwd: Path | None = None, recompile: bool = False) -> pipe.Pipeline:
    """The country's scratch lakehouse: build its lake if needed, compile against it, open the emulator."""
    repo = pipe.repo_root(Path(cwd or Path.cwd()))
    base = country_dir(repo, code)
    lake = base / "lake"
    build_country_lake(code, pipe.default_lake(repo), lake)
    work = base / "pipeline"
    manifest = work / "target" / "manifest.json"
    if recompile or not manifest.exists():
        pipe.compile_project(repo, work, lake)
    pl = pipe.Pipeline(manifest, work / "lakehouse.duckdb")
    pl.repo, pl.lake, pl.country = repo, lake, COUNTRIES[code]
    pl.restricted = pipe.restricted_columns(repo)
    return pl


# ---------------------------------------------------------------------------------------------- calendar
def _easter(year: int) -> date:
    from dateutil.easter import easter

    return easter(year)


def bank_holidays(code: str, years: range) -> dict[date, str]:
    """Statutory holidays (python-holidays) plus the days banks close although the labour law does not list them.

    Mexico: the labour law lists 7 days, but the CNBV bank calendar also closes Holy Thursday and Good Friday, the
    Day of the Dead (2 Nov) and the Virgin of Guadalupe (12 Dec), and on those days branch and transfer activity
    stops like on any holiday. Colombia's and Argentina's statutory lists already include the bank closures.
    """
    import holidays

    out = dict(holidays.country_holidays(code, years=list(years)).items())
    if code == "MX":
        for y in years:
            e = _easter(y)
            out.setdefault(e - timedelta(days=3), "Jueves Santo (bancario)")
            out.setdefault(e - timedelta(days=2), "Viernes Santo (bancario)")
            out.setdefault(date(y, 11, 2), "Día de Muertos (bancario)")
            out.setdefault(date(y, 12, 12), "Día de la Virgen de Guadalupe (bancario)")
    return out


def calendar(code: str, start: str = "2023-06-01", end: str = "2026-07-31") -> pd.DataFrame:
    """One row per local calendar day with the variables a behavioural model of a LATAM bank needs.

    * weekday, weekend, holiday (and its name), long weekend (bridge), business day;
    * pay cycle: Mexico and Colombia pay salaries fortnightly (the 15th and the last day, "quincena"), Argentina
      monthly in the first business days; `is_payday` marks the pay day moved back to the previous business day when
      it falls on a weekend or holiday, `days_since_payday` counts from it;
    * month start and end, week of month, quarter;
    * bonus seasons: Mexico's aguinaldo (by 20 December), Colombia's prima (June and December), Argentina's
      aguinaldo/SAC (June and December).
    """
    days = pd.date_range(start, end, freq="D")
    hol = bank_holidays(code, range(days.min().year, days.max().year + 1))
    df = pd.DataFrame({"local_date": days.date})
    d = pd.to_datetime(df.local_date)
    df["iso_weekday"] = d.dt.isocalendar().day.astype(int)
    df["is_weekend"] = df.iso_weekday >= 6
    df["holiday_name"] = df.local_date.map(hol)
    df["is_holiday"] = df.holiday_name.notna()
    df["is_business_day"] = ~(df.is_weekend | df.is_holiday)
    off = ~df.is_business_day
    df["is_long_weekend"] = (
        off
        & (off.shift(1, fill_value=False) | off.shift(-1, fill_value=False))
        & (off.rolling(3, center=True, min_periods=1).sum() >= 3)
    )
    bdays = set(df.local_date[df.is_business_day])

    def back_to_business(x: date) -> date:
        while x not in bdays and x > df.local_date.iloc[0]:
            x -= timedelta(days=1)
        return x

    def forward_to_business(x: date, n: int = 1) -> list[date]:
        out, cur = [], x
        while len(out) < n and cur <= df.local_date.iloc[-1]:
            if cur in bdays:
                out.append(cur)
            cur += timedelta(days=1)
        return out

    paydays = set()
    for m in pd.period_range(days.min(), days.max(), freq="M"):
        first = m.start_time.date()
        last = m.end_time.date()
        if code in ("MX", "CO"):
            paydays.add(back_to_business(date(m.year, m.month, 15)))
            paydays.add(back_to_business(last))
        else:  # Argentina: monthly salary within the first 4 business days; mark the first of them
            paydays.update(forward_to_business(first, 1))
    df["is_payday"] = df.local_date.isin(paydays)
    last_pay = None
    since = []
    for x, p in zip(df.local_date, df.is_payday, strict=True):
        if p:
            last_pay = x
        since.append((x - last_pay).days if last_pay else np.nan)
    df["days_since_payday"] = since
    df["is_month_start"] = d.dt.day <= 3
    df["is_month_end"] = d.dt.days_in_month - d.dt.day <= 2
    df["week_of_month"] = ((d.dt.day - 1) // 7 + 1).astype(int)
    df["month"] = d.dt.month
    df["quarter"] = d.dt.quarter
    bonus = {"MX": (12,), "CO": (6, 12), "AR": (6, 12)}[code]
    df["is_bonus_month"] = df.month.isin(bonus)
    return df


def enrich_transactions(pl: pipe.Pipeline) -> pd.DataFrame:
    """Create main.tx_local: every enriched transaction with local time and the calendar of its country.

    Local time uses the **customer's** country offset (the bank's view of the customer's day); the transaction
    country can differ for cross-border rows, which keep their own `transaction_ts_local` from silver.
    """
    c = pl.country
    cal = calendar(c.code)
    pl.con.register("cal_df", cal)
    pl.con.sql("CREATE OR REPLACE TABLE main.calendar_local AS SELECT * FROM cal_df")
    pl.con.unregister("cal_df")
    pl.con.sql(f"""
        CREATE OR REPLACE TABLE main.tx_local AS
        SELECT t.*,
               t.transaction_ts_utc + INTERVAL ({c.utc_offset}) HOUR AS ts_customer_local,
               CAST(t.transaction_ts_utc + INTERVAL ({c.utc_offset}) HOUR AS DATE) AS local_date,
               hour(t.transaction_ts_utc + INTERVAL ({c.utc_offset}) HOUR) AS local_hour_customer,
               k.iso_weekday, k.is_weekend AS is_weekend_local, k.is_holiday, k.holiday_name, k.is_long_weekend,
               k.is_business_day, k.is_payday, k.days_since_payday, k.is_month_start, k.is_month_end,
               k.week_of_month, k.month, k.quarter, k.is_bonus_month
        FROM {pl.relation(pl.key("int_transactions_enriched"))} t
        LEFT JOIN main.calendar_local k
          ON k.local_date = CAST(t.transaction_ts_utc + INTERVAL ({c.utc_offset}) HOUR AS DATE)""")
    return pl.q("SELECT count(*) AS n_rows, count(iso_weekday) AS with_calendar FROM main.tx_local")


# ---------------------------------------------------------------------------------------------- baselines
REFERENCE_DAYS = 180  # the reference window a country's contract baselines are estimated on


def country_baselines(pl: pipe.Pipeline, reference_days: int = REFERENCE_DAYS) -> pd.DataFrame:
    """Contract drift baselines re-estimated on the country's own **reference window**.

    The global contract's baselines were measured on the three countries mixed. Amounts are in each country's
    currency mix, so their typical magnitude differs by orders of magnitude between countries (Argentine pesos are
    about 350 per dollar): checked against the blended baseline, every Argentine and Colombian day looks like a unit
    change. Baselines are estimated on the first `reference_days` of history, as a drift reference should be: a
    baseline fitted on the whole history would absorb the very changes it is meant to detect. Same estimators as the
    contract generator: share of empty values, median of the daily log10 medians, median absolute deviation of them.
    """
    return pl.q(f"""
        with p as (
            select table_name, column_name, partition_date, n_rows, n_empty, n_absent, log10_median
            from {{dq_partition_profile}}
            where zone = 'bronze'
              and partition_date < (select min(partition_date) from {{dq_partition_profile}}) + {reference_days}),
        m as (select table_name, column_name, median(log10_median) as med from p group by 1, 2)
        select p.table_name, p.column_name,
               sum(p.n_empty + p.n_absent) / sum(p.n_rows) as empty_share_country,
               any_value(m.med) as scale_log10_median_country,
               median(abs(p.log10_median - m.med)) as scale_mad_country,
               count(*) as reference_partitions
        from p join m using (table_name, column_name) group by 1, 2""")


def _country_seed_sql(pl: pipe.Pipeline, source: str) -> str:
    return f"""
        SELECT s.* EXCLUDE (_country_baseline) REPLACE (
                 coalesce(b.empty_share_country, s.empty_share) AS empty_share,
                 CASE WHEN s.scale_log10_median IS NOT NULL THEN b.scale_log10_median_country END AS scale_log10_median,
                 CASE WHEN s.scale_log10_median IS NOT NULL THEN b.scale_mad_country END AS scale_mad),
               true AS _country_baseline
        FROM (SELECT *, false AS _country_baseline FROM {source}) s LEFT JOIN base_df b USING (table_name, column_name)"""


def drift_with_country_baselines(pl: pipe.Pipeline) -> pd.DataFrame:
    """What-if: the compiled drift SQL against the contract with the country's baselines (nothing is changed)."""
    pl.con.register("base_df", country_baselines(pl))
    seed = pl.relation(pl.key("source_contract_columns"))
    pl.con.sql(f"CREATE OR REPLACE TEMP TABLE contract_country AS {_country_seed_sql(pl, seed)}")
    pl.con.unregister("base_df")
    sql = pl.sql("dq_schema_drift").replace(seed, "temp.main.contract_country")
    return pl.con.sql(f"SELECT * EXCLUDE (checked_at) FROM ({sql})").df()


def country_contract_applied(pl: pipe.Pipeline) -> bool:
    cols = (
        pl.columns("source_contract_columns")["column_name"].tolist()
        if pl.exists(pl.key("source_contract_columns"))
        else []
    )
    return "_country_baseline" in cols


def invalidate_downstream(pl: pipe.Pipeline, name: str, keep: tuple[str, ...] = ()) -> list[str]:
    """Drop every built relation downstream of `name` so the next build recomputes it from the new input."""
    dropped = []
    for d in pl.lineage(name)["downstream"]:
        if d in keep:
            continue
        k = pl.key(d)
        if pl.exists(k):
            kind = "VIEW" if pl.nodes[k]["config"].get("materialized") == "view" else "TABLE"
            pl.con.sql(f"DROP {kind} IF EXISTS {pl.relation(k)}")
            dropped.append(d)
    return dropped


def apply_country_contract(pl: pipe.Pipeline, force: bool = False) -> dict:
    """Replace the contract seed by the country's version (reference-window baselines) and invalidate what used it.

    Idempotent: a seed already carrying `_country_baseline` is left alone unless `force`. Run after the partition
    profile exists (notebook 02/03); everything downstream of the contract is dropped and rebuilt on demand.
    """
    if country_contract_applied(pl) and not force:
        return {"applied": False, "reason": "already applied"}
    if force:
        pl.build("source_contract_columns")  # back to the reviewed CSV before re-basing
    pl.ensure(pl.key("dq_partition_profile"))
    seed = pl.relation(pl.key("source_contract_columns"))
    pl.con.register("base_df", country_baselines(pl))
    pl.con.sql(f"CREATE OR REPLACE TEMP TABLE contract_country AS {_country_seed_sql(pl, seed)}")
    pl.con.unregister("base_df")
    pl.con.sql(f"CREATE OR REPLACE TABLE {seed} AS SELECT * FROM temp.main.contract_country")
    dropped = invalidate_downstream(pl, "source_contract_columns", keep=("dq_partition_profile",))
    return {"applied": True, "rebuilt_on_demand": len(dropped)}


def country_rule_slo(pl: pipe.Pipeline) -> pd.DataFrame:
    """Integrity-rule SLOs re-based on the country: baseline = the country's own rate, maximum = baseline scaled by
    the global max/baseline ratio (at least +0.1 point). Rules whose policy maximum is 0 % (R21, R25, R26) keep it:
    a policy is not re-based by geography."""
    return pl.q("""
        select s.rule_id, s.severity, s.table_name, s.rate_pct as country_rate_pct,
               g.baseline_rate_pct as global_baseline_pct, g.max_rate_pct as global_max_pct,
               case when g.max_rate_pct = 0 then 0
                    else greatest(s.rate_pct * g.max_rate_pct / nullif(g.baseline_rate_pct, 0), s.rate_pct + 0.1)
               end as country_max_pct,
               s.rate_pct > g.max_rate_pct as breaches_global_slo
        from {dq_rule_summary} s join {dq_rule_slo} g using (rule_id)
        where s.rule_id like 'R%'""")


def global_contract(pl: pipe.Pipeline) -> str:
    """Load the reviewed (global) contract CSV into temp.main.contract_global and return that relation name, so a
    notebook can compare against it even after the country contract replaced the seed table."""
    seed_key = pl.key("source_contract_columns")
    n = pl.nodes[seed_key]
    path = Path(n["root_path"]) / n["original_file_path"]
    types = dict(
        pl.q("""select column_name, data_type from information_schema.columns
                         where table_name = 'source_contract_columns' and column_name <> '_country_baseline'""").values
    )
    cols = ", ".join(f'try_cast(nullif("{c}", \'\') AS {t}) AS "{c}"' for c, t in types.items())
    pl.con.execute(
        f"CREATE OR REPLACE TEMP TABLE contract_global AS SELECT {cols} FROM read_csv(?, all_varchar = true)",
        [str(path)],
    )
    return "temp.main.contract_global"


def global_contract_drift(pl: pipe.Pipeline) -> pd.DataFrame:
    """The drift checks as the global (reviewed CSV) contract would judge this country: what Airflow would hold if
    the country were run on the shared contract."""
    rel = global_contract(pl)
    sql = pl.sql("dq_schema_drift").replace(pl.relation(pl.key("source_contract_columns")), rel)
    return pl.con.sql(f"SELECT * EXCLUDE (checked_at) FROM ({sql})").df()


def prepare(pl: pipe.Pipeline, layer: str) -> None:
    """Everything up to `layer`, on the country's contract (a notebook run on its own gets the same state)."""
    pl.build_layer("seeds", verbose=False)
    apply_country_contract(pl)
    pl.ensure_until(layer)


# ---------------------------------------------------------------------------------------------- learnability
def hanley_mcneil(auc: float, npos: int, nneg: int) -> float:
    q1, q2 = auc / (2 - auc), 2 * auc * auc / (1 + auc)
    return float(
        np.sqrt(
            (auc * (1 - auc) + (npos - 1) * (q1 - auc * auc) + (nneg - 1) * (q2 - auc * auc))
            / max(npos * nneg, 1)
        )
    )


def evaluate_target(
    df: pd.DataFrame,
    target: str,
    time_col: str,
    features: list[str],
    test_frac: float = 0.25,
    seed: int = 7,
    n_boot: int = 200,
) -> dict:
    """Out-of-time learnability of one target: train on the earlier 75 %, test on the later 25 % (by time).

    Gradient boosting (scikit-learn's HistGradientBoosting, categorical features native) with class weights;
    reports test ROC AUC with a Hanley–McNeil interval, average precision against the base rate with a bootstrap
    interval, and the lift of AP over the base rate. AP is the honest metric for rare targets.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, roc_auc_score

    d = df.dropna(subset=[target, time_col]).copy()
    d[time_col] = pd.to_datetime(d[time_col])
    # a total, stable order: rows sharing a timestamp would otherwise reach the model in whatever order the database
    # returned them, and boosting's internal early-stopping split would see a different sample on every run
    d = d.sort_values(
        [time_col, *features, target], kind="mergesort", na_position="last"
    ).reset_index(drop=True)
    cut = d[time_col].quantile(1 - test_frac)
    tr, te = d[d[time_col] < cut], d[d[time_col] >= cut]
    X = d[features].copy()
    cats = [
        c
        for c in features
        if not (pd.api.types.is_numeric_dtype(X[c]) or pd.api.types.is_bool_dtype(X[c]))
    ]
    for col in cats:
        X[col] = X[col].astype("category").cat.codes.replace(-1, np.nan)
    for col in features:
        if pd.api.types.is_bool_dtype(X[col]):
            X[col] = X[col].astype(float)
    ytr, yte = tr[target].astype(int).to_numpy(), te[target].astype(int).to_numpy()
    out = {
        "target": target,
        "train_rows": len(tr),
        "test_rows": len(te),
        "train_positives": int(ytr.sum()),
        "test_positives": int(yte.sum()),
        "base_rate": float(yte.mean()) if len(yte) else np.nan,
        "split_at": str(cut),
    }
    if ytr.sum() < 20 or yte.sum() < 10 or ytr.sum() == len(ytr):
        out.update(
            auc=np.nan,
            auc_lo=np.nan,
            auc_hi=np.nan,
            ap=np.nan,
            ap_lo=np.nan,
            ap_hi=np.nan,
            ap_lift=np.nan,
            note="too few positives to evaluate",
        )
        return out
    w = np.where(ytr == 1, (len(ytr) - ytr.sum()) / max(ytr.sum(), 1), 1.0)
    m = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.06,
        max_leaf_nodes=31,
        min_samples_leaf=100,
        l2_regularization=1.0,
        categorical_features=[features.index(c) for c in cats] or None,
        random_state=seed,
    )
    m.fit(X.loc[tr.index].to_numpy(dtype=float), ytr, sample_weight=w)
    p = m.predict_proba(X.loc[te.index].to_numpy(dtype=float))[:, 1]
    auc = roc_auc_score(yte, p)
    se = hanley_mcneil(auc, int(yte.sum()), int(len(yte) - yte.sum()))
    ap = average_precision_score(yte, p)
    rng = np.random.default_rng(seed)
    aps = []
    for _ in range(n_boot):
        i = rng.integers(0, len(yte), len(yte))
        if yte[i].sum():
            aps.append(average_precision_score(yte[i], p[i]))
    singles = {}
    xte = X.loc[te.index]
    for col in features:
        x = xte[col].to_numpy(dtype=float)
        ok = ~np.isnan(x)
        if (
            ok.sum() > 100 and len(np.unique(x[ok])) > 1 and 10 <= yte[ok].sum() < ok.sum()
        ):  # >= 10 positives
            a1 = roc_auc_score(yte[ok], x[ok])
            singles[col] = max(a1, 1 - a1)
    best = max(singles, key=singles.get) if singles else None
    out.update(best_single_feature=best, best_single_auc=singles.get(best, np.nan))
    out.update(
        auc=auc,
        auc_lo=auc - 1.96 * se,
        auc_hi=auc + 1.96 * se,
        ap=ap,
        ap_lo=float(np.quantile(aps, 0.025)),
        ap_hi=float(np.quantile(aps, 0.975)),
        ap_lift=ap / out["base_rate"] if out["base_rate"] else np.nan,
        note="",
    )
    try:
        from sklearn.inspection import permutation_importance

        sub = rng.choice(len(te), size=min(len(te), 20000), replace=False)
        pi = permutation_importance(
            m,
            X.loc[te.index].to_numpy(dtype=float)[sub],
            yte[sub],
            scoring="roc_auc",
            n_repeats=3,
            random_state=seed,
        )
        out["importance"] = dict(
            sorted(zip(features, pi.importances_mean.round(4), strict=True), key=lambda kv: -kv[1])[
                :8
            ]
        )
    except ValueError:
        out["importance"] = {}
    return out


def verdict(row: dict) -> str:
    """A plain-language learnability verdict from the out-of-time metrics."""
    if not np.isfinite(row.get("auc", np.nan)):
        return "not evaluable (too few positives)"
    lo = row["auc_lo"]
    if lo <= 0.5:
        return "no evidence of signal"
    if row["auc"] < 0.6 or row["ap_lift"] < 1.5:
        return "weak signal: rules, not models"
    if row["auc"] < 0.7:
        return "moderate signal: a model may help, validate further"
    return "learnable: build and monitor a model"
