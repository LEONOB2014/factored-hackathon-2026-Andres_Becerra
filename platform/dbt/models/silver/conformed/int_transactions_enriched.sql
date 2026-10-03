-- The conformed transaction fact: one row per transaction with repaired USD amount, local time,
-- direction, decoded response and one boolean per data-quality rule. Every downstream mart reads this.
{{ enrich_transactions(ref('stg_transactions')) }}
