# %% [markdown]
# # 03 · The quality gate: schema drift and the circuit breaker
# **Pipeline series** · task group `silver`, part 2: `models/silver/quality`
#
# ## What happens here
# Typing (notebook 02) judges **cells**. This step judges **partitions**: one day of one table. A producer change, such as a
# new core-banking release that writes amounts with a decimal comma or translates a category, does not break
# individual cells at random: it changes a whole day at once. The quality models measure every partition against
# the contract and **hold** the ones whose shape changed, before anything is built on them.
#
# | model | grain | what it computes |
# |---|---|---|
# | `dq_partition_header` | partition | the header each file arrived with: missing, extra, reordered columns |
# | `dq_partition_profile` | partition × column | counts of absent, empty, uncastable, wrong-format, bad-key, unknown, variant and placeholder values; the median magnitude (log10) |
# | `dq_schema_drift` | partition × column × check | each check that fails, with severity A (hold) or B (report) |
# | `dq_partition_releases_active` | partition | holds lifted by an approved four-eyes release |
# | `dq_partition_holds` | partition | severity-A partitions not released: **staging excludes their rows** (macro `not_held`) |
#
# Thresholds (docs/platform/09 §C): format or key problems in more than 0.1 % of the non-empty values; more than 20 %
# unknown vocabulary (A; less is B); median magnitude moved by a factor ≥ 10^0.5 ≈ 3.2 with a robust z above 6; a
# required column more than 0.1 % empty; any column absent from the header; the empty share moved by 30 points or
# more (B).

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
pl.ensure_until("seeds")
QUALITY = [
    "dq_partition_header",
    "dq_partition_profile",
    "dq_schema_drift",
    "dq_partition_releases_active",
    "dq_partition_holds",
]
built = pl.build_set(QUALITY)

# %% [markdown]
# ## 1 · Headers: did any file arrive with a different set of columns?

# %%
hdr = pl.q("""
    select table_name, count(*) as partitions, count(distinct header) as distinct_headers,
           count(*) filter (where len(missing_columns) > 0) as with_missing,
           count(*) filter (where len(extra_columns) > 0) as with_extra,
           count(*) filter (where reordered) as reordered,
           min(partition_date) as first_day, max(partition_date) as last_day
    from {dq_partition_header} group by all order by table_name""")
show(hdr, paging=False)

# %% [markdown]
# Every table has **one header across all its partitions**: no column was added, dropped or reordered in three years.
# Dimensions arrive as one snapshot (one partition); facts as one file a day. `campaign_sends` has 1,083 daily
# partitions instead of 1,097 because sending started on 2023-07-01, two weeks after the other facts. That is not a
# gap.
#
# **What the gate does not check: completeness.** A day with no file at all produces no header row and no profile,
# so nothing fires. In production, add an **expected-partition check** (a calendar of the days each table must
# deliver) so a missing day is an alert rather than a silent hole. That belongs with the landing manifest, which
# knows what should have arrived.

# %% [markdown]
# ## 2 · The profile: one row per partition and column
# The profile reads the **raw text** with the same predicates the typed views use, so the cell rules and the
# partition rules cannot disagree. Pick a table, a column and a measure to see its daily history.

# %%
prof_cols = pl.columns("dq_partition_profile")["column_name"].tolist()
MEASURES = [c for c in prof_cols if c.startswith("n_") and c not in ("n_rows",)] + ["log10_median"]
facts = pl.q("""select table_name, column_name, count(*) as partitions from {dq_partition_profile}
                group by all having count(*) > 1 order by 1, 2""")
w_t = w.Dropdown(
    options=sorted(facts["table_name"].unique()), value="campaign_sends", description="table"
)
w_c = w.Dropdown(description="column")
w_m = w.Dropdown(options=MEASURES, value="n_empty", description="measure")
w_share = w.Checkbox(value=True, description="as share of rows")
out_p = w.Output()


def _pcols(*_):
    w_c.options = facts.loc[facts.table_name == w_t.value, "column_name"].tolist()


def draw_profile(*_):
    with out_p:
        out_p.clear_output()
        if not w_c.value:
            return
        m = w_m.value
        df = pl.q(f"""select partition_date, n_rows, {m} from {{dq_partition_profile}}
                      where table_name = '{w_t.value}' and column_name = '{w_c.value}' order by 1""")
        y = m
        if w_share.value and m != "log10_median":
            df["share"] = df[m] / df["n_rows"]
            y = "share"
        fig = px.line(df, x="partition_date", y=y, title=f"{w_t.value}.{w_c.value} · {m}")
        fig.update_layout(height=320, xaxis_title=None)
        fig.show()


w_t.observe(_pcols, "value")
for wd in (w_c, w_m, w_share):
    wd.observe(draw_profile, "value")
_pcols()
w_c.value = "subject"
draw_profile()
display(w.VBox([w.HBox([w_t, w_c, w_m, w_share]), out_p]))

# %% [markdown]
# ## 3 · What the real data triggers
# All checks that fired, grouped. Severity A would hold a partition; B is reported only.

# %%
drift = pl.q("""
    select table_name, column_name, check_name, severity, count(*) as partitions,
           min(partition_date) as first_day, max(partition_date) as last_day,
           round(min(observed), 3) as min_observed, round(max(observed), 3) as max_observed,
           any_value(detail) as example
    from {dq_schema_drift} group by all order by partitions desc""")
show(drift, paging=False)
display(pl.q("select count(*) as held_partitions from {dq_partition_holds}"))
display(pl.q("select count(*) as releases_in_force from {dq_partition_releases_active}"))

# %% [markdown]
# **No partition is held.** The only reports are 46 severity-B **empty-share** checks on `campaign_sends`: `subject`
# on 17 days and `was_opened` on 29, both "more than 30 points away from the contract's empty share". The next cell
# shows why.

# %%
ch = pl.q("""select send_channel, count(*) as sends,
                    round(100 * avg((subject is null)::int), 1) as subject_empty_pct,
                    round(100 * avg((was_opened is null)::int), 1) as was_opened_empty_pct
             from {typed_campaign_sends} group by 1 order by 2 desc""")
show(ch, paging=False)
daily = pl.q("""
    with p as (select partition_date, n_empty / n_rows as share from {dq_partition_profile}
               where table_name = 'campaign_sends' and column_name = 'subject'),
         d as (select partition_date from {dq_schema_drift}
               where table_name = 'campaign_sends' and column_name = 'subject')
    select p.*, p.partition_date in (select partition_date from d) as reported from p order by 1""")
base = pl.q("""select empty_share from {source_contract_columns}
               where table_name = 'campaign_sends' and column_name = 'subject'""").iloc[0, 0]
fig = go.Figure()
fig.add_hrect(y0=base - 0.3, y1=min(1, base + 0.3), fillcolor="#3987e5", opacity=0.08, line_width=0)
fig.add_hline(y=base, line_dash="dot", annotation_text=f"contract {base:.0%}")
fig.add_trace(
    go.Scatter(
        x=daily.partition_date,
        y=daily.share,
        mode="lines",
        name="daily empty share",
        line=dict(width=1),
    )
)
r = daily[daily.reported]
fig.add_trace(
    go.Scatter(x=r.partition_date, y=r.share, mode="markers", name="B report", marker=dict(size=7))
)
fig.update_layout(
    title="campaign_sends.subject: daily empty share against the contract band (±30 points)",
    height=360,
    yaxis_tickformat=".0%",
    xaxis_title=None,
)
fig.show()

# %% [markdown]
# **The empty share is structural, not drift.** A subject exists only for e-mail (10 % empty there, 100 % for SMS,
# WhatsApp, push and voice); `was_opened` is not tracked for WhatsApp and voice. The daily share of an "optional"
# column therefore follows the **channel mix of the day's campaigns**, and a day dominated by SMS sends crosses the
# ±30-point band without anything having changed at the producer.
#
# **Decision recorded in the contract design (severity B for empty share).** Reporting rather than holding was the
# right call: an empty-share move is a weak signal of a producer change. **Improvement recommended:** make the
# expected empty share **conditional on the applicability column** (subject given `send_channel = 'Email'`,
# `was_opened` given channel in e-mail, SMS, push). Measured within applicable rows, these two columns would be
# about 10 % and 6 % empty every day, and a real change (e-mails arriving without subject) would stand out instead of
# hiding in channel noise. The same pattern applies to resolution fields of complaints (applicable when the status
# is resolved) and to credit fields of products (applicable to credit families).

# %% [markdown]
# ## 4 · What `not_held` removed: typed rows against staged rows
# Staging is the only silver step that drops rows, and only rows of held partitions.

# %%
pairs = []
for t in sorted(n for n in pl.catalog()["node"] if n.startswith("typed_")):
    s = "stg_" + t.removeprefix("typed_")
    pl.ensure(pl.key(s))
    pairs.append({"table": t.removeprefix("typed_"), "typed": pl.rows(t), "staged": pl.rows(s)})
pairs = pd.DataFrame(pairs)
pairs["removed"] = pairs["typed"] - pairs["staged"]
show(pairs, paging=False)

# %% [markdown]
# ## 5 · What-if: inject a producer change and watch the breaker
# The real data holds nothing, so the breaker's value is invisible. The simulator below copies the profile, changes
# the counts of one partition the way a producer change would, and runs **the compiled `dq_schema_drift` and
# `dq_partition_holds` SQL** against the copy. Nothing in the scratch lakehouse changes.
#
# The positive control of phase 3 did the same with real mutated files (docs/platform/evidence/phase3): five
# severe changes were held, a rare new category was only reported.

# %%
DRIFT_SQL = pl.sql("dq_schema_drift")
PROFILE_REL = pl.relation(pl.key("dq_partition_profile"))
MUTATIONS = {
    "decimal comma in a number (format)": ("n_format", None),
    "identifier pattern changed (key)": ("n_key", None),
    "category translated (unknown vocabulary)": ("n_unknown", None),
    "amounts restated ×1000 (scale)": ("log10_median", 3.0),
    "required column left empty": ("n_empty", None),
    "column dropped from the file (absent)": ("n_absent", None),
}


def whatif(
    table: str, day: str, column: str, mutation: str, share: float
) -> tuple[pd.DataFrame, bool]:
    field, shift = MUTATIONS[mutation]
    pl.con.sql(f"CREATE OR REPLACE TEMP TABLE profile_whatif AS SELECT * FROM {PROFILE_REL}")
    where = f"table_name = '{table}' and partition_date = date '{day}' and column_name = '{column}'"
    if field == "log10_median":
        pl.con.sql(f"UPDATE profile_whatif SET log10_median = log10_median + {shift} WHERE {where}")
    else:
        pl.con.sql(f"UPDATE profile_whatif SET {field} = round(n_rows * {share}) WHERE {where}")
    sql = DRIFT_SQL.replace(PROFILE_REL, "temp.main.profile_whatif")
    checks = pl.con.sql(f"""select * exclude (checked_at) from ({sql})
                           where table_name = '{table}' and partition_date = date '{day}'""").df()
    held = (checks["severity"] == "A").any()
    return checks, held


w_tab = w.Dropdown(
    options=["transactions", "digital_events", "complaints", "campaign_sends"], description="table"
)
w_col = w.Dropdown(description="column")
w_mut = w.Dropdown(options=list(MUTATIONS), description="change")
w_sh = w.FloatLogSlider(value=0.05, base=10, min=-4, max=0, step=0.25, description="share of rows")
w_day = w.Text(value="2025-03-13", description="day")
out_w = w.Output()


def _wcols(*_):
    w_col.options = pl.q(f"""select column_name from {{source_contract_columns}}
                            where table_name = '{w_tab.value}' order by ordinal""")[
        "column_name"
    ].tolist()


def draw_whatif(*_):
    with out_w:
        out_w.clear_output()
        if not w_col.value:
            return
        checks, held = whatif(w_tab.value, w_day.value, w_col.value, w_mut.value, w_sh.value)
        n = pl.q(f"""select max(n_rows) as n from {{dq_partition_profile}} where table_name = '{w_tab.value}'
                     and partition_date = date '{w_day.value}'""").iloc[0, 0]
        verdict = (
            (
                f"**HELD**: {int(n):,} rows of {w_tab.value} {w_day.value} stay in bronze and typed silver but "
                "never reach staging, gold, features or serving until a four-eyes release."
            )
            if held
            else (
                "**Not held**: the partition flows on"
                + (" (reported, severity B)." if len(checks) else ".")
            )
        )
        display(Markdown(verdict))
        if len(checks):
            display(checks)


w_tab.observe(_wcols, "value")
for wd in (w_col, w_mut, w_sh, w_day):
    wd.observe(draw_whatif, "value")
_wcols()
w_col.value = "amount"
draw_whatif()
display(w.VBox([w.HBox([w_tab, w_col, w_day]), w.HBox([w_mut, w_sh]), out_w]))

# %% [markdown]
# **The thresholds at work** (try them in the simulator). For one transactions partition and `amount`:

# %%
rows = []
for mut in MUTATIONS:
    for share in (0.0005, 0.002, 0.05, 0.3):
        col = (
            "transaction_type"
            if "vocabulary" in mut
            else ("transaction_id" if "key" in mut else "amount")
        )
        checks, held = whatif("transactions", "2025-03-13", col, mut, share)
        rows.append(
            {
                "change": mut,
                "column": col,
                "share of rows": share,
                "held": held,
                "checks": ", ".join(
                    f"{c}({s})" for c, s in zip(checks.check_name, checks.severity)
                ),
            }
        )
grid = pd.DataFrame(rows)
show(
    grid.pivot_table(
        index=["change", "column"], columns="share of rows", values="held", aggfunc="first"
    ),
    paging=False,
)

# %% [markdown]
# Read the grid as the breaker's sensitivity. Format and key problems hold at **0.2 %** of rows but not at 0.05 %
# (a few malformed values are cell findings, not a producer change). An unknown vocabulary holds only above
# **20 %** (a new rare category is a B report: the phase-3 control with 5 `Kiosk` rows passed). A scale change
# holds whatever the share, because it moves the median. An absent column always holds.
#
# **Why hold instead of fixing.** A held partition is a question for a person ("did the producer change the unit?"),
# not for code. Guessing a fix (divide by 1000? swap the decimal separator?) would put a plausible wrong number into
# gold. Holding keeps every derived table correct but **incomplete**, and incompleteness is visible: the hold is in
# the audit trail, Airflow opens a review, and the four-eyes flow releases it (after a correction, if needed).

# %% [markdown]
# ## Findings and what to do
# 1. **The source never changed shape in three years.** One header per table across 7,671 partitions; no format,
#    key, scale, vocabulary or required-field drift. **0 partitions held**, so staging keeps every typed row.
# 2. **46 severity-B reports, all false alarms of one kind:** empty-share moves on campaign sends caused by the daily
#    channel mix (subjects exist only for e-mail). **Recommendation:** condition empty-share baselines on their
#    applicability column. It is a small change in the contract generator, and it turns this column into a real
#    detector.
# 3. **The breaker is calibrated sensibly** (section 5): it ignores a handful of bad cells, holds a producer change at
#    0.2 % of rows, holds any unit change, and reports rather than holds a rare new category. The cost of a hold is
#    completeness, which is visible; the cost of not holding would be wrong numbers, which are not.
# 4. **Gap: completeness.** A missing daily file triggers nothing. **Recommendation:** an expected-partition check
#    driven by the landing manifest, with severity A for facts (a missing day of transactions would understate
#    every monthly aggregate in gold).
# 5. **Implication for the project:** the breaker is the control that lets the platform run unattended on daily
#    deliveries. Keep its tests (`test_drift_holds.py`) and the phase-3 positive control in CI, and treat a
#    hold as an incident with an owner, never as noise to suppress.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
