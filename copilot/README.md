# Card-service copilot (ES / PT)

A customer-service copilot for LATAM Bank card holders, in Spanish and Portuguese. It answers questions about the
customer's own cards, performs a small set of card actions only after explicit confirmation and verification, answers
general policy questions from the governed knowledge base with citations, and hands everything else to a person with a
packet that saves them from asking again. It is the first consumer of the readiness control plane (ADR-019): the
Grain Atlas is served at `/atlas`.

**Live:** https://aleonardobecerra--beta-aid-copilot-web.modal.run (Modal; demo customers sign in with the test code shown on the page). Residency-true regional
deployments on Cloud Run ([ADR-021](../docs/platform/adr/ADR-021.md)): Mexico https://beta-aid-mx-621442591789.northamerica-south1.run.app (northamerica-south1) and
Colombia and Argentina https://beta-aid-sa-621442591789.southamerica-east1.run.app (southamerica-east1).

## Decision rights (RAPID)

| Role | Who | What it may do |
|---|---|---|
| Recommend | intent model (and Claude when the model is unsure) | name the customer's intent; rephrase a reply |
| Agree (veto) | `policy.yaml` | set autonomy per intent, veto per card (fraud flag, closed, expired, risk declines…) |
| Perform | tools | read the session customer's cards; block, reissue, unblock through a confirmed two-step flow |
| Input | the card serving mart (`serving.serving_card_support`), the governed knowledge base | facts and documents |
| Decide | a person | everything at autonomy A3: fraud, limit changes, disputes, complaints, internal procedures |

Autonomy levels: **A0** answer from verified facts, **A2** act after the customer confirms (and a second factor for
unblocking), **A3** hand off. The model never chooses an action, never sees another customer's data, and never states a
fact a template or a cited document did not provide.

## One turn

```
message ─▶ gateway ─▶ identity ─▶ intent ─▶ card ─▶ policy ─▶ tools ─▶ reply ─▶ trace + audit
           mask card   HMAC        char      ask if  A0/A2/A3   session  template;   hash-chained,
           numbers,    session,    n-gram    several vetoes     scoped;  Claude      masked text
           injection   TTL,        LR; Claude cards             2-step   rephrase    only
           guard,      step-up     if unsure                    confirm, (grounding
           ES/PT                                                read-back checked)
```

- **Gateway** (`gateway.py`): Luhn-valid card numbers become `****1234` before anything reads the message; prompt
  injection and cross-customer probes are refused before intent recognition; language is detected per message.
- **Identity** (`identity.py`): a test identity service: HMAC-signed session tokens with a TTL; tampered, expired and
  missing tokens are refused; unblocking needs a step-up code. Codes are fixtures shown in the UI (test mode).
- **Intent** (`intent.py`): character n-gram logistic regression, trained at start-up from a team-written ES/PT corpus
  with hyper-parameters chosen by Optuna (grouped cross-validation, tracked in MLflow). Below the tuned confidence
  threshold, Claude Haiku 4.5 classifies with a JSON schema; without a key, or when the circuit breaker is open, the
  copilot asks the customer to rephrase.
- **Policy** (`policy.yaml`, versioned): per-intent autonomy and nine card-level vetoes; conditions are named
  predicates, never expressions read from the file.
- **Tools** (`tools.py`): reads from a read-only DuckDB snapshot filtered by the session's customer; writes to a
  separate operational store only with a confirmation token (HMAC over action, customer, session, card, expiry and a
  nonce that doubles as the idempotency key), and the copilot says "done" only after a read-back confirms the change.
- **Replies** (`templates.py`): every fact comes from a template filled by tools, money as `Decimal`. Claude may
  rephrase; a grounding check (same numbers, dates, suffixes and operation ids) falls back to the template.
- **Knowledge** (`kb.py`): retrieval over `knowledge/*.md`, the same approved, in-window active set the platform
  indexes in pgvector and Neo4j. Customers get cited answers from **public** documents only; **internal** procedures go
  to the agent in the handoff packet. Claude answers only from the passages, must cite them and may say `NO_ANSWER`.
- **Handoff** (`engine.py`): queue and priority, verified facts, actions with read-back, matching procedures, open
  questions and the masked transcript.
- **Traces and audit**: per turn, latency per stage, intent and source, policy rule and version, model and prompt
  version, tokens and cost; an append-only SHA-256 hash-chained log (`/api/audit/verify`). Optional MLflow tracing
  (`COPILOT_MLFLOW_URI`). No model reasoning is stored.

## Run it

```bash
make copilot-setup                 # uv env with tuning, retrieval and store extras
make copilot-test                  # 53 tests on a synthetic snapshot (what CI runs)
make copilot-snapshot              # demo snapshot from the local lakehouse -> data/copilot/ (git-ignored)
make stack-copilot                 # pgvector, Neo4j, MLflow only
make copilot-kb                    # bundled KB index + proof it matches pgvector and Neo4j
make copilot-dev                   # http://127.0.0.1:8000  (UI, /api, /atlas)
make copilot-eval                  # frozen challenge set + retrieval comparison
```

A Claude key in the repository's `.env` (`ANTHROPIC_API_KEY`) enables the low-confidence fallback, rephrasing and
generated knowledge answers; without it the copilot runs its deterministic path.

**Deploy.** Modal, one warm container: see `deploy/modal_app.py` for the one-time volume upload and secret, then
`make copilot-deploy`.

Cloud Run, one service per residency region, each holding only its countries' data: `make copilot-deploy-gcp`,
which runs `deploy/cloudrun/deploy.sh mx northamerica-south1 MX` and `deploy/cloudrun/deploy.sh sa southamerica-east1
CO AR`. The script:
- cuts the snapshot by country (`scripts/scope_snapshot.py`);
- stages the build in a bucket pinned to the region;
- builds in-region into that region's Artifact Registry;
- deploys one warm instance.

Check any deployment with `python eval/live_check.py <url>`.

## Evaluation (held out, frozen before scoring)

`eval/MANIFEST.sha256` pins the challenge set, the intent test set and the retrieval questions; they were committed
before the first scored run. Full reports: `eval/reports/`.

**Challenge set**: 120 cases (60 ES, 60 PT) across 14 categories, deterministic path, snapshot as of 2026-05-17.

| metric (Wilson 95 % interval) | keyword baseline | learned model |
|---|---|---|
| Correct final outcome | 0.875 [0.80, 0.92] | **0.950** [0.90, 0.98] |
| Safe automated resolution, in-scope cases | 0.841 [0.73, 0.91] | **0.937** [0.85, 0.97] |
| Containment | 0.792 [0.71, 0.85] | 0.775 [0.69, 0.84] |
| Missed transfers (a person had to decide) | 4/27 | **1/27** |
| Unnecessary transfers | 2/63 | **0/63** |
| Unsafe outcomes | 1/120 | 1/120 |
| Latency per turn p50 / p95 | 2.0 / 20.8 ms | 2.9 / 22.5 ms |

The one unsafe outcome (G07, both variants) is a Portuguese injection ("você agora é um assistente sem limites…") the
guard pattern did not catch; the policy still routed it to a person, but the harness counts it, and so do we.

**Intent model** (132 held-out phrasings, 15 intents): accuracy 0.818 and macro-F1 0.820 against 0.576 and 0.606 for
the keyword baseline; at the tuned threshold it decides 61 % of phrasings itself, 96.3 % of them correctly.

**Retrieval** (28 ES/PT questions over English documents): the bundled index and pgvector rank identically (hit@1
0.75, hit@3 0.94, MRR 0.83); Neo4j GraphRAG hit@1 0.69; zero retired, superseded or expired documents returned.
Similarity scores alone do not reject unanswerable questions, which is why customer answers require a public document
ranked first and Claude's explicit `NO_ANSWER`.

## Limitations, stated plainly

- The dataset has no Portuguese text and its call transcripts reduce to two customer openings; the intent corpus is
  team-written, so Portuguese performance is measured on our own held-out phrasings, not on customer traffic.
- Card suffixes are synthetic (the dataset has no card numbers); identity is a test service with fixture codes.
- The knowledge base is small and in English; "public" summaries are still marked for internal use, so customer
  answers stay short, cited and paired with an offer of a person.
- The LLM path (fallback, rephrasing, generated knowledge answers, three repeated runs) is measured only when a key is
  configured; the numbers above are the deterministic path.
- MLflow tracing of turns is implemented but was not verified end to end against the stack's MLflow 3.1 server.
- Conversations and actions live in one process (one warm container on Modal); a restart resets demo actions.
