# Knowledge base (governed)

Documents indexed by the `kb_sync` DAG into pgvector (`knowledge.kb`) and Neo4j. Rules: `platform/policies/kb_governance.yaml`.

* Only `status: approved` documents inside their effective window are servable (`kb.active_chunk`).
* Drafts, superseded, retired and expired versions are never retrievable; their registry rows stay (append-only) for audit.
* Documents with personal data are rejected at ingestion.
* Policies here are **synthetic internal policies** for the demo bank; `reg-*` documents are short summaries of public
  facts with sources, for internal use only, and must be verified with counsel.

File naming: `<doc_id>_v<version>.md`. To publish a new version: add a new file with a higher version and `supersedes`,
then set the old file's `status: superseded` (a status change is recorded as an event, the old content is never edited).
