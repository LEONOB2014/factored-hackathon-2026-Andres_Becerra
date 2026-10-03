---
doc_id: std-data-residency
version: 1.0
status: approved
title: Data residency standard
country: ALL
language: en
classification: internal
owner: data-platform
approver: chief-data-officer
effective_from: 2026-07-01
effective_to: null
supersedes: null
source_url: null
---
# Data residency standard

## Principle
Personal and confidential data of a country's customers is stored and processed only in the regions approved for that country in the residency policy (platform/policies/residency.yaml).

## Mexico and Brazil
Mexico uses northamerica-south1 (Querétaro) and Brazil uses southamerica-east1 (São Paulo), both in-country.

## Colombia and Argentina
No in-country BigQuery region exists. The proposed region is southamerica-east1 under a documented international transfer basis, pending legal sign-off.

## Cross-border outputs
Only differentially private aggregates, public reference data and approved model weights may cross borders.
