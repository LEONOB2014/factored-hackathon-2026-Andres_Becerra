# %% [markdown]
# # 12 · Audit and the three gates
# **Pipeline series** · task group `audit`, then the Python tasks `drift_holds`, `dq_gate` and `governance_gate`
#
# ## What happens here
# The last task group measures everything built before it, and three gates decide whether the run may publish:
#
# | step | what it does | fails the run when |
# |---|---|---|
# | `audit` models | integrity findings (row rules R01–R27), cell findings (contract rules C01–C10), rule summary against SLOs, partition manifest, SCD2 change log, backup reconciliation | never (they measure) |
# | `drift_holds` | opens a review for each newly held partition | never (a hold is already contained) |
# | `dq_gate` | reads the rule summary | a severity-A rule breaches its SLO **and** is enforced |
# | `governance_gate` | checks every model's owner, data class, residency, zone, contracts, PII policy | any governance error |
#
# Only after the three gates does `dbt_lakehouse` mark the `LAKEHOUSE` asset as updated, which triggers publishing,
# graph loading, ML training and monitoring.

# %%
import json
import subprocess
import sys
import time

sys.path.insert(0, "../../src")
import ipywidgets as w
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import pipeline as pipe
from latam_eda import theme

theme.register()
t0 = time.time()
pl = pipe.session()
pl.ensure_until("privacy_serving")
AUDIT = pl.catalog().query("layer == 'audit'")["node"].tolist()
built = pl.build_set(AUDIT)

# %% [markdown]
# ## 1 · Integrity rules against their SLOs
# `dq_integrity_findings` holds one row per (rule, violating row): 11.5 M rows, because some rules fire on half a
# table. `dq_rule_summary` turns them into rates per rule and compares each with its baseline and maximum (seed
# `dq_rule_slo`); cell rules C01–C10 are summarised per table the same way.

# %%
summ = pl.q("""select rule_id, severity, table_name, violations, table_rows, rate_pct, baseline_rate_pct,
                      max_rate_pct, slo_breached, enforce_in_dev, rule_description
               from {dq_rule_summary} where rule_id like 'R%' order by rule_id""")
show(summ, paging=False)
fig = px.scatter(
    summ,
    x="baseline_rate_pct",
    y="rate_pct",
    color="severity",
    hover_name="rule_id",
    symbol="slo_breached",
    title="Row rules: measured rate against baseline (%)",
)
fig.add_shape(type="line", x0=0, y0=0, x1=100, y1=100, line=dict(dash="dot"))
fig.update_layout(height=380)
fig.show()

# %% [markdown]
# Every rule sits on or just below its baseline (the diagonal): the data did not get worse. Three rules breach their SLO because the
# policy maximum is 0 % while the data violates them by construction: **R21** (sends without consent, 50 %), **R25**
# (complaint product owned by another customer, 66 %) and **R26** (digital event product owned by another customer,
# 7 %). They are severity A but `enforce_in_dev = false`.

# %%
cell = pl.q("""select rule_id, table_name, violations, rate_pct, max_rate_pct, slo_breached
               from {dq_rule_summary} where rule_id like 'C%' and violations > 0 order by violations desc""")
show(cell, paging=False)

# %% [markdown]
# ## 2 · The gates, emulated
# The same queries the Python tasks run, against the scratch lakehouse.

# %%
holds = pl.q("select * from {dq_partition_holds}")
display(
    Markdown(f"**drift_holds**: {len(holds)} held partition(s) → {len(holds)} review(s) to open.")
)

breaches = pl.q("""select rule_id, severity, rate_pct, max_rate_pct, enforce_in_dev
                   from {dq_rule_summary} where slo_breached""")
blocking = breaches[(breaches.severity == "A") & breaches.enforce_in_dev]
display(
    Markdown(
        f"**dq_gate**: {len(breaches)} breach(es), {len(blocking)} blocking → "
        + ("**FAIL**" if len(blocking) else "pass")
    )
)
show(breaches, paging=False)

gov = subprocess.run(
    [
        str(pl.repo / "platform" / ".venv" / "bin" / "python"),
        "-c",
        "import json, sys; from pathlib import Path; from latam_platform import governance as g; "
        "r = g.check_manifest(Path(sys.argv[1])); "
        "print(json.dumps({'checked_models': r.checked_models, 'errors': r.errors, 'warnings': r.warnings}))",
        str(pl.manifest_path),
    ],
    capture_output=True,
    text=True,
    check=True,
)
g = json.loads(gov.stdout)
display(
    Markdown(
        f"**governance_gate**: {g['checked_models']} models checked, {len(g['errors'])} error(s), "
        f"{len(g['warnings'])} warning(s) → " + ("**FAIL**" if g["errors"] else "pass")
    )
)

# %% [markdown]
# **What enforcement would do.** Flip `enforce_in_dev` for R21, R25 and R26 and the gate fails every run, forever: the
# violations are in the source, not in a bad day. That is why decision *slo-breach-rules* on the board recommends
# keeping them non-blocking while the **marts** exclude or flag the violating rows (consent gate in campaigns,
# ownership check in complaints and digital events). A blocking gate should guard against *change*, which the
# baseline-plus-tolerance rules already do for the other 23.

# %% [markdown]
# ## 3 · The other audit models

# %%
show(
    pl.q("""select 'audit_partition_manifest' as model, count(*) as n_rows,
                   'per partition: row count and a digest of every record''s landed bytes' as what
            from {audit_partition_manifest}
            union all select 'audit_scd2_change_log', count(*), 'every version change the snapshots recorded'
            from {audit_scd2_change_log}
            union all select 'audit_backup_reconciliation', count(*), 'main against the backup folder, per table'
            from {audit_backup_reconciliation}
            union all select 'dq_cell_findings', count(*), 'one row per cell breaking its contract'
            from {dq_cell_findings}
            union all select 'dq_integrity_findings', count(*), 'one row per row breaking an integrity rule'
            from {dq_integrity_findings}"""),
    paging=False,
)
show(pl.q("select * from {audit_backup_reconciliation}"), paging=False)

# %% [markdown]
# * The **partition manifest** is what makes a rebuild verifiable: each partition's digest is computed over the bytes
#   that landed, so the same digest after a rebuild proves the same input.
# * The **SCD2 change log** is empty: one snapshot, no changes yet (notebook 06).
# * The **backup reconciliation** reports the second folder as a different dataset (the atlas, module 05); its test
#   `backup_is_faithful` is a warning by design, documenting rather than failing.

# %% [markdown]
# ## 4 · Every test, every layer
# The data tests the series ran after each task group, as Cosmos does.

# %%
for layer in pipe.LAYER_NAMES:
    if not len(pl.q(f"select * from main._pipeline_tests where layer = '{layer}'")):
        pl.run_tests(layer)
allt = pl.tests()
show(allt.groupby(["layer", "status"]).size().unstack(fill_value=0), paging=False)
show(allt[allt.status != "pass"][["layer", "test", "severity", "failures", "status"]], paging=False)

# %% [markdown]
# 107 data tests: no failure. Four warnings, all documented: customers' and agents' branches that do not exist
# (R23, R24), the backup that is not a backup, and the three SLO breaches not enforced in development.

# %% [markdown]
# ## 5 · Fidelity: does the emulator reproduce Airflow?
# The scratch lakehouse was compared with the live one (same commit, built by Airflow in Docker) relation by relation,
# with `platform/dbt/scripts/verify/compare_lakehouses.py --fingerprint` (count, sum of row hashes, sum of hashes per
# column). Every difference has one of four explanations, and none is a logic difference:
#
# | difference | relations | explanation |
# |---|---|---|
# | tokens (`*_token`, IP graph nodes, customer document ids) | profile, 360, inquiry, card support, disputes, sessions, graph, knowledge | the stack salts tokens with a secret (`LATAM_PII_SALT`); the emulator uses the development default. Same structure, different values, by design |
# | last-digit floating point (relative 2–4 × 10⁻¹⁶; z-scores 3 × 10⁻¹³) | fraud features, credit features, eligibility, profile `log10_median`, graph log amounts | `ln`, `log10`, `asin` differ in the last bit between the Linux container's math library and macOS; reproducibility within one platform is exact (108/108) |
# | run timestamps | knowledge `generated_at`, snapshots | volatile by definition |
# | unreadable | live views (typed, staging) | they read container paths (`/opt/latam/...`); the same bronze, read here directly |
#
# Row counts match for every relation. The live lakehouse also still contains `reference.dq_partition_releases`, a
# seed removed in phase 4: dbt never drops relations it no longer builds. **Recommendation:** drop it, and add a
# periodic "orphan relations" check (relations in the database with no node in the manifest).

# %% [markdown]
# ## 6 · Build times of the whole replay

# %%
log = pl.log().drop_duplicates("node", keep="last")
by = log.groupby("layer")["seconds"].sum().reindex(pipe.LAYER_NAMES).fillna(0).round(1)
show(by.rename("seconds").to_frame(), paging=False)
show(
    log.sort_values("seconds", ascending=False).head(10)[["node", "layer", "rows", "seconds"]],
    paging=False,
)

# %% [markdown]
# The full platform, 109 relations from 23.5 M records, builds in about four minutes on a laptop with 4 GB for
# DuckDB. Speed is not the constraint for daily batch; correctness and evidence are.

# %% [markdown]
# ## 7 · Explorer: findings of any rule

# %%
rules = summ["rule_id"].tolist()
w_r = w.Dropdown(options=rules, value="R25", description="rule")
out_r = w.Output()


def draw_rule(*_):
    with out_r:
        out_r.clear_output()
        row = summ.set_index("rule_id").loc[w_r.value]
        display(
            Markdown(
                f"**{w_r.value}** · {row.rule_description} · {row.violations:,} violations "
                f"({row.rate_pct} %, baseline {row.baseline_rate_pct} %, max {row.max_rate_pct} %)"
            )
        )
        show(
            pl.safe(
                pl.q(
                    f"select * from {{dq_integrity_findings}} where rule_id = '{w_r.value}' limit 10"
                )
            ),
            paging=False,
        )


w_r.observe(draw_rule, "value")
draw_rule()
display(w.VBox([w_r, out_r]))

# %% [markdown]
# ## What the whole series found, and what to do, in priority order
#
# **Fix now (small changes, high impact):**
# 1. **`pii_hash` must keep NULL as NULL** (notebook 10). Missing IPs, e-mails and phones collapse into single tokens:
#    a graph supernode linking 95 % of customers, and thousands of people merged for entity resolution.
# 2. **Version 1 of each SCD2 dimension valid from the beginning of time** (notebook 06). 19 % of transactions lose
#    their customer key and 19 % their product key today; add `not_null` tests on the surrogate keys.
# 3. **Move `mart_credit_eligibility` after the features task group** (notebook 01), and test the manifest for
#    forward dependencies.
# 4. **Dispute candidates must ignore unowned products** (notebook 07); 11.8 k disputes lose all candidates.
# 5. **Revive `PEER_OUTLIER_INFLOW`** (notebook 08): compute peers on months with inflow or use a quantile rule; add a
#    planted-positive test per typology.
# 6. **Rename the "confirmed fraud" columns** (notebook 07) and stop the card-block rule from reading the legacy flag.
#
# **Improve next (controls and policy):**
# 7. Condition empty-share baselines on applicability (notebook 03) and add an expected-partition completeness check.
# 8. Add a row-count reconciliation test for `int_transactions_enriched` (notebook 05).
# 9. Seeds owned by compliance for regulatory deadlines and AML thresholds per country (notebooks 07, 08).
# 10. Separate *unknown* from *late* in the early-warning score; label products without DPD as unknown (notebook 08).
# 11. Drop orphan relations from the live lakehouse and check for them periodically (section 5).
# 12. Replace salted SHA-256 tokens with keyed HMAC from a tokenisation service before real data (notebook 05).
#
# **Ask the source (data that would unlock models):**
# 13. A signed amount or debit/credit flag, and the counterparty of transfers (inflows, AML networks, mule graphs).
# 14. `disputed_transaction_id` captured at intake (dispute automation).
# 15. Explicit time zones in timestamps (notebook 04), and consent history (campaign compliance at send time).
# 16. Confirmed fraud labels (chargebacks, analyst dispositions) with their dates; a randomised holdout per campaign.
#
# **What already works and should be protected:** lossless bronze, contract typing that never drops a row, the drift
# circuit breaker, the four-eyes correction overlay, reproducible gold, PIT features with embargo and parity, enforced
# serving contracts, and residency in the data model. Keep their tests mandatory in CI.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
