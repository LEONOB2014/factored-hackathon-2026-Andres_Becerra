# dbt lineage (generated)

_Generated from `platform/dbt/target/manifest.json` (73 models)._

## Zone-level lineage

```mermaid
flowchart LR
  audit["audit<br/>5 nodes"]
  features["features<br/>8 nodes"]
  gold["gold<br/>22 nodes"]
  graph["graph<br/>6 nodes"]
  knowledge["knowledge<br/>2 nodes"]
  privacy["privacy<br/>2 nodes"]
  reference["reference<br/>5 nodes"]
  serving["serving<br/>6 nodes"]
  silver["silver<br/>22 nodes"]
  snapshots["snapshots<br/>4 nodes"]
  source_holdout["source:holdout<br/>2 nodes"]
  source_published["source:published<br/>4 nodes"]
  source_raw["source:raw<br/>13 nodes"]
  source_raw_backup["source:raw_backup<br/>5 nodes"]
  features -->|1| gold
  features -->|1| graph
  gold -->|4| graph
  gold -->|1| knowledge
  gold -->|5| serving
  graph -->|1| knowledge
  reference -->|1| audit
  reference -->|1| gold
  reference -->|1| graph
  reference -->|8| silver
  silver -->|21| audit
  silver -->|10| features
  silver -->|40| gold
  silver -->|22| graph
  silver -->|4| knowledge
  silver -->|4| privacy
  silver -->|1| serving
  silver -->|4| snapshots
  snapshots -->|1| audit
  snapshots -->|2| gold
  source_holdout -->|2| silver
  source_raw -->|11| audit
  source_raw -->|13| silver
  source_raw_backup -->|5| audit
```

## Model-level lineage into `serving`

```mermaid
flowchart LR
  mart_account_payment_inquiry --> serving_account_inquiry
  mart_card_support --> serving_card_support
  mart_credit_eligibility --> serving_credit_eligibility
  mart_customer_360 --> serving_customer_360
  mart_transaction_disputes --> serving_dispute_case
  int_transactions_enriched --> serving_online_fraud_state
```

## Model-level lineage into `features`

```mermaid
flowchart LR
  int_customer_month_tx --> feat_credit_eligibility_pit
  int_products_enriched --> feat_credit_eligibility_pit
  int_customer_profile --> feat_credit_eligibility_pit
  int_transactions_enriched --> feat_fraud_realtime_pit
  stg_digital_events --> feat_fraud_realtime_pit
  stg_digital_events --> feat_fraud_stream_parity
  stg_digital_events_holdout --> feat_fraud_stream_parity
  int_transactions_enriched_with_holdout --> feat_fraud_stream_parity
  feat_fraud_realtime_pit --> ml_fraud_test
  feat_fraud_realtime_pit --> ml_fraud_train
  feat_fraud_realtime_pit --> ml_fraud_valid
  stg_complaints --> ml_kumo_relational_complaint90d
  int_customer_profile --> ml_kumo_relational_complaint90d
  feat_fraud_realtime_pit --> ml_kumo_tabular_fraud
```

## Model-level lineage into `graph`

```mermaid
flowchart LR
  fgl_silo_nodes --> fgl_silo_edges
  int_transactions_enriched --> fgl_silo_edges
  stg_complaints --> fgl_silo_nodes
  int_customer_profile --> fgl_silo_nodes
  int_transactions_enriched --> fgl_silo_nodes
  dim_country --> fgl_silo_nodes
  dim_merchant --> fgl_silo_nodes
  int_products_enriched --> graph_edges
  fct_transaction --> graph_edges
  stg_products --> graph_edges
  stg_call_center_interactions --> graph_edges
  stg_complaints --> graph_edges
  stg_campaign_sends --> graph_edges
  stg_digital_events --> graph_edges
  graph_nodes --> graph_edges
  int_customer_profile --> graph_nodes
  int_products_enriched --> graph_nodes
  int_transactions_enriched --> graph_nodes
  stg_branches --> graph_nodes
  stg_service_agents --> graph_nodes
  stg_marketing_campaigns --> graph_nodes
  country_codes --> graph_nodes
  stg_complaints --> graph_nodes
  stg_digital_events --> graph_nodes
  int_customer_profile --> tgn_node_features
  int_transactions_enriched --> tgn_node_features
  dim_merchant --> tgn_node_features
  int_customer_profile --> tgn_tx_events
  int_transactions_enriched --> tgn_tx_events
  feat_fraud_realtime_pit --> tgn_tx_events
```

## Model-level lineage into `knowledge`

```mermaid
flowchart LR
  mart_customer_360 --> kb_entity_docs
  stg_complaints --> kb_entity_docs
  stg_service_agents --> kb_entity_docs
  stg_marketing_campaigns --> kb_entity_docs
  graph_edges --> kb_entity_triples
  int_transactions_enriched --> kb_entity_triples
```

## Model-level lineage into `privacy`

```mermaid
flowchart LR
  stg_complaints --> privacy_input_complaints_country_month
  int_customer_profile --> privacy_input_complaints_country_month
  int_transactions_enriched --> privacy_input_tx_segment_month
  int_customer_profile --> privacy_input_tx_segment_month
```
