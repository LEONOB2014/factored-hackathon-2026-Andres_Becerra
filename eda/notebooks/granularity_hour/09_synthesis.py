# %% [markdown]
# # 09 · Synthesis: the bank at the hour
# **Granularity series III · the bank at the hour** · reads the tables written by notebooks 01–08
#
# **What this notebook does.** Corrects every hypothesis test of the series together (Benjamini–Hochberg at a 5 %
# false-discovery rate), collects the readiness gates of notebook 08, and turns both into the KPI catalogue of the hour
# grain, the promotion decision for each hour model, and the downstream implications for contracts, dbt, streaming,
# ML and agents.

# %%
import sys
from pathlib import Path

sys.path.insert(0, "../../src")
import numpy as np
import pandas as pd
from IPython.display import Markdown, display
from itables import show

from latam_eda import granularity as g
from latam_eda import theme

theme.register()
OUT = Path("../../reports/tables")
TESTS = [
    "customer_profile",
    "channel_hour",
    "branch_hours",
    "agent_shift",
    "case_clock",
    "session_funnel",
    "send_delay",
]
checks = pd.read_csv(OUT / "granularity_hour_checks.csv")
sparsity = pd.read_csv(OUT / "granularity_hour_sparsity.csv")
ready = pd.read_csv(OUT / "granularity_hour_readiness.csv")

# %% [markdown]
# ## 1 · Every test of the series, under false-discovery control
# "Material" uses the effect sizes of each test: Cohen's w or Cramér's V of at least 0.1, a share differing by at least
# 5 points, a κ above 0.9, or a correlation above 0.5. With millions of rows a negligible effect is significant; only
# significant **and** material findings are signal.

# %%
sig = pd.concat([pd.read_csv(OUT / f"granularity_hour_{t}.csv") for t in TESTS], ignore_index=True)
sig["reject"], sig["q_value"] = g.bh_fdr(sig.p_value.fillna(1).to_numpy())
sig["material"] = sig.effect.abs().fillna(0) >= np.where(
    sig.test.str.contains("κ"),
    0.9,
    np.where(sig.test.str.contains("outside hours|inside their shift"), 0.05, 0.1),
)
sig["signal"] = sig.reject & sig.material
sig = sig.sort_values(
    ["signal", "reject", "q_value", "scenario", "test"],
    ascending=[False, False, True, True, True],
    kind="stable",
)
sig.to_csv(OUT / "granularity_hour_signal.csv", index=False)
show(
    sig[
        [
            "scenario",
            "test",
            "statistic",
            "effect",
            "p_value",
            "q_value",
            "reject",
            "material",
            "signal",
            "reading",
        ]
    ].round(5),
    paging=False,
)
surv = sig[sig.signal]
display(
    Markdown(
        f"**{int(sig.reject.sum())} of {len(sig)} tests survive the false-discovery correction; {len(surv)} are also "
        "material**"
        + (
            ": " + "; ".join(f"{r['test']} ({r['reading']})" for _, r in surv.iterrows()) + "."
            if len(surv)
            else "."
        )
        + " The significant-but-immaterial ones are effects so small that only the volume detects them (for example "
        "the weekend dip showing up in the Monday-to-Friday reading of branch hours). Everything behavioural at the "
        "hour (customer habits, channel rhythms, shift work, arrival-time effects on complaints, event order, send "
        "time) is absent from this source."
    )
)

# %% [markdown]
# ## 2 · The readiness gates

# %%
show(
    ready[
        [
            "scenario",
            "model",
            "metric",
            "value",
            "benchmark_value",
            "delta",
            "delta_lo",
            "delta_hi",
            "verdict",
            "root_cause",
        ]
    ].round(4),
    paging=False,
)
vc = ready.verdict.value_counts()
display(
    Markdown(
        f"**{len(ready)} hour-grain models: {vc.get('green', 0)} green, {vc.get('amber', 0)} amber, {vc.get('red', 0)} "
        "red.** The red ones are the specification of the data collection audit (notebook 08 and strategy chapter 13)."
    )
)

# %% [markdown]
# ## 3 · KPIs of the hour grain

# %%
kpis = pd.DataFrame(
    [
        (
            "delivery-day conformance",
            "share of rows whose timestamp + declared offset = process_date",
            "process × day",
            "data platform",
            "≥ 99.5 %",
            "deterministic",
        ),
        (
            "clock drift",
            "best shift of the hour × weekday scan per process and month",
            "process × month",
            "data platform",
            "equal to the declared offset",
            "deterministic",
        ),
        (
            "teller transactions outside schedule",
            "teller transactions in hours the branch is closed / teller transactions",
            "branch × day",
            "branch operations",
            "≈ 0 % (today 59 %)",
            "deterministic",
        ),
        (
            "shift adherence",
            "contacts inside the agent's rostered hours / contacts",
            "agent × day",
            "workforce management",
            "≥ 95 % (today 33 %)",
            "deterministic, needs rosters",
        ),
        (
            "occupancy",
            "handle time / logged-in time per interval",
            "agent × hour",
            "workforce management",
            "75–85 %",
            "needs agent state logs",
        ),
        (
            "required vs rostered agents",
            "Erlang C agents for the interval's arrivals minus rostered agents",
            "queue × hour",
            "workforce management",
            "≥ 0 in every interval",
            "deterministic, needs rosters",
        ),
        (
            "hourly volume alert rate",
            "channel-hours outside Poisson (small) or negative-binomial (large) limits",
            "market × channel × hour",
            "operations",
            "≈ 0.1 %",
            "deterministic",
        ),
        (
            "time to first response (business hours)",
            "Kaplan–Meier median of business hours to first response",
            "country × case type × week",
            "complaints, compliance",
            "within the regulatory deadline",
            "deterministic",
        ),
        (
            "regulatory breach rate",
            "cases past their country's business-day deadline, recomputed from the clock",
            "country × case type × month",
            "compliance",
            "0 %",
            "deterministic",
        ),
        (
            "send-to-open delay",
            "median hours from send to open, tracked channels",
            "campaign × channel",
            "marketing technology",
            "monitor",
            "deterministic",
        ),
        (
            "model readiness",
            "share of hour models with a green gate",
            "series × quarter",
            "data office",
            "rises as audit items land",
            "this series",
        ),
    ],
    columns=["KPI", "definition", "grain", "owner", "target", "kind"],
)
kpis.to_csv(OUT / "granularity_hour_kpis.csv", index=False)
show(kpis, paging=False)

# %% [markdown]
# ## 4 · What to promote

# %%
promo = pd.DataFrame(
    [
        (
            "dim_time_of_day, dim_process_clock",
            "promote (P0 with ADR-014)",
            "the declared clocks as data; every intraday fact needs them",
        ),
        (
            "dim_branch_schedule",
            "promote, with collected opening days",
            "the coverage dimension behind the teller-hours rule",
        ),
        (
            "dim_agent_shift",
            "promote when rosters exist",
            "today it encodes an assumed roster; real rosters replace it",
        ),
        (
            "fct_case_clock",
            "promote",
            "the regulatory deadline KPI is deterministic and reportable",
        ),
        (
            "fct_channel_hour, fct_contact_queue_hour",
            "streaming only",
            "monitors per hour; no hourly fact table in the warehouse",
        ),
        (
            "fct_branch_hour",
            "promote as a control input",
            "teller-outside-hours rule; ATM cash stays daily",
        ),
        (
            "fct_agent_hour",
            "internal, when rosters exist",
            "adherence and occupancy are employee data and need rosters",
        ),
        (
            "fct_session",
            "promote (replaces the gold session date)",
            "on the delivery clock; the session is the digital analytics grain",
        ),
        (
            "fct_send_response",
            "promote",
            "response delays per send; send-time models wait for randomised send times",
        ),
        (
            "fct_customer_daypart",
            "keep in the lab",
            "no customer has habits here; re-test on real data",
        ),
        (
            "every hour-grain model",
            "do not deploy",
            "0 green gates; re-run scripts/readiness_check.py as audit items land",
        ),
    ],
    columns=["model", "decision", "why"],
)
promo.to_csv(OUT / "granularity_hour_promotion.csv", index=False)
show(promo, paging=False)

# %% [markdown]
# ## 5 · Downstream implications
# | layer | change | from |
# |---|---|---|
# | source contract | declare clock and delivery window per timestamp (ADR-014); branch opening days and hours; rostered shifts; queue and agent-state events; ATM terminal events; clickstream order with page and product; randomised send times | notebooks 01–08 |
# | silver / integrity | new rule: teller transaction outside the declared schedule (severity B); shift-adherence check once rosters land | 04, 05 |
# | gold | `fct_digital_session` dated by the delivery day, not the UTC day; `fct_case_clock` with business hours and the deadline seed per country and case type | 06, 07 |
# | streaming | hourly monitors per market × channel: Poisson limits for small channels, negative-binomial for market totals | 03, series II |
# | ML | no hour-grain model; the readiness scorecard re-runs on each new source; a green gate opens the ADR-012 path (model card, benchmark, monitoring) | 08 |
# | agents | a compliance agent can answer "which cases are near their regulatory deadline" deterministically from `fct_case_clock`; no intraday triggers or send-time recommendations | 06, 07 |
#
# ### Recommendation
# Promote the **clock and schedule dimensions** and the **case clock** now: they are deterministic, testable, and serve
# regulatory reporting. Keep hourly volumes in the **streaming layer**. Treat every hour-grain model as **blocked by the
# data collection audit**, not by method: the scorecard says what each one needs, and the re-run command says when it
# arrived.
