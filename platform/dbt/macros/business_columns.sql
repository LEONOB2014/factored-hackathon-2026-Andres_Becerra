{# Business columns that define "the same record" for change detection (SCD2 snapshots, audit
   reconciliation). Audit/technical stamps such as last_updated are deliberately excluded:
   they are unreliable in this dataset (rules R06/R07) and must not drive change detection. #}

{% macro cols_customers() %}
  {{ return(['document_type', 'document_number', 'first_name', 'last_name', 'date_of_birth', 'gender', 'email',
             'mobile_phone', 'address', 'city', 'state', 'country', 'segment', 'credit_score',
             'estimated_monthly_income', 'occupation', 'marital_status', 'education_level', 'registration_date',
             'registration_branch_id', 'customer_status', 'accepts_marketing']) }}
{% endmacro %}

{% macro cols_products() %}
  {{ return(['customer_id', 'product_type', 'product_number', 'currency', 'current_balance', 'credit_limit',
             'interest_rate', 'opening_date', 'expiration_date', 'opening_branch_id', 'product_status',
             'opening_channel', 'has_linked_app', 'days_past_due']) }}
{% endmacro %}

{% macro cols_transactions() %}
  {{ return(['transaction_date', 'product_id', 'customer_id', 'transaction_type', 'transaction_category', 'amount',
             'currency', 'amount_usd', 'channel', 'branch_id', 'merchant_name', 'merchant_category',
             'transaction_country', 'transaction_city', 'transaction_status', 'response_code', 'is_fraud',
             'fraud_score', 'latitude', 'longitude']) }}
{% endmacro %}

{% macro cols_complaints() %}
  {{ return(['creation_date', 'customer_id', 'case_type', 'category', 'subcategory', 'reception_channel',
             'affected_product_id', 'related_branch_id', 'origin_interaction_id', 'claimed_amount', 'currency',
             'priority', 'status', 'assigned_agent_id', 'resolution_date', 'sla_breached', 'compensation_granted']) }}
{% endmacro %}

{% macro cols_call_center_interactions() %}
  {{ return(['interaction_date', 'customer_id', 'agent_id', 'interaction_type', 'channel', 'contact_reason',
             'duration_seconds', 'wait_time_seconds', 'was_resolved', 'was_escalated', 'detected_sentiment',
             'sentiment_score', 'has_transcript', 'has_recording']) }}
{% endmacro %}

{% macro cols_service_agents() %}
  {{ return(['employee_code', 'first_name', 'last_name', 'email', 'assigned_branch_id', 'agent_type',
             'experience_level', 'languages', 'specialty', 'agent_status', 'work_shift']) }}
{% endmacro %}

{% macro cols_branches() %}
  {{ return(['branch_code', 'branch_name', 'branch_type', 'address', 'city', 'state', 'country', 'has_atms',
             'atm_count', 'teller_window_count', 'latitude', 'longitude', 'branch_status']) }}
{% endmacro %}
