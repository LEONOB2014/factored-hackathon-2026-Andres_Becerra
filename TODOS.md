# TODOs

## Fix the complaint product key in the card-support and dispute marts (R25)

- **What:** In `platform/dbt/models/gold/marts/mart_card_support.sql`, count open cases per customer instead of per
  affected product. In `platform/dbt/models/gold/marts/mart_transaction_disputes.sql`, drop the product term from the
  complaint-to-transaction match.
- **Why:** `fct_complaint.affected_product_id` never belongs to the complainant (0 of 43,345 complaints), so
  `mart_card_support.open_cases` counts other customers' complaints, and 26,317 of 26,351 dispute links resolve to
  `none`. The copilot's next-best-action and the dispute views read these marts.
- **Pros:** Correct open-case counts and dispute links for the copilot; removes a defect the technical report has to
  document as open.
- **Cons:** Changes served mart values, so downstream snapshots, copilot evaluation baselines and the Atlas views that
  read them must be re-run and compared.
- **Context:** Found in the pipeline emulator series (`eda/notebooks/pipeline/07_service_marts`) and the country
  series. The technical report (`docs/designs/technical-report.md`, Chapter 11) reports the defect with its counts
  rather than fixing it, to keep the report branch free of pipeline behavior changes. Start by adding a dbt unit test
  that fails on the current join, then change the join.
- **Depends on / blocked by:** The end of the hackathon evaluation (no remote changes until then). Do it on its own
  `fix/` branch from `develop`, not on `docs/technical-report`.
