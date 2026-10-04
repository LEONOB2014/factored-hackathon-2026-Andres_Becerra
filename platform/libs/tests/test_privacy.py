"""DP release: epsilon is debited before release, over-budget releases are refused, groups come from public keys."""

import pandas as pd
import psycopg
import pytest

from latam_platform import privacy


def _contrib(n_customers=400):
    rows = []
    for c in range(n_customers):
        for m in ("2026-01", "2026-02", "2026-03"):
            rows.append(
                {
                    "customer_id": f"c{c}",
                    "country_code": ["MX", "CO", "AR"][c % 3],
                    "year_month": m,
                    "contribution": 1 + (c % 3),
                }
            )
    return pd.DataFrame(rows)


def test_release_debits_budget_and_refuses_overspend(audit_db):
    domains = {
        "country_code": ["MX", "CO", "AR", "BR"],
        "year_month": ["2026-01", "2026-02", "2026-03"],
    }
    with psycopg.connect(audit_db["writer"], autocommit=True) as c:
        privacy.ensure_budget_policy(
            c, "complaints_test", epsilon_total=1.0, delta_total=0.0, period="year"
        )
        rel = privacy.dp_count_release(
            _contrib(),
            unit="customer_id",
            group_cols=["country_code", "year_month"],
            public_domains=domains,
            epsilon=0.6,
            max_per_group=3,
            max_groups=2,
            release_name="r1",
            dataset="complaints_test",
            ledger_conn=c,
            requested_by="test",
        )
        assert len(rel.table) == 12  # every public key, including BR with no data
        # empty public groups are noised like any other (hiding whether a group exists); suppressed cells carry no value
        assert rel.table.loc[rel.table.suppressed, "dp_count"].isna().all()
        assert rel.epsilon == pytest.approx(0.6)
        with pytest.raises(privacy.BudgetExceeded):
            privacy.dp_count_release(
                _contrib(),
                unit="customer_id",
                group_cols=["country_code", "year_month"],
                public_domains=domains,
                epsilon=0.6,
                max_per_group=3,
                max_groups=2,
                release_name="r2",
                dataset="complaints_test",
                ledger_conn=c,
                requested_by="test",
            )
        ledger = c.execute(
            "SELECT release_name, approved FROM privacy.budget_ledger ORDER BY spent_at"
        ).fetchall()
    assert ledger == [("r1", True), ("r2", False)]


def test_unbounded_contributions_are_rejected(audit_db):
    df = _contrib().assign(contribution=99)
    with psycopg.connect(audit_db["writer"], autocommit=True) as c:
        with pytest.raises(ValueError):
            privacy.dp_count_release(
                df,
                unit="customer_id",
                group_cols=["country_code"],
                public_domains={"country_code": ["MX"]},
                epsilon=0.5,
                max_per_group=3,
                max_groups=1,
                release_name="r3",
                dataset="x",
                ledger_conn=c,
                requested_by="test",
            )
