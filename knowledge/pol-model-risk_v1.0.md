---
doc_id: pol-model-risk
version: 1.0
status: approved
title: Model risk management policy
country: ALL
language: en
classification: internal
owner: model-risk
approver: chief-risk-officer
effective_from: 2026-07-01
effective_to: null
supersedes: null
source_url: null
---
# Model risk management policy

## Inventory and tiering
Every model, including prompt and tool chains of AI agents, is registered with an owner, a tier and a validator.

## Validation
Tier 1 models (credit decisions, fraud declines, AML alerts) require independent validation before promotion; promotion to champion requires a human approval recorded in the orchestrator.

## Monitoring
Drift above PSI 0.25 on a top feature, or an approval-rate ratio below 0.8 across protected groups, triggers a model risk review.
