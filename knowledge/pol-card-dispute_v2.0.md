---
doc_id: pol-card-dispute
version: 2.0
status: approved
title: Card transaction dispute policy
country: ALL
language: en
classification: internal
owner: disputes-operations
approver: head-of-operations
effective_from: 2026-04-01
effective_to: null
supersedes: 1.0
source_url: null
---
# Card transaction dispute policy (v2.0)

## Scope
Applies to unrecognised card charges and incorrect fees reported through any channel, including complaints received through a regulator.

## Mandatory intake data
Every dispute must capture the disputed transaction identifier at intake (control C5). A dispute without a transaction identifier is returned to intake; probabilistic matching is only a fallback and is flagged with its confidence level.

## Ownership check
The disputed product must belong to the complaining customer. Cases where the product belongs to another customer are routed to data quality (rule R25) and never processed automatically.

## Workflow
Disputes follow an orchestrated saga: provisional credit decision, evidence collection, card-network chargeback, final resolution and customer notice. Each step is recorded in the audit ledger.

## Service levels
Internal service levels per priority are set by operations; regulatory response deadlines per country are maintained by compliance and override internal targets when stricter.
