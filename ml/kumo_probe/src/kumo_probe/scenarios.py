"""Two readiness scenarios whose out-of-time split is the gate's quantile cut.

`04 branch` / teller transactions and `05 agent and queue` / handle time.
Names, metrics, benchmarks, materiality and root causes are copied from
`latam_eda.hour_models` so a probe row joins the scorecard on scenario and model.

The branch query adds `customer_id` and `branch_id` to the gate's select list.
Those columns are already the join keys, so the grain and the time quantile
stay the same. `open_fraction` is the label source and is dropped before any
feature table is built.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

FrameFn = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass(frozen=True)
class Related:
    """One dimension table linked from the task rows. The key is an `id` column."""

    name: str
    key: str
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]

    @property
    def columns(self) -> tuple[str, ...]:
        return (self.key, *self.numeric, *self.categorical)


@dataclass(frozen=True)
class Scenario:
    key: str
    scenario: str
    model: str
    task: str  # classification | regression, the sdm task name
    metric: str
    benchmark: str
    material: float
    cause: str
    requirement: str
    time_col: str
    target: str
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    task_ids: tuple[str, ...]
    task_numeric: tuple[str, ...]
    task_categorical: tuple[str, ...]
    related: tuple[Related, ...]
    benchmark_key: str | None
    sql: str
    derive: FrameFn


def _derive_branch(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["outside"] = (out["open_fraction"] == 0).astype(int)
    return out.drop(columns=["open_fraction"])


def _derive_agent(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["aht"] = out["handle_seconds"] / out["contacts"]
    return out


# The gate's branch select, plus the two foreign keys the joins already use.
_BRANCH_SQL = (
    "select t.transaction_id, t.transaction_ts_utc, t.amount_usd, "
    "t.transaction_type, t.transaction_category, t.is_cash, t.customer_id, "
    "t.branch_id, p.segment, p.age_years, b.branch_type, s.open_fraction "
    "from {int_transactions_enriched} t "
    "join {int_customer_profile} p using (customer_id) "
    "join {stg_branches} b using (branch_id) "
    "join {dim_hour} h on h.hour_start = date_trunc('hour', t.transaction_ts_utc) "
    "join {dim_branch_schedule} s on s.branch_id = t.branch_id "
    "and s.iso_weekday = h.delivery_weekday and s.hour_of_day = h.hour_of_day "
    "where t.channel = 'Branch' "
    "order by t.transaction_ts_utc, t.transaction_id"
)

# Identical to hour_models.agent. The fact is already one row per agent-hour.
_AGENT_SQL = (
    "select f.agent_id, f.hour_start, f.contacts, f.handle_seconds, f.in_shift, "
    "f.contact_hour_of_day, d.experience_level, d.agent_type, d.specialty "
    "from {fct_agent_hour} f join {dim_agent} d using (agent_id) "
    "order by f.hour_start, f.agent_id"
)

_BRANCH_REQUIREMENT = (
    "teller sessions tied to the branch schedule (opening days and hours per branch, holiday "
    "closures) and a teller or terminal identifier per transaction"
)
_AGENT_REQUIREMENT = (
    "workforce data: rostered shifts per agent and day, login/logout and state logs (available, "
    "on break, in call), so occupancy and adherence can be measured"
)

BRANCH = Scenario(
    key="branch_teller",
    scenario="04 branch",
    model="teller transaction outside opening hours",
    task="classification",
    metric="AUC",
    benchmark="base rate",
    material=0.02,
    cause="data defect",
    requirement=_BRANCH_REQUIREMENT,
    time_col="transaction_ts_utc",
    target="outside",
    numeric=("amount_usd", "age_years", "is_cash"),
    categorical=("transaction_type", "transaction_category", "segment", "branch_type"),
    task_ids=("transaction_id", "customer_id", "branch_id"),
    task_numeric=("amount_usd", "is_cash"),
    task_categorical=("transaction_type", "transaction_category"),
    related=(
        Related("customers", "customer_id", ("age_years",), ("segment",)),
        Related("branches", "branch_id", (), ("branch_type",)),
    ),
    benchmark_key=None,
    sql=_BRANCH_SQL,
    derive=_derive_branch,
)

AGENT = Scenario(
    key="agent_handle",
    scenario="05 agent and queue",
    model="handle time per agent-hour",
    task="regression",
    metric="MAE (s)",
    benchmark="agent's own mean",
    material=0.02,
    cause="missing field",
    requirement=_AGENT_REQUIREMENT,
    time_col="hour_start",
    target="aht",
    numeric=("contacts", "in_shift", "contact_hour_of_day"),
    categorical=("experience_level", "agent_type", "specialty"),
    task_ids=("agent_id",),
    task_numeric=("contacts", "in_shift", "contact_hour_of_day"),
    task_categorical=(),
    related=(Related("agents", "agent_id", (), ("experience_level", "agent_type", "specialty")),),
    benchmark_key="agent_id",
    sql=_AGENT_SQL,
    derive=_derive_agent,
)

SCENARIOS: tuple[Scenario, ...] = (BRANCH, AGENT)


def by_key(key: str) -> Scenario:
    for spec in SCENARIOS:
        if spec.key == key:
            return spec
    raise KeyError(key)
