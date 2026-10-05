"""Shared with the hour-grain readiness gate (`latam_eda.hour_models`)."""

SEED = 2026
BOOTSTRAP_ROUNDS = 200
# In-context limit for the foundation model. The gate's test split is not capped.
MAX_CONTEXT_ROWS = 60_000
MAX_COLUMNS = 100
QUANTILE = 2 / 3
