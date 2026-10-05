# Product Specification: AI-First Banking Customer Service System

> **Status (2026-10-05): design-time specification.** Written at the start of the hackathon and kept unchanged as
> the record of intent; the project is now **BETA AID** (Banking Evolutionary Transformation and AI Deployment).
> What was built:
> - [`copilot/`](../../copilot/README.md): card support in Spanish and Portuguese. Status, balance and limit,
>   declines, expiry; block, reissue and step-up unblock after confirmation.
> - Cited answers to policy questions.
> - Transaction disputes, fraud, limit changes and complaints are handed to a person with a packet, by policy.
> - Mexico, Colombia and Argentina are in the data. Brazil and Portuguese text are not, so Portuguese is supported
>   and evaluated on team-written phrasings.

## 1. Product Vision
The Factored AI & Data Hackathon 2026 project aims to build an AI-first banking customer service system for the LATAM market (Mexico, Colombia, Argentina, Brazil). The system acts as the primary interface for customer support, specifically focused on **Transaction Disputes & Card Support**. It is designed to autonomously handle complex customer queries, resolve standard issues, and intelligently escalate to human agents with full context when necessary, all while handling regional variations of Spanish and Portuguese.

## 2. User Stories

1. **Customer filing a transaction dispute:** As a customer, I want to dispute a transaction I don't recognize, so that I can recover my funds without waiting on hold for a human agent.
2. **Customer requesting card block/unblock:** As a customer whose card is lost or temporarily misplaced, I want to instantly block or unblock my card securely through the AI assistant to protect my account.
3. **Customer querying transaction status:** As a customer, I want to ask about the status of a recent transfer or payment, so that I know when the recipient will get the funds.
4. **Agent receiving escalation with context:** As a human support agent, I want to receive a concise summary of the AI's conversation with the customer along with relevant data when an issue is escalated, so that I don't have to ask the customer to repeat themselves.
5. **System detecting fraudulent patterns:** As a bank security manager, I want the system to identify potential fraud patterns during customer interactions and automatically flag the account or escalate immediately.
6. **Customer with ambiguous/incomplete request:** As a customer who provides vague information (e.g., "fix my card"), I want the AI to ask clarifying questions to understand my intent before taking action.
7. **Customer attempting unauthorized access:** As a bank compliance officer, I want the system to firmly reject and log any attempts by users to access data for accounts they do not own or perform actions they are not authorized for.
8. **Multilingual interaction (Spanish/Portuguese):** As a customer in Brazil or Argentina, I want to interact with the system naturally using regional slang and local currency context (BRL, ARS, MXN, COP).

## 3. Acceptance Criteria (Mapped to Hackathon Evaluation)

- **AI Engineering (30%)**: The system correctly understands user intent >95% of the time. The LangGraph agent effectively routes between standard flows, ambiguous flows, and escalations.
- **Machine Learning (20%)**: Fraud detection models and intent classification models (served via ONNX) exhibit >90% precision and recall on the test dataset.
- **Data Engineering (20%)**: The data pipeline processes the 19M row dataset cleanly. Real-time customer context is loaded into Neo4j/PostgreSQL within <500ms for agent access.
- **Data Analytics (15%)**: Real-time dashboards (Prometheus/Grafana) track agent resolution rates, escalation metrics, and topic clustering of interactions.
- **Overall Rationale (15%)**: System architecture reflects realistic banking constraints (security, latency, cost).

## 4. System Behavior Requirements

The AI workflow must strictly adhere to the following sequence: **Understand → Decide → Act → Verify → Escalate**

- **Understand:** Extract intent, entities (e.g., dates, amounts), and sentiment from user input. Handle multi-turn context and clarify ambiguities.
- **Decide:** Query databases (PostgreSQL/Neo4j) to fetch user context and validate authorization. Determine if the requested action is permissible.
- **Act:** Execute the transaction, status update, or API call (e.g., blocking a card).
- **Verify:** Confirm with the user that the action resolved their issue and update the system of record.
- **Escalate:** If the user requests a human, intent is unsupported, or a high-risk scenario is detected, gracefully hand off to a human agent with a structured summary.

## 5. Non-Functional Requirements

- **Latency:** Time to first token <1s. Total response time <3s (p50) and <8s (p95) including DB lookups.
- **Cost:** Inference and API usage cost <$0.15 per resolved conversation.
- **Security:**
  - Strict PII masking before logging.
  - Robust prompt injection defenses.
  - Strict authorization checks before any state-changing action.
- **Multilingual Support:** Native handling of ES-MX, ES-CO, ES-AR, and PT-BR, including regional banking terminology and currencies (MXN, COP, ARS, USD).

## 6. Data Contract

The system relies on a dataset comprising ~19M rows across 13 core tables:
- `customers` (150K rows)
- `products` (400K rows)
- `transactions` (5M rows)
- `call_center_interactions` (800K rows)
- `call_transcripts` (200K rows)
- `satisfaction_surveys` (250K rows)
- `digital_events` (10M rows)
- `complaints` (80K rows)
- `campaign_sends` (2M rows)
- `branches` (350 rows)
- `service_agents` (1200 rows)
- `marketing_campaigns` (200 rows)
- `daily_exchange_rates` (3000 rows)

*Note: All data ingestion and transformation must be orchestrated via Airflow and dbt.*

## 7. Evaluation Strategy

The solution will be evaluated against a suite of 50+ diverse test cases (golden dataset).
- **Target Metrics:**
  - **Safe Resolution Rate:** >70% of standard queries resolved without human intervention.
  - **Unsafe Outcome Rate:** <2% (hallucinations, unauthorized actions, bad advice).
  - **Escalation Precision:** >85% (only escalating when truly necessary).
- **Baseline Comparison:** Must outperform a basic prompt-based LLM baseline on all target metrics.

## 8. Deliverables Checklist

- [ ] **Architecture Diagram:** Comprehensive system design.
- [ ] **Data Pipeline (dbt/Airflow):** Code for ETL of the 13 tables.
- [ ] **AI Agent Service (FastAPI/LangGraph):** The core decision engine.
- [ ] **Knowledge Graph / Vector DB:** Populated with user and product data.
- [ ] **Evaluation Report:** Results from the 50+ test cases.
- [ ] **Monitoring Dashboard:** Grafana dashboard for system health and analytics.
- [ ] **Deployment Code:** Dockerfiles and Terraform configurations.

## 9. Risk Register

| Risk | Impact | Likelihood | Mitigation Strategy |
|---|---|---|---|
| 1. Prompt Injection | High | High | Implement input sanitization and strict guardrail prompts. |
| 2. Hallucinated Transactions | High | Medium | Ground all agent responses strictly in database query results. |
| 3. High Latency | Medium | Medium | Optimize database indices; use streaming responses; optimize LLM payload size. |
| 4. Context Window Overflow | Medium | Low | Summarize long conversation histories before passing to the decision node. |
| 5. Unauthorized Data Access | High | Low | Enforce strict RBAC and user-ID matching on all DB queries. |
| 6. Cloud Cost Overruns | Medium | Medium | Implement caching (Redis); use smaller models (e.g., Claude 3 Haiku) for routing. |
| 7. Poor Language Localization | Low | Medium | Provide few-shot examples for regional slang in the system prompt. |
| 8. Database Connection Exhaustion | High | Low | Use connection pooling (PgBouncer) for PostgreSQL. |
| 9. Ambiguous User Intent | Medium | High | Implement robust fallback to clarifying questions before taking action. |
| 10. API Rate Limiting | Low | Low | Implement exponential backoff and retry logic in external API calls. |

## 10. Glossary

- **PII:** Personally Identifiable Information.
- **Escalation:** Transferring a customer from the AI agent to a human representative.
- **LangGraph:** Framework for building stateful, multi-actor applications with LLMs.
- **dbt:** Data Build Tool, used for transforming data in the warehouse.
- **ONNX:** Open Neural Network Exchange, format for representing machine learning models.
- **LATAM:** Latin America region.
- **PGVector:** PostgreSQL extension for vector similarity search.
- **Neo4j:** Graph database management system.
