# %% [markdown]
# # 02 · Correction workbench
# **Model-risk series, phase 4** · four-eyes correction and restore of flagged cells
#
# ## What this notebook is for
# Silver flags every cell that breaks its source contract (`audit.dq_cell_findings`, notebook 01 and
# docs/platform/09 §C). This workbench helps a **data steward** decide what to do about them and write a
# **proposal**. It never changes data: the proposal goes through the `dq_correction_review` DAG, which validates it
# against the contracts and lossless bronze, and an **approver who is not the proposer** decides in Airflow. Only an
# approved proposal reaches silver, as an overlay; bronze keeps the original value, and a revert restores it.
#
# | step | where | who |
# |---|---|---|
# | explore findings, preview impact, write the proposal | this notebook | steward |
# | validate, stage, record `dq.correction_proposed` | Airflow `dq_correction_review`, triggered as `steward` | steward |
# | approve or reject, with a comment | Airflow *Required actions* | `approver` |
# | apply to the correction log, rebuild silver and gold | Airflow, automatically | - |
#
# Proposal kinds: **pattern** (every cell holding a value, e.g. `Mexico` → `México`), **cells** (named records),
# **revert** (undo an applied correction), **release** (lift a schema-drift hold).
#
# **Inputs.** The lakehouse (`data/lake/lakehouse.duckdb`, read-only) after a `dbt_lakehouse` run. Open it when no
# Airflow dbt run is active: DuckDB has a single writer.

# %%
import os
import sys
from pathlib import Path

sys.path.insert(0, "../../src")
import ipywidgets as w
from IPython.display import Markdown, display
from itables import show

from latam_eda import correction_workbench as wb

REPO = Path("../../..").resolve()
LAKEHOUSE = Path(os.environ.get("LATAM_LAKEHOUSE", REPO / "data" / "lake" / "lakehouse.duckdb"))
PROPOSALS = Path(
    os.environ.get("LATAM_PROPOSALS", REPO / "data" / "lake" / "corrections" / "proposals")
)
MANIFEST = REPO / "platform" / "dbt" / "target-airflow" / "manifest.json"
con = wb.connect(LAKEHOUSE)
print(f"lakehouse: {LAKEHOUSE.name} · proposals go to {PROPOSALS.relative_to(REPO)}")

# %% [markdown]
# ## 1 · Findings by pattern
# One row per (table, column, issue code, value). `cells` counts flagged cells, `already_corrected` those an
# approved correction fixes in silver today. `pii` values are shown only as a shape (letters → A, digits → 9): those
# columns are corrected cell by cell, never by pattern. Codes: T cast, F format, N required empty, K key, V1 unknown
# vocabulary, V2 variant spelling, P rendered null, S template slot, G CSV grammar.

# %%
groups = wb.pattern_groups(con)
show(groups, lengthMenu=[10, 25, 50], pageLength=10)

# %% [markdown]
# ## 2 · Drill into a pattern and preview its impact
# Pick a group: the records it touches (lineage only) and the consumer models a correction would change.

# %%
choices = [
    (f"{r.table_name}.{r.column_name} · {r.issue_code} · {r.raw_value!r} · {r.cells:,} cells", i)
    for i, r in groups.iterrows()
]
pick = w.Dropdown(options=choices, description="pattern", layout=w.Layout(width="90%"))
out = w.Output()


def preview(change=None):
    out.clear_output()
    g = groups.loc[pick.value]
    with out:
        display(Markdown(
            f"**{g.cells:,} cells** in {g.records:,} records, {g.partitions:,} partitions "
            f"({g.first_partition} → {g.last_partition}); {g.already_corrected:,} already corrected."
        ))  # fmt: skip
        display(wb.records(con, g.table_name, g.column_name, g.raw_value, limit=10))
        display(
            Markdown(
                "Consumers that would change: "
                + (", ".join(wb.downstream(MANIFEST, g.table_name)) or "-")
            )
        )


pick.observe(preview, names="value")
display(pick, out)
if choices:
    preview()

# %% [markdown]
# ## 3 · Write a pattern proposal
# The new value must satisfy the column's contract (the DAG re-checks it with the same predicates the typed models
# use), and the reason is the first thing the approver reads. An id cannot be reused.

# %%
pid = w.Text(description="proposal_id", placeholder="cp-2026-10-mexico-variant")
to_value = w.Text(description="new value")
reason = w.Textarea(description="reason", layout=w.Layout(width="90%", height="70px"))
write = w.Button(description="Write proposal", button_style="primary")
result = w.Output()


def on_write(_):
    result.clear_output()
    g = groups.loc[pick.value]
    with result:
        try:
            p = wb.pattern_proposal(
                pid.value, g.table_name, g.column_name, g.raw_value, to_value.value, reason.value
            )
            path = wb.write_proposal(p, PROPOSALS)
            display(Markdown(f"`{path.name}` written. {wb.next_step(p['proposal_id'])}"))
        except (ValueError, FileExistsError) as exc:
            display(Markdown(f"**Not written:** {exc}"))


write.on_click(on_write)
display(pid, to_value, reason, write, result)

# %% [markdown]
# ## 4 · Cells, reverts and releases
# The same helpers write the other kinds. Fill in and run the cell you need; each writes one proposal file.
#
# * **cells**: name each cell by its bronze lineage (from §2) with the value it holds today (`old_value`): a stale
#   value is refused, so a proposal never overwrites a change it did not see;
# * **revert**: the applied proposal ids to undo; silver returns to the original values on the next build;
# * **release**: a partition held by the schema-drift circuit breaker (below), once its change is understood.

# %%
show(wb.holds(con))
EXAMPLES = {
    "cells": lambda: wb.cells_proposal(
        "cp-example-cells",
        [
            {
                "zone": "bronze",
                "table": "transactions",
                "source_file": "<from §2>",
                "record_no": 0,
                "column": "transaction_city",
                "old_value": "<value today>",
                "new_value": "<new value>",
            }
        ],  # fmt: skip
        "<why this record is wrong and what the right value is>",
    ),
    "revert": lambda: wb.revert_proposal(
        "cp-example-revert", ["<applied proposal id>"], "<why it must be undone>"
    ),
    "release": lambda: wb.release_proposal(
        "cp-example-release", "<table>", "<YYYY-MM-DD>", "<what changed and why it is safe>"
    ),
}
print("Example (not written):", EXAMPLES["revert"]())
# wb.write_proposal(EXAMPLES["revert"](), PROPOSALS)   # edit the values first, then uncomment to write
