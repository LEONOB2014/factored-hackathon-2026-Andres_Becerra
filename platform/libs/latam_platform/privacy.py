"""Differentially private releases with an immutable privacy-budget ledger.

Scope (ADR-009): DP protects aggregate outputs that leave a trust boundary (cross-country analytics,
external or regulator-facing statistics, dashboards for third parties, synthetic dev data). It is NOT used
for operational decisions (fraud, AML, credit) or for statutory reports that legally require exact values.

Mechanism for a counting release:
  * the group keys come from PUBLIC domains (countries x months x categories), never from the data, so the
    existence of a group is not itself a leak;
  * each person contributes at most `max_per_group` to a group (bounded in dbt: privacy_input_*) and to at
    most `max_groups` groups (bounded here) -> L1 sensitivity = max_per_group * max_groups;
  * OpenDP's discrete Laplace measurement adds noise; epsilon is taken from OpenDP's privacy map, not
    from a hand formula, and is debited from audit.privacy.budget_ledger before anything is released;
  * suppression of small noisy counts is post-processing and costs no budget.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product

import pandas as pd


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Release:
    name: str
    dataset: str
    epsilon: float
    table: pd.DataFrame


def _bound_groups(
    df: pd.DataFrame, unit: str, group_cols: list[str], max_groups: int, seed: str
) -> pd.DataFrame:
    """Keep at most `max_groups` groups per privacy unit, chosen by a keyed hash (deterministic, data-independent)."""
    key = df[group_cols].astype(str).agg("|".join, axis=1)
    df = df.assign(
        _rank_key=[
            hashlib.sha256(f"{seed}|{u}|{k}".encode()).hexdigest() for u, k in zip(df[unit], key)
        ]
    )
    df = df.sort_values([unit, "_rank_key"])
    return df[df.groupby(unit).cumcount() < max_groups].drop(columns="_rank_key")


def debit_budget(
    conn,
    release_name: str,
    dataset: str,
    epsilon: float,
    delta: float,
    mechanism: str,
    requested_by: str,
) -> None:
    row = conn.execute(
        "SELECT epsilon_remaining, delta_remaining FROM privacy.budget_remaining WHERE dataset = %s",
        (dataset,),
    ).fetchone()
    approved = row is not None and epsilon <= row[0] + 1e-12 and delta <= row[1] + 1e-15
    reason = (
        None
        if approved
        else (
            "no budget policy" if row is None else f"remaining epsilon {row[0]:.4f} < {epsilon:.4f}"
        )
    )
    conn.execute(
        "INSERT INTO privacy.budget_ledger (release_name, dataset, epsilon, delta, mechanism, requested_by, approved, reason,"
        " spent_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            release_name,
            dataset,
            epsilon,
            delta,
            mechanism,
            requested_by,
            approved,
            reason,
            datetime.now(UTC),
        ),
    )
    if not approved:
        raise BudgetExceeded(f"{release_name}: {reason}")


def dp_count_release(
    contributions: pd.DataFrame,
    *,
    unit: str,
    group_cols: list[str],
    public_domains: dict[str, list],
    epsilon: float,
    max_per_group: int,
    max_groups: int,
    release_name: str,
    dataset: str,
    ledger_conn,
    requested_by: str,
    suppress_below: int = 10,
    seed: str = "dp-v1",
) -> Release:
    """`contributions` has one row per (unit, group) with a bounded `contribution` column (<= max_per_group)."""
    import opendp.prelude as dp

    dp.enable_features("contrib")

    if (contributions["contribution"] > max_per_group).any():
        raise ValueError(
            "contributions exceed max_per_group: bound them upstream (dbt privacy_input_*)"
        )
    bounded = _bound_groups(contributions, unit, group_cols, max_groups, seed)
    sensitivity = max_per_group * max_groups
    space = (dp.vector_domain(dp.atom_domain(T=int)), dp.l1_distance(T=int))
    scale = sensitivity / epsilon
    meas = dp.m.make_laplace(*space, scale=scale)
    eps_used = meas.map(d_in=sensitivity)  # OpenDP's own accounting

    debit_budget(
        ledger_conn,
        release_name,
        dataset,
        eps_used,
        0.0,
        f"discrete_laplace(scale={scale:.3f})",
        requested_by,
    )

    keys = pd.DataFrame(list(product(*public_domains.values())), columns=list(public_domains))
    true = bounded.groupby(group_cols, as_index=False)["contribution"].sum()
    grid = keys.merge(true, on=group_cols, how="left").fillna({"contribution": 0})
    grid["dp_count"] = meas(grid["contribution"].astype(int).tolist())
    grid["dp_count"] = grid["dp_count"].clip(lower=0)
    grid["suppressed"] = grid["dp_count"] < suppress_below
    grid.loc[grid["suppressed"], "dp_count"] = None
    out = grid.drop(columns="contribution").assign(
        epsilon=eps_used, released_at=datetime.now(UTC).isoformat()
    )
    return Release(release_name, dataset, eps_used, out)


def ensure_budget_policy(
    conn, dataset: str, epsilon_total: float, delta_total: float, period: str
) -> None:
    conn.execute(
        "INSERT INTO privacy.budget_policy (dataset, epsilon_total, delta_total, period) VALUES (%s,%s,%s,%s)"
        " ON CONFLICT (dataset) DO NOTHING",
        (dataset, epsilon_total, delta_total, period),
    )


def release_manifest(rel: Release) -> str:
    return json.dumps(
        {
            "release": rel.name,
            "dataset": rel.dataset,
            "epsilon": rel.epsilon,
            "rows": len(rel.table),
        }
    )
