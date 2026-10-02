# Factored Datathon 2026: Machine Learning Specification

## 1. Overview
This specification governs all machine learning and predictive modeling for the Factored Datathon 2026 project. The project provides an AI-first banking customer service system for LATAM (Mexico, Colombia, Argentina).

**Dataset Context:**
* 19M rows across 13 tables in PostgreSQL.
* Language: Spanish data with regional accents (Mexican, Colombian, Argentine) + Portuguese.
* Key Tables:
  * `transactions`: 5M rows (features `is_fraud`, `fraud_score`)
  * `call_transcripts`: 200K rows (features `full_text`, `detected_intents`, `detected_keywords`, `main_topics`)
  * `satisfaction_surveys`: 250K rows (features `main_score`, `nps_category`, `comment_sentiment`)
  * `complaints`: 80K rows (features `case_type`, `category`, `priority`, `resolution`)
  * `customers`: 150K rows (features `segment`, `credit_score`, `customer_status`)

All ML development must adhere to the CRISP-DM methodology: Business Understanding, Data Understanding, Data Preparation, Modeling, Evaluation, and Deployment.

---

## 2. Model Specifications

### 2.1 Intent Classifier (P0)
* **Purpose:** Route customer requests to the correct agent.
* **Data Sources:** `call_transcripts.full_text` + `call_center_interactions.contact_reason` + `reason_category`
* **Labels:** Map `contact_reason` to target intents: `dispute`, `card_support`, `account_inquiry`, `credit_info`, `complaint`, `general`.
* **Model:** Fine-tune `XLM-RoBERTa-base` on Spanish transcripts.
* **Baseline:** TF-IDF + Logistic Regression.
* **Evaluation Metrics:** Macro F1 > 0.85, per-class Precision/Recall.
* **Serving:** Export to ONNX Runtime, inference latency < 10ms.

### 2.2 Fraud Detection Model (P0)
* **Purpose:** Real-time transaction risk scoring.
* **Data Sources:** `transactions` (5M rows) with `is_fraud` label, enriched with `customers` and product features.
* **Features:** Amount, time-of-day, merchant_category, geo-distance from home, velocity (txn count in last 1h/24h), channel.
* **Model:** XGBoost with SHAP interpretability.
* **Handling Class Imbalance:** Use SMOTE or XGBoost `class_weight` / `scale_pos_weight`.
* **Baseline:** Rule-based heuristics (amount threshold + geo).
* **Evaluation Metrics:** AUC-ROC > 0.95, Precision @ 95% Recall, F1 Score.
* **Serving:** MLflow Model Serving, inference latency < 50ms.

### 2.3 Sentiment Analysis Model (P1)
* **Purpose:** Detect customer emotion in real-time.
* **Data Sources:** `call_transcripts.customer_text` + `satisfaction_surveys.open_comments` + `complaints.description`.
* **Labels:** Map `satisfaction_surveys.main_score` to sentiment (1-2=Negative, 3=Neutral, 4-5=Positive) or utilize existing `comment_sentiment`.
* **Model:** Fine-tune `pysentimiento/robertuito-sentiment-analysis` (Spanish-native BERT).
* **Baseline:** VADER with Spanish translation.
* **Evaluation Metrics:** Macro F1 > 0.80.
* **Serving:** Export to ONNX, inference latency < 15ms.

### 2.4 Dispute Resolution Predictor (P1)
* **Purpose:** Predict dispute outcome and recommend optimal resolution path.
* **Data Sources:** `complaints` (80K) with `status`, `resolution_days`, `resolution_satisfaction`.
* **Features:** `case_type`, `category`, `claimed_amount`, `priority`, `is_repeat_complainer`, `customer_segment`, `product_type`.
* **Target:** Multi-class (`Resolved`, `Escalated`, `Rejected`).
* **Model:** LightGBM with Optuna for hyperparameter tuning.
* **Baseline:** Majority class prediction.
* **Evaluation Metrics:** Weighted F1 > 0.75, calibrated prediction probabilities.
* **Serving:** API endpoint.

### 2.5 Churn Prediction (P2)
* **Purpose:** Identify at-risk customers for proactive retention.
* **Data Sources:** Customer activity features aggregated from `transactions`, `digital_events`, `complaints`.
* **Features:** Days since last txn, complaint count, satisfaction trend, product count, balance trend.
* **Target:** Binary classification (`churned` = `customer_status` changed to Inactive/Closed).
* **Model:** XGBoost + SHAP interpretability.
* **Evaluation Metrics:** AUC-ROC, Recall @ Top K.
* **Serving:** Batch inference (nightly Airflow DAG).

### 2.6 Prompt Injection Detector (P1)
* **Purpose:** Provide a safety guardrail for agent input against injection attacks.
* **Data Sources:** Synthetic injection examples + clean banking queries.
* **Model:** Fine-tuned `DistilBERT` binary classifier.
* **Evaluation Metrics:** Recall > 0.95 (crucial to catch injections), False Positive Rate (FPR) < 5%.
* **Serving:** Export to ONNX, inline inference latency < 5ms.

---

## 3. General ML Requirements (Applies to ALL models)

### 3.1 Data Splitting & Validation
* **Split Strategy:** 80% Train, 10% Validation, 10% Test.
* **Method:** Stratified sampling by target class. For time-series data (e.g., fraud, churn), strict **temporal splitting** must be used (train on past, validate/test on future) to avoid data leakage.

### 3.2 Leakage Prevention Checklist
* [ ] Verify that no target-derived features are present in the training set.
* [ ] Ensure temporal features are split correctly (no future information in the past).
* [ ] Standardize/Scale features using parameters fit ONLY on the training set.
* [ ] Handle missing values using statistics computed ONLY on the training set.

### 3.3 Hyperparameter Tuning
* **Framework:** Optuna.
* **Search Space Requirements:** Define a structured search space for each model type (e.g., `learning_rate` [1e-4, 1e-1], `max_depth` [3, 10] for tree models).
* **Validation:** Optimize based on the validation set metrics.

### 3.4 MLflow Experiment Tracking
All experiments must be logged to a centralized MLflow Tracking Server.
* **Parameters Logged:** Optuna hyperparameters, model architecture details.
* **Metrics Logged:** Validation and Test metrics (F1, AUC, Loss, etc.).
* **Artifacts Logged:** Serialized model, SHAP plots, confusion matrices, ROC curves.
* **Tags:** Model name, author, datathon phase, datathon group.

### 3.5 Model Interpretability (SHAP)
* Tabular models (XGBoost, LightGBM) must output SHAP feature importance plots.
* Log global SHAP summary plots to MLflow.
* Provide utilities to generate local SHAP force plots for individual predictions.

### 3.6 ONNX Conversion
* NLP models (XLM-RoBERTa, DistilBERT) must be converted to ONNX format.
* Quantization (FP16 or INT8) should be applied to meet strict latency constraints (<10-15ms).
* Verify that inference outputs between PyTorch/Transformers and ONNX match within a defined tolerance.

### 3.7 Model Card Template
Every production-ready model must have a Model Card documented in the repo:
1. **Model Details:** Name, version, architecture, owners.
2. **Intended Use:** Primary use case, out-of-scope use cases.
3. **Training Data:** Description, time frame, demographic distribution.
4. **Evaluation:** Metrics, demographic parity (fairness for regional data).
5. **Ethical Considerations:** Bias mitigation strategies.
6. **Caveats & Recommendations.**

### 3.8 Monitoring & Retraining
* **Monitoring:** Use `Evidently` to generate reports on Data Drift (input feature distributions) and Prediction Drift (output probability distributions).
* **Alerting:** Configure Prometheus/Grafana to scrape Evidently metrics and fire alerts on significant drift.
* **Retraining Triggers:**
  1. Performance degrades below the baseline threshold (e.g., Fraud AUC drops < 0.90).
  2. Data drift is detected in top 3 SHAP-important features.
  3. Scheduled periodic retraining (e.g., monthly).
