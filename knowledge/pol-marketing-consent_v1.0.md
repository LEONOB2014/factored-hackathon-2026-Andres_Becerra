---
doc_id: pol-marketing-consent
version: 1.0
status: approved
title: Marketing consent policy
country: ALL
language: en
classification: internal
owner: marketing-compliance
approver: data-protection-officer
effective_from: 2026-01-01
effective_to: null
supersedes: null
source_url: null
---
# Marketing consent policy

## Rule
No marketing communication may be sent to a customer without valid consent for that channel and purpose at send time.

## Evidence
Consent is stored as an event history (who, when, channel, purpose, text version). The current flag alone is not sufficient evidence.

## Control
The consent gate runs before every campaign send (regulatory trigger consent_revoked). Sends without consent are suppressed and recorded.
