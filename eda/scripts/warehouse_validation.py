"""Collect validation numbers from the dbt warehouse into reports/tables/warehouse_*.csv.

Run after `cd platform/dbt && uv run dbt build`:  uv run eda/scripts/warehouse_validation.py
"""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]  # eda/
REPO = ROOT.parent
OUT = ROOT / "reports" / "tables"
LAKE = REPO / "data" / "lake"


def connect() -> duckdb.DuckDBPyConnection:
    # staging views read ../../data/lake relative to platform/dbt/, so resolve from there
    import os

    os.chdir(REPO / "platform" / "dbt")
    return duckdb.connect(str(LAKE / "lakehouse.duckdb"), read_only=True)


def main() -> None:
    con = connect()
    q = lambda sql: con.sql(sql).df()  # noqa: E731

    # 1. model inventory: rows per relation
    rels = q("""
        select table_schema as schema, table_name as model
        from information_schema.tables
        where table_schema in ('silver', 'gold', 'features', 'graph', 'knowledge', 'privacy', 'serving', 'audit', 'snapshots')
        order by 1, 2""")
    rels["rows"] = [
        con.sql(f'select count(*) from "{s}"."{m}"').fetchone()[0]
        for s, m in rels.itertuples(index=False)
    ]
    for f in sorted(
        [
            *LAKE.glob("graph/*.parquet"),
            *LAKE.glob("features/*.parquet"),
            *LAKE.glob("knowledge/*.parquet"),
        ]
    ):
        n = con.sql(f"select count(*) from '{f}'").fetchone()[0]
        rels.loc[len(rels)] = [f"lake/{f.parent.name} (parquet)", f.stem, n]
    rels.to_csv(OUT / "warehouse_model_inventory.csv", index=False)

    # 2. data-quality rules and reconciliation (straight from the audit layer)
    q("select * exclude (enforce_in_dev) from audit.dq_rule_summary order by rule_id").to_csv(
        OUT / "warehouse_dq_rule_summary.csv", index=False
    )
    q("select * from audit.audit_backup_reconciliation").to_csv(
        OUT / "warehouse_backup_reconciliation.csv", index=False
    )

    # 3. use-case mart facts quoted in the report
    facts = {}
    one = lambda sql: con.sql(sql).fetchone()[0]  # noqa: E731
    facts["disputes_total"] = one("select count(*) from gold.mart_transaction_disputes")
    facts["disputes_linked_medium_or_better"] = one(
        "select count(*) from gold.mart_transaction_disputes where link_confidence in ('high','medium')"
    )
    facts["disputes_via_regulator_pct"] = one(
        "select 100*avg(came_via_regulator::int) from gold.mart_transaction_disputes"
    )
    facts["disputes_sla_breached_pct"] = one(
        "select 100*avg(sla_breached::int) from gold.mart_transaction_disputes"
    )
    facts["cards_total"] = one("select count(*) from gold.mart_card_support")
    facts["cards_active_but_expired"] = one(
        "select count(*) from gold.mart_card_support where is_active_but_expired"
    )
    facts["credit_eligible_card_pct"] = one(
        "select 100*avg(eligible_credit_card::int) from gold.mart_credit_eligibility"
    )
    facts["credit_eligible_loan_pct"] = one(
        "select 100*avg(eligible_personal_loan::int) from gold.mart_credit_eligibility"
    )
    facts["tx_per_customer_month"] = one(
        "select avg(n_tx) from silver.int_customer_month_tx where month_start >= date '2023-07-01'"
    )
    facts["sends_without_current_consent_pct"] = one(
        "select 100*avg(sent_without_current_consent::int) from gold.mart_campaign_compliance_uplift"
    )
    facts["conv_rate_with_consent_pct"] = one(
        "select 100*avg(outcome_converted::int) from gold.mart_campaign_compliance_uplift where accepts_marketing_current"
    )
    facts["conv_rate_without_consent_pct"] = one(
        "select 100*avg(outcome_converted::int) from gold.mart_campaign_compliance_uplift where not accepts_marketing_current"
    )
    facts["sends_promoting_already_held_product_pct"] = one(
        "select 100*avg(already_held_promoted_product::int) from gold.mart_campaign_compliance_uplift"
    )
    facts["cx_repeat_contact_7d_pct"] = one(
        "select 100*avg(repeat_contact_7d::int) from gold.mart_cx_journey"
    )
    facts["cx_complaint_within_14d_pct"] = one(
        "select 100*avg(complaint_within_14d::int) from gold.mart_cx_journey"
    )
    facts["transcripts_with_placeholders_pct"] = one(
        "select 100*avg(transcript_is_template_artifact::int) from gold.mart_cx_journey where transcript_id is not null"
    )
    facts["aml_customer_months_with_hits"] = one(
        "select count(*) from gold.mart_aml_customer_month where len(typology_hits) > 0"
    )
    facts["shared_ip_nodes"] = one(
        f"select count(*) from '{LAKE}/graph/graph_nodes.parquet' where node_type = 'ip'"
    )
    facts["graph_edges"] = one(f"select count(*) from '{LAKE}/graph/graph_edges.parquet'")
    facts["kumo_complaint90d_rows"] = one(
        f"select count(*) from '{LAKE}/features/ml_kumo_relational_complaint90d.parquet'"
    )
    facts["kumo_complaint90d_positive_pct"] = one(
        f"select 100*avg(label_complaint_90d::int) from '{LAKE}/features/ml_kumo_relational_complaint90d.parquet'"
    )
    pd.Series(facts, name="value").rename_axis("fact").to_csv(OUT / "warehouse_use_case_facts.csv")

    # 4. NBA, eligibility reasons, AML typologies, collections buckets
    q(
        "select next_best_action, count(*) as cards from gold.mart_card_support group by 1 order by 2 desc"
    ).to_csv(OUT / "warehouse_card_next_best_action.csv", index=False)
    q("""select reason, count(*) as customers from
         (select unnest(decline_reasons) as reason from gold.mart_credit_eligibility) group by 1 order by 2 desc""").to_csv(
        OUT / "warehouse_credit_decline_reasons.csv", index=False
    )
    q("""select typology, count(*) as customer_months from
         (select unnest(typology_hits) as typology from gold.mart_aml_customer_month) group by 1 order by 2 desc""").to_csv(
        OUT / "warehouse_aml_typology_hits.csv", index=False
    )
    q("""select dpd_bucket, count(*) as products, round(avg(early_warning_score), 1) as avg_ews
         from gold.mart_collections_early_warning group by 1 order by 1""").to_csv(
        OUT / "warehouse_collections_buckets.csv", index=False
    )

    # 5. fraud: point-in-time behavioural features only (no fraud_score), out-of-time evaluation
    df = con.sql(f"select * from '{LAKE}/features/ml_kumo_tabular_fraud.parquet'").df()
    cat = ["transaction_type", "channel", "transaction_category", "product_family"]
    for c in cat:
        df[c] = df[c].astype("category")
    feats = [
        c
        for c in df.columns
        if c not in ("transaction_id", "split", "label_is_fraud", "sample_weight")
    ]
    X = df[feats].astype({c: "float64" for c in feats if c not in cat})
    y = df["label_is_fraud"].astype(int)
    tr, te = df["split"] == "train", df["split"] == "test"
    clf = HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.05,
        categorical_features="from_dtype",
        class_weight="balanced",
        random_state=0,
    )
    clf.fit(X[tr], y[tr], sample_weight=df.loc[tr, "sample_weight"])
    p = clf.predict_proba(X[te])[:, 1]
    w = df.loc[te, "sample_weight"]
    base_rate = np.average(y[te], weights=w)
    pd.DataFrame(
        [
            {
                "model": "HistGBT on PIT behavioural features (no fraud_score)",
                "train_rows": int(tr.sum()),
                "test_rows": int(te.sum()),
                "test_auc_weighted": roc_auc_score(y[te], p, sample_weight=w),
                "test_ap_weighted": average_precision_score(y[te], p, sample_weight=w),
                "test_base_rate": base_rate,
            }
        ]
    ).to_csv(OUT / "warehouse_fraud_pit_baseline.csv", index=False)

    print(pd.read_csv(OUT / "warehouse_use_case_facts.csv").to_string(index=False))
    print(pd.read_csv(OUT / "warehouse_fraud_pit_baseline.csv").to_string(index=False))


if __name__ == "__main__":
    main()
