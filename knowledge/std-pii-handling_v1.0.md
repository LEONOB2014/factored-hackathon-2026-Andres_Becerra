---
doc_id: std-pii-handling
version: 1.0
status: approved
title: Personal data handling standard
country: ALL
language: en
classification: internal
owner: data-protection-office
approver: data-protection-officer
effective_from: 2026-07-01
effective_to: null
supersedes: null
source_url: null
---
# Personal data handling standard

## Zones
Direct identifiers exist only in landing, bronze and silver. Gold, features, graph, knowledge, serving and audit hold tokens only. Protected attributes are used only to measure disparate impact.

## Free text
Complaint descriptions, transcripts, survey comments and prompts pass through the PII guard before storage or indexing. Knowledge base documents containing personal data are rejected.

## Erasure
Erasure requests are honoured by crypto-shredding the subject key and purging derived stores; legal holds take precedence.
