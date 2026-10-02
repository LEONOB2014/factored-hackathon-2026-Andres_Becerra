-- ==============================================================================
-- Database Initialization Script
-- Factored AI & Data Hackathon 2026
-- Creates schemas, extensions, and initial database structure
-- ==============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;        -- PGVector for embeddings
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- Trigram similarity for fuzzy search
CREATE EXTENSION IF NOT EXISTS btree_gist;    -- GiST index support

-- ==============================================================================
-- Create separate databases for services
-- ==============================================================================
-- MLflow database
SELECT 'CREATE DATABASE mlflowdb'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflowdb')\gexec

-- Airflow database
SELECT 'CREATE DATABASE airflowdb'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflowdb')\gexec

-- ==============================================================================
-- Schema organization
-- ==============================================================================
CREATE SCHEMA IF NOT EXISTS raw;          -- Bronze layer: raw ingested data
CREATE SCHEMA IF NOT EXISTS clean;        -- Silver layer: cleaned/deduped
CREATE SCHEMA IF NOT EXISTS analytics;    -- Gold layer: business marts
CREATE SCHEMA IF NOT EXISTS ml;           -- ML feature store & predictions
CREATE SCHEMA IF NOT EXISTS agent;        -- Agent state & memory
CREATE SCHEMA IF NOT EXISTS audit;        -- Audit logs & traces

-- ==============================================================================
-- Raw (Bronze) Layer - Dimension Tables
-- ==============================================================================
CREATE TABLE IF NOT EXISTS raw.customers (
    customer_id VARCHAR(20) PRIMARY KEY,
    document_number VARCHAR(20) NOT NULL,
    document_type VARCHAR(10) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(1),
    email VARCHAR(100),
    mobile_phone VARCHAR(20),
    landline_phone VARCHAR(20),
    address VARCHAR(200),
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    country VARCHAR(50) NOT NULL,
    postal_code VARCHAR(10),
    detected_accent VARCHAR(50),
    segment VARCHAR(50) NOT NULL,
    credit_score INTEGER,
    estimated_monthly_income DECIMAL(12,2),
    occupation VARCHAR(100),
    marital_status VARCHAR(20),
    education_level VARCHAR(50),
    registration_date TIMESTAMP NOT NULL,
    registration_branch_id VARCHAR(20) NOT NULL,
    customer_status VARCHAR(20) NOT NULL,
    last_updated TIMESTAMP NOT NULL,
    accepts_marketing BOOLEAN NOT NULL,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.products (
    product_id VARCHAR(20) PRIMARY KEY,
    customer_id VARCHAR(20) NOT NULL,
    product_type VARCHAR(50) NOT NULL,
    product_number VARCHAR(30) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    current_balance DECIMAL(15,2) NOT NULL,
    credit_limit DECIMAL(15,2),
    interest_rate DECIMAL(5,2),
    opening_date DATE NOT NULL,
    expiration_date DATE,
    opening_branch_id VARCHAR(20) NOT NULL,
    product_status VARCHAR(20) NOT NULL,
    opening_channel VARCHAR(30) NOT NULL,
    has_linked_app BOOLEAN NOT NULL,
    days_past_due INTEGER,
    last_transaction_date TIMESTAMP,
    last_updated TIMESTAMP NOT NULL,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.branches (
    branch_id VARCHAR(20) PRIMARY KEY,
    branch_code VARCHAR(10) NOT NULL,
    branch_name VARCHAR(100) NOT NULL,
    branch_type VARCHAR(30) NOT NULL,
    address VARCHAR(200) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    country VARCHAR(50) NOT NULL,
    postal_code VARCHAR(10),
    geographic_zone VARCHAR(50) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    email VARCHAR(100),
    opening_time TIME NOT NULL,
    closing_time TIME NOT NULL,
    has_atms BOOLEAN NOT NULL,
    atm_count INTEGER,
    has_teller_windows BOOLEAN NOT NULL,
    teller_window_count INTEGER,
    latitude DECIMAL(10,7),
    longitude DECIMAL(10,7),
    branch_opening_date DATE NOT NULL,
    branch_status VARCHAR(20) NOT NULL,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.service_agents (
    agent_id VARCHAR(20) PRIMARY KEY,
    employee_code VARCHAR(15) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    native_accent VARCHAR(50) NOT NULL,
    country_of_origin VARCHAR(50) NOT NULL,
    assigned_branch_id VARCHAR(20),
    agent_type VARCHAR(30) NOT NULL,
    experience_level VARCHAR(20) NOT NULL,
    languages VARCHAR(100) NOT NULL,
    specialty VARCHAR(100),
    hire_date DATE NOT NULL,
    avg_csat DECIMAL(3,2),
    total_monthly_interactions INTEGER,
    agent_status VARCHAR(20) NOT NULL,
    work_shift VARCHAR(20) NOT NULL,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.marketing_campaigns (
    campaign_id VARCHAR(20) PRIMARY KEY,
    campaign_name VARCHAR(150) NOT NULL,
    description TEXT,
    campaign_type VARCHAR(50) NOT NULL,
    campaign_objective VARCHAR(100) NOT NULL,
    promoted_product VARCHAR(50),
    target_segment VARCHAR(50),
    target_country VARCHAR(50),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    budget DECIMAL(12,2),
    campaign_status VARCHAR(20) NOT NULL,
    expected_conversion_rate DECIMAL(5,2),
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

-- ==============================================================================
-- Raw (Bronze) Layer - Fact Tables
-- ==============================================================================
CREATE TABLE IF NOT EXISTS raw.transactions (
    transaction_id VARCHAR(30) PRIMARY KEY,
    transaction_date TIMESTAMP NOT NULL,
    process_date DATE NOT NULL,
    product_id VARCHAR(20) NOT NULL,
    customer_id VARCHAR(20) NOT NULL,
    transaction_type VARCHAR(50) NOT NULL,
    transaction_category VARCHAR(50),
    amount DECIMAL(15,2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    amount_usd DECIMAL(15,2),
    channel VARCHAR(30) NOT NULL,
    branch_id VARCHAR(20),
    merchant_name VARCHAR(150),
    merchant_category VARCHAR(50),
    transaction_country VARCHAR(50) NOT NULL,
    transaction_city VARCHAR(100),
    transaction_status VARCHAR(20) NOT NULL,
    response_code VARCHAR(10),
    is_fraud BOOLEAN NOT NULL,
    fraud_score DECIMAL(5,2),
    latitude DECIMAL(10,7),
    longitude DECIMAL(10,7),
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.call_center_interactions (
    interaction_id VARCHAR(30) PRIMARY KEY,
    interaction_date TIMESTAMP NOT NULL,
    process_date DATE NOT NULL,
    customer_id VARCHAR(20) NOT NULL,
    agent_id VARCHAR(20),
    interaction_type VARCHAR(30) NOT NULL,
    channel VARCHAR(30) NOT NULL,
    contact_reason VARCHAR(100) NOT NULL,
    reason_category VARCHAR(50) NOT NULL,
    duration_seconds INTEGER,
    wait_time_seconds INTEGER,
    was_resolved BOOLEAN,
    requires_followup BOOLEAN NOT NULL,
    detected_sentiment VARCHAR(20),
    sentiment_score DECIMAL(3,2),
    customer_detected_accent VARCHAR(50),
    agent_used_accent VARCHAR(50),
    was_escalated BOOLEAN NOT NULL,
    mentioned_products VARCHAR(200),
    has_transcript BOOLEAN NOT NULL,
    has_recording BOOLEAN NOT NULL,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.call_transcripts (
    transcript_id VARCHAR(30) PRIMARY KEY,
    interaction_id VARCHAR(30) NOT NULL,
    process_date DATE NOT NULL,
    customer_id VARCHAR(20) NOT NULL,
    agent_id VARCHAR(20) NOT NULL,
    full_text TEXT NOT NULL,
    customer_text TEXT,
    agent_text TEXT,
    detected_language VARCHAR(10) NOT NULL,
    detected_accent VARCHAR(50),
    accent_confidence DECIMAL(3,2),
    detected_keywords VARCHAR(500),
    mentioned_entities TEXT,
    detected_intents VARCHAR(300),
    main_topics VARCHAR(300),
    transcription_model VARCHAR(50) NOT NULL,
    audio_quality VARCHAR(20),
    duration_seconds INTEGER NOT NULL,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.satisfaction_surveys (
    survey_id VARCHAR(30) PRIMARY KEY,
    survey_date TIMESTAMP NOT NULL,
    process_date DATE NOT NULL,
    interaction_id VARCHAR(30),
    customer_id VARCHAR(20) NOT NULL,
    agent_id VARCHAR(20),
    survey_type VARCHAR(20) NOT NULL,
    send_channel VARCHAR(30) NOT NULL,
    main_score INTEGER NOT NULL,
    nps_category VARCHAR(20),
    question_1_text TEXT,
    question_1_response INTEGER,
    question_2_text TEXT,
    question_2_response INTEGER,
    question_3_text TEXT,
    question_3_response INTEGER,
    open_comments TEXT,
    comment_sentiment VARCHAR(20),
    response_time_hours DECIMAL(8,2),
    campaign_response_rate DECIMAL(5,2),
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.complaints (
    complaint_id VARCHAR(30) PRIMARY KEY,
    creation_date TIMESTAMP NOT NULL,
    process_date DATE NOT NULL,
    customer_id VARCHAR(20) NOT NULL,
    case_type VARCHAR(30) NOT NULL,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100),
    reception_channel VARCHAR(30) NOT NULL,
    affected_product_id VARCHAR(20),
    related_branch_id VARCHAR(20),
    origin_interaction_id VARCHAR(30),
    description TEXT NOT NULL,
    claimed_amount DECIMAL(15,2),
    currency VARCHAR(3),
    priority VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL,
    assigned_agent_id VARCHAR(20),
    assignment_date TIMESTAMP,
    first_response_date TIMESTAMP,
    resolution_date TIMESTAMP,
    closing_date TIMESTAMP,
    sla_breached BOOLEAN NOT NULL,
    resolution_days INTEGER,
    resolution TEXT,
    compensation_granted DECIMAL(15,2),
    resolution_satisfaction INTEGER,
    is_repeat_complainer BOOLEAN NOT NULL,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.digital_events (
    event_id VARCHAR(30) PRIMARY KEY,
    event_date TIMESTAMP NOT NULL,
    process_date DATE NOT NULL,
    customer_id VARCHAR(20),
    session_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_category VARCHAR(50) NOT NULL,
    channel VARCHAR(30) NOT NULL,
    platform VARCHAR(30),
    browser VARCHAR(50),
    app_version VARCHAR(20),
    page_url VARCHAR(300),
    page_title VARCHAR(200),
    action VARCHAR(100),
    element_id VARCHAR(100),
    product_id VARCHAR(20),
    event_value DECIMAL(15,2),
    duration_seconds INTEGER,
    ip_address VARCHAR(45),
    ip_country VARCHAR(50),
    ip_city VARCHAR(100),
    is_mobile BOOLEAN NOT NULL,
    referrer VARCHAR(300),
    utm_source VARCHAR(100),
    utm_medium VARCHAR(100),
    utm_campaign VARCHAR(100),
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.campaign_sends (
    send_id VARCHAR(30) PRIMARY KEY,
    send_date TIMESTAMP NOT NULL,
    process_date DATE NOT NULL,
    campaign_id VARCHAR(20) NOT NULL,
    customer_id VARCHAR(20) NOT NULL,
    send_channel VARCHAR(30) NOT NULL,
    template_used VARCHAR(100),
    subject VARCHAR(200),
    send_status VARCHAR(20) NOT NULL,
    was_delivered BOOLEAN NOT NULL,
    was_opened BOOLEAN,
    open_date TIMESTAMP,
    was_clicked BOOLEAN,
    click_date TIMESTAMP,
    click_count INTEGER,
    had_conversion BOOLEAN NOT NULL,
    conversion_date TIMESTAMP,
    conversion_value DECIMAL(15,2),
    open_device VARCHAR(30),
    open_country VARCHAR(50),
    failure_reason VARCHAR(200),
    send_cost DECIMAL(10,4),
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS raw.daily_exchange_rates (
    date DATE NOT NULL,
    source_currency VARCHAR(3) NOT NULL,
    target_currency VARCHAR(3) NOT NULL,
    exchange_rate DECIMAL(12,6) NOT NULL,
    buy_rate DECIMAL(12,6),
    sell_rate DECIMAL(12,6),
    source VARCHAR(50),
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file VARCHAR(500),
    PRIMARY KEY (date, source_currency, target_currency)
);

-- ==============================================================================
-- Agent Schema - Conversation & Memory
-- ==============================================================================
CREATE TABLE IF NOT EXISTS agent.conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id VARCHAR(20),
    session_id VARCHAR(100) NOT NULL,
    language VARCHAR(10) DEFAULT 'es',
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'active',
    total_turns INTEGER DEFAULT 0,
    was_escalated BOOLEAN DEFAULT FALSE,
    resolution_type VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS agent.messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES agent.conversations(conversation_id),
    role VARCHAR(20) NOT NULL, -- 'user', 'assistant', 'system', 'tool'
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent.tool_calls (
    tool_call_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES agent.conversations(conversation_id),
    message_id UUID REFERENCES agent.messages(message_id),
    tool_name VARCHAR(100) NOT NULL,
    tool_input JSONB NOT NULL,
    tool_output JSONB,
    status VARCHAR(20) DEFAULT 'pending', -- pending, success, error, timeout
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent.escalations (
    escalation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES agent.conversations(conversation_id),
    customer_id VARCHAR(20) NOT NULL,
    reason VARCHAR(200) NOT NULL,
    request_summary TEXT NOT NULL,
    verified_facts JSONB,
    actions_taken JSONB,
    unresolved_questions JSONB,
    recommended_action TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ==============================================================================
-- Audit Schema - Traces & Logs
-- ==============================================================================
CREATE TABLE IF NOT EXISTS audit.request_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID,
    request_type VARCHAR(50),
    customer_id VARCHAR(20),
    action VARCHAR(100),
    input_hash VARCHAR(64),
    output_hash VARCHAR(64),
    latency_ms INTEGER,
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost_usd DECIMAL(10,6),
    model_used VARCHAR(100),
    status VARCHAR(20),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ==============================================================================
-- ML Schema - Predictions & Features
-- ==============================================================================
CREATE TABLE IF NOT EXISTS ml.predictions (
    prediction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50),
    entity_type VARCHAR(50) NOT NULL, -- 'customer', 'transaction', etc.
    entity_id VARCHAR(50) NOT NULL,
    prediction JSONB NOT NULL,
    confidence DECIMAL(5,4),
    features_used JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ==============================================================================
-- Vector Embeddings Table (PGVector)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS agent.document_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    metadata JSONB,
    embedding vector(768),  -- multilingual-e5-large dimension
    doc_type VARCHAR(50),   -- 'policy', 'faq', 'transcript', 'product_doc'
    language VARCHAR(10),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create HNSW index for fast similarity search
CREATE INDEX IF NOT EXISTS idx_document_embeddings_hnsw
    ON agent.document_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ==============================================================================
-- Indexes for performance
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_transactions_customer ON raw.transactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON raw.transactions(process_date);
CREATE INDEX IF NOT EXISTS idx_transactions_fraud ON raw.transactions(is_fraud) WHERE is_fraud = TRUE;
CREATE INDEX IF NOT EXISTS idx_interactions_customer ON raw.call_center_interactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_interactions_date ON raw.call_center_interactions(process_date);
CREATE INDEX IF NOT EXISTS idx_complaints_customer ON raw.complaints(customer_id);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON raw.complaints(status);
CREATE INDEX IF NOT EXISTS idx_transcripts_interaction ON raw.call_transcripts(interaction_id);
CREATE INDEX IF NOT EXISTS idx_digital_events_customer ON raw.digital_events(customer_id);
CREATE INDEX IF NOT EXISTS idx_digital_events_date ON raw.digital_events(process_date);
CREATE INDEX IF NOT EXISTS idx_campaign_sends_customer ON raw.campaign_sends(customer_id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_conversation ON agent.messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_conversation ON agent.tool_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_conversation ON audit.request_logs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_entity ON ml.predictions(entity_type, entity_id);

-- ==============================================================================
-- Grant permissions
-- ==============================================================================
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA raw TO factored;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA clean TO factored;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA analytics TO factored;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA ml TO factored;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA agent TO factored;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA audit TO factored;
GRANT USAGE ON ALL SCHEMAS IN DATABASE bankingdb TO factored;

-- Done!
SELECT 'Database initialization complete!' AS status;
