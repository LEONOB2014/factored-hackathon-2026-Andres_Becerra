"""Table profiling for the medallion re-analysis.

Exact statistics run in DuckDB over the full table; pandas-only views (info, missingno,
KDEs) use a reproducible sample from `sample()`. `rel` is any relation name the
connection can select from (a view such as `m_transactions`, or a table).

PII columns are profiled by shape and cardinality only, never shown as values.
"""

import math

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

# Personal data: profiled by pattern and cardinality, never displayed.
PII = frozenset(
    {
        "document_number",
        "first_name",
        "last_name",
        "email",
        "mobile_phone",
        "landline_phone",
        "phone",
        "address",
        "ip_address",
        "date_of_birth",
    }
)
# Free text: profiled by length, language and keywords, not as categories.
TEXT = frozenset(
    {
        "full_text",
        "customer_text",
        "agent_text",
        "description",
        "open_comments",
        "resolution",
        "subject",
        "page_url",
        "page_title",
    }
)
# Strings that stand in for a missing value in raw extracts.
PLACEHOLDERS = ("", "n/a", "na", "null", "none", "nan", "-", "?", "undefined")

NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL")
TEMPORAL = ("DATE", "TIMESTAMP", "TIME")


def q(col: str) -> str:
    """Quote an identifier for SQL."""
    return '"' + col.replace('"', '""') + '"'


def kind(name: str, dtype: str) -> str:
    """Analytical role of a column: pii, text, identifier, numeric, boolean, temporal, categorical."""
    dtype = dtype.upper()
    if name in PII:
        return "pii"
    if name in TEXT:
        return "text"
    if name.endswith("_id") or name in ("product_number", "employee_code", "branch_code"):
        return "identifier"
    if dtype == "BOOLEAN":
        return "boolean"
    if dtype.startswith(NUMERIC):
        return "numeric"
    if dtype.startswith(TEMPORAL):
        return "temporal"
    return "categorical"


def columns(con, rel: str) -> pd.DataFrame:
    """column, dtype and analytical kind for every column of `rel`."""
    rows = con.sql(f"describe select * from {rel}").fetchall()
    return pd.DataFrame(
        [(r[0], r[1], kind(r[0], r[1])) for r in rows], columns=["column", "dtype", "kind"]
    )


def cols_of(con, rel: str, *kinds: str) -> list[str]:
    cols = columns(con, rel)
    return cols.loc[cols["kind"].isin(kinds), "column"].tolist()


def overview(con, rel: str) -> pd.DataFrame:
    """Per column: nulls, disguised missing values (blanks, 'N/A'...), approximate distinct count.

    `missing` = nulls + placeholders; `distinct` is HyperLogLog-approximate (exact below ~1k).
    """
    cols = columns(con, rel)
    exprs = ["count(*) as __n"]
    for c, dtype in zip(cols["column"], cols["dtype"]):
        exprs.append(f"count({q(c)}) as {q('nn_' + c)}")
        exprs.append(f"approx_count_distinct({q(c)}) as {q('nd_' + c)}")
        if dtype.upper() == "VARCHAR":
            tokens = ", ".join(f"'{p}'" for p in PLACEHOLDERS)
            exprs.append(f"count_if(lower(trim({q(c)})) in ({tokens})) as {q('ph_' + c)}")
    r = con.sql(f"select {', '.join(exprs)} from {rel}").df().iloc[0]
    n = int(r["__n"])
    out = cols.copy()
    out["non_null"] = [int(r["nn_" + c]) for c in cols["column"]]
    out["nulls"] = n - out["non_null"]
    out["placeholders"] = [int(r.get("ph_" + c, 0)) for c in cols["column"]]
    out["missing"] = out["nulls"] + out["placeholders"]
    out["null_pct"] = 100 * out["nulls"] / max(n, 1)
    out["missing_pct"] = 100 * out["missing"] / max(n, 1)
    out["distinct"] = [min(int(r["nd_" + c]), int(r["nn_" + c])) for c in cols["column"]]
    out["distinct_pct"] = 100 * out["distinct"] / out["non_null"].clip(lower=1)
    out.attrs["rows"] = n
    return out


def pk_check(con, rel: str, pk: str) -> dict:
    """Exact primary-key health: nulls and duplicated keys."""
    r = con.sql(
        f"select count(*) n, count({q(pk)}) nn, count(distinct {q(pk)}) nd from {rel}"
    ).fetchone()
    return {"pk": pk, "rows": r[0], "null_keys": r[0] - r[1], "duplicate_keys": r[1] - r[2]}


def numeric_summary(con, rel: str, cols: list[str] | None = None) -> pd.DataFrame:
    """Exact describe() plus tails, shape and outlier shares for numeric columns."""
    cols = cols if cols is not None else cols_of(con, rel, "numeric")
    rows = []
    for c in cols:
        x = f"{q(c)}::double"
        r = (
            con.sql(
                f"""
            with s as (
                select quantile_cont({x}, 0.25) q1, quantile_cont({x}, 0.75) q3 from {rel}
            )
            select count({x}) count, avg({x}) mean, stddev_samp({x}) std, min({x}) min,
                   quantile_cont({x}, 0.01) p01, any_value(s.q1) p25,
                   quantile_cont({x}, 0.50) p50, any_value(s.q3) p75,
                   quantile_cont({x}, 0.99) p99, max({x}) max,
                   skewness({x}) skew, kurtosis({x}) kurtosis,
                   avg(({x} = 0)::int) zero_share, avg(({x} < 0)::int) negative_share,
                   avg(({x} < s.q1 - 1.5 * (s.q3 - s.q1)
                        or {x} > s.q3 + 1.5 * (s.q3 - s.q1))::int) iqr_outlier_share
            from {rel}, s
            """
            )
            .df()
            .iloc[0]
        )
        rows.append({"column": c, **r.to_dict()})
    return pd.DataFrame(rows).set_index("column") if rows else pd.DataFrame()


def value_counts(con, rel: str, col: str, top: int = 15) -> pd.DataFrame:
    """Exact top-N value counts with share and cumulative share; the tail folds into '(other)'."""
    df = con.sql(
        f"select {q(col)}::varchar as value, count(*) as n from {rel} group by 1 order by n desc"
    ).df()
    df["value"] = df["value"].fillna("(null)")
    total = df["n"].sum()
    head = df.head(top).copy()
    if len(df) > top:
        head = pd.concat(
            [
                head,
                pd.DataFrame({"value": [f"(other {len(df) - top})"], "n": [df["n"][top:].sum()]}),
            ],
            ignore_index=True,
        )
    head["share_pct"] = 100 * head["n"] / max(total, 1)
    head["cum_pct"] = head["share_pct"].cumsum()
    head.attrs["cardinality"] = len(df)
    return head


def pattern_profile(con, rel: str, col: str, top: int = 8) -> pd.DataFrame:
    """Shape of a PII column without its values: letters -> A, digit runs -> 9."""
    shape = f"regexp_replace(regexp_replace({q(col)}::varchar, '[0-9]+', '9', 'g'), '[^\\W\\d_]+', 'A', 'g')"
    df = con.sql(
        f"select {shape} as pattern, count(*) as n, avg(length({q(col)}::varchar)) as avg_len "
        f"from {rel} group by 1 order by n desc limit {int(top)}"
    ).df()
    df["pattern"] = df["pattern"].fillna("(null)")
    return df


def text_lengths(con, rel: str, col: str) -> pd.DataFrame:
    """Character and word counts of a free-text column (exact, full table)."""
    return con.sql(
        f"""select length({q(col)}) chars,
                   len(string_split(trim({q(col)}), ' ')) words
            from {rel} where {q(col)} is not null"""
    ).df()


def sample(con, rel: str, n: int = 200_000, key: str | None = None, seed: int = 42) -> pd.DataFrame:
    """Reproducible sample: the full table when small, else the n rows with the lowest hash(key)."""
    total = con.sql(f"select count(*) from {rel}").fetchone()[0]
    if total <= n:
        return con.sql(f"select * from {rel}").df()
    if key:
        return con.sql(
            f"select * from {rel} order by hash({q(key)}, {int(seed)}) limit {int(n)}"
        ).df()
    return con.sql(
        f"select * from {rel} using sample reservoir({int(n)} rows) repeatable ({int(seed)})"
    ).df()


def binned_hist(con, rel: str, col: str, bins: int = 40, log: bool = False) -> pd.DataFrame:
    """Histogram bins computed in SQL over the full column; `log` bins log10(x) of positive values.

    Returns left, right, n. `attrs['excluded']` counts non-positive values dropped by `log`.
    """
    x = f"{q(col)}::double"
    where = f"{x} is not null" + (f" and {x} > 0" if log else "")
    v = f"log10(case when {x} > 0 then {x} end)" if log else x
    lo, hi, kept, total = con.sql(
        f"select min({v}) filter (where {where}), max({v}) filter (where {where}), "
        f"count(*) filter (where {where}), count({x}) from {rel}"
    ).fetchone()
    if lo is None:
        return pd.DataFrame(columns=["left", "right", "n"])
    width = (hi - lo) / bins if hi > lo else 1.0
    df = con.sql(
        f"""select least(floor(({v} - {lo}) / {width}), {bins - 1})::int b, count(*) n
            from {rel} where {where} group by 1 order by 1"""
    ).df()
    full = pd.DataFrame({"b": range(bins)}).merge(df, on="b", how="left").fillna({"n": 0})
    full["left"] = lo + full["b"] * width
    full["right"] = full["left"] + width
    if log:
        full[["left", "right"]] = 10 ** full[["left", "right"]]
    full.attrs["excluded"] = total - kept
    return full[["left", "right", "n"]].astype({"n": int})


def crosstab(
    con, rel: str, row: str, col: str, top: int = 15, normalize: str | None = None
) -> pd.DataFrame:
    """Exact contingency table of the top categories of two columns.

    normalize: None (counts), 'row', 'column' or 'all' (percentages).
    """
    keep = lambda c: (
        f"(select {q(c)} from {rel} group by 1 order by count(*) desc limit {int(top)})"
    )
    df = con.sql(
        f"""select {q(row)}::varchar r, {q(col)}::varchar c, count(*) n from {rel}
            where {q(row)} in {keep(row)} and {q(col)} in {keep(col)} group by 1, 2"""
    ).df()
    ct = df.pivot_table(index="r", columns="c", values="n", fill_value=0, aggfunc="sum")
    ct.index.name, ct.columns.name = row, col
    if normalize == "row":
        ct = 100 * ct.div(ct.sum(axis=1), axis=0)
    elif normalize == "column":
        ct = 100 * ct.div(ct.sum(axis=0), axis=1)
    elif normalize == "all":
        ct = 100 * ct / ct.values.sum()
    return ct


def cramers_v(x: pd.Series, y: pd.Series) -> float:
    """Bias-corrected Cramér's V (Bergsma 2013) between two categorical series, in [0, 1]."""
    ct = pd.crosstab(x, y)
    if min(ct.shape) < 2:
        return 0.0
    chi2 = chi2_contingency(ct, correction=False)[0]
    n = ct.values.sum()
    r, k = ct.shape
    phi2 = max(0.0, chi2 / n - (k - 1) * (r - 1) / (n - 1))
    rc, kc = r - (r - 1) ** 2 / (n - 1), k - (k - 1) ** 2 / (n - 1)
    denom = min(kc - 1, rc - 1)
    return float(math.sqrt(phi2 / denom)) if denom > 0 else 0.0


def cramers_v_matrix(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Symmetric Cramér's V matrix over categorical columns (nulls kept as their own level)."""
    data = df[cols].astype("string").fillna("(null)")
    m = pd.DataFrame(np.eye(len(cols)), index=cols, columns=cols)
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            m.loc[a, b] = m.loc[b, a] = cramers_v(data[a], data[b])
    return m


def spearman_matrix(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Spearman rank correlation (robust to the heavy tails of money columns)."""
    return df[cols].astype(float).corr(method="spearman")


def time_profile(
    con, rel: str, col: str, grain: str = "day", value: str | None = None, agg: str = "count"
) -> pd.DataFrame:
    """Volume (or sum/avg of `value`) per `grain` of a date or timestamp column."""
    if grain not in ("day", "week", "month", "quarter", "year"):
        raise ValueError(f"unknown grain {grain!r}")
    if agg not in ("count", "sum", "avg"):
        raise ValueError(f"unknown aggregate {agg!r}")
    measure = "count(*)" if agg == "count" or value is None else f"{agg}({q(value)}::double)"
    return con.sql(
        f"""select date_trunc('{grain}', {q(col)})::date as period, {measure} as value
            from {rel} where {q(col)} is not null group by 1 order by 1"""
    ).df()


def weekday_hour(con, rel: str, col: str) -> pd.DataFrame:
    """Event counts by ISO weekday (rows, Mon..Sun) and hour of day (columns)."""
    df = con.sql(
        f"""select isodow({q(col)}) dow, hour({q(col)}) h, count(*) n from {rel}
            where {q(col)} is not null group by 1, 2"""
    ).df()
    grid = df.pivot_table(index="dow", columns="h", values="n", fill_value=0, aggfunc="sum")
    grid = grid.reindex(index=range(1, 8), columns=range(24), fill_value=0)
    grid.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return grid


def safe(df: pd.DataFrame) -> pd.DataFrame:
    """Drop PII and free-text columns before a frame is displayed."""
    return df.drop(columns=[c for c in df.columns if c in PII or c in TEXT])
