# %% [markdown]
# # 12 · Integrity rules, country SLOs and the gates (Colombia)
# **Country series · Colombia** · *generated from `notebooks/country_template`: edit the template*
#
# The audit task group measures every integrity rule against its SLO (baseline and maximum rate, seed `dq_rule_slo`),
# and `dq_gate` blocks a run when an enforced severity-A rule breaches (pipeline series, notebook 12). The SLOs were
# measured on the bank as a whole. This notebook asks which rules behave differently in Colombia, and what
# the SLO of each rule should be for this country.

# %%
import sys
import time
from pathlib import Path

sys.path.insert(0, "../../src")
import plotly.express as px
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme

COUNTRY = "CO"
DATASET = "main"
PREFIX = "country"
CTRY = country.SCOPES[COUNTRY]
OUT = Path("../../reports/tables")
OUT.mkdir(parents=True, exist_ok=True)
theme.register()
t0 = time.time()
pl = country.session(COUNTRY, DATASET)
country.prepare(pl, "privacy_serving")
AUDIT = pl.catalog().query("layer == 'audit'")["node"].tolist()
built = pl.build_set(AUDIT)

# %% [markdown]
# ## 1 · Every row rule: the country's rate against the bank's

# %%
slo = country.country_rule_slo(pl)
slo.assign(country=COUNTRY, dataset=DATASET).to_csv(
    OUT / f"{PREFIX}_{COUNTRY.lower()}_rule_slo.csv", index=False
)
show(slo.round(3), paging=False)
fig = px.scatter(
    slo,
    x="global_baseline_pct",
    y="country_rate_pct",
    color="severity",
    hover_name="rule_id",
    symbol="breaches_global_slo",
    title=f"{CTRY.title}: rule rates against the bank-wide baseline (%)",
)
fig.add_shape(type="line", x0=0, y0=0, x1=100, y1=100, line=dict(dash="dot"))
fig.update_layout(height=420)
fig.show()
diff = slo[(slo.country_rate_pct - slo.global_baseline_pct).abs() >= 1].sort_values("rule_id")
display(
    Markdown(
        f"**{len(diff)} rules differ from the bank-wide baseline by a point or more in {CTRY.name}:** "
        + ", ".join(
            f"{r.rule_id} ({r.global_baseline_pct:.1f} → {r.country_rate_pct:.1f} %)"
            for r in diff.itertuples()
        )
        + "."
        if len(diff)
        else f"**No rule differs from the bank-wide baseline by a point or more in {CTRY.name}.**"
    )
)

# %% [markdown]
# **How to read the differences (country scopes).**
# * **R17** (USD label on a Mexican customer) is by definition a Mexican rule: about 100 % of Mexican transactions,
#   0 % elsewhere. A bank-wide rate of 50 % describes no country.
# * **R25** (complaint product owned by another customer) and **R26** (digital event product owned by another
#   customer) drop sharply in a single country: most of the "other customers" are in other countries, whose products
#   are not in this country's table. The defect is cross-border.
# * **R18** (imputed USD amounts) depends on the share of non-USD transactions; **R20** (anonymous events) on how much
#   anonymous traffic the IP attribution brought in.
#
# **Decision: SLOs per country.** A gate that compares a country's rate with a bank-wide maximum either never fires
# (where the country is below the blend) or always fires (where it is above). The `country_max_pct` column re-bases
# each SLO on the country's own rate, keeping the bank's tolerance ratio, and leaves the zero-tolerance policies (R21,
# R25, R26) at 0 %: geography changes a baseline, not a policy.

# %% [markdown]
# ## 2 · The gates, emulated on the scope

# %%
held = pl.q("select count(*) as held from {dq_partition_holds}").iloc[0, 0]
breaches = pl.q("""select rule_id, severity, rate_pct, max_rate_pct, enforce_in_dev
                   from {dq_rule_summary} where slo_breached order by rule_id""")
blocking = breaches[(breaches.severity == "A") & breaches.enforce_in_dev]
display(
    Markdown(
        f"**drift_holds**: {held} held partitions (country contract). "
        f"**dq_gate** (bank-wide SLOs): {len(breaches)} breaches, {len(blocking)} blocking → "
        + ("**FAIL**" if len(blocking) else "pass")
        + f". With country SLOs: {int((slo.country_rate_pct > slo.country_max_pct).sum())} breaches."
    )
)
show(breaches, paging=False)

# %% [markdown]
# ## 3 · Reconciliation against the quarantined copy
# `audit_backup_reconciliation` compares the authoritative bronze with the copy in quarantine, key by key, as landed
# text: a true backup gives the same keys and identical records.

# %%
rec = pl.q("select * from {audit_backup_reconciliation} order by table_name")
rec["changed_pct_of_shared"] = (
    100 * rec.shared_changed / rec.shared_keys.where(rec.shared_keys > 0)
).round(1)
rec.assign(country=COUNTRY, dataset=DATASET).to_csv(
    OUT / f"{PREFIX}_{COUNTRY.lower()}_reconciliation.csv", index=False
)
show(rec, paging=False)
display(
    Markdown(
        "**Reconciliation:** "
        + "; ".join(
            f"{r.table_name}: {r.shared_keys:,} shared keys, {r.only_main:,} only here, {r.only_backup:,} only in the "
            f"copy, {r.changed_pct_of_shared:.0f} % of shared records changed"
            for r in rec.itertuples()
        )
        + ". "
        + (
            "The copy is not a backup of this data: any equality test would fail loudly."
            if (rec.shared_changed > 0).any() or (rec.only_backup > 0).any()
            else "The copy matches."
        )
    )
)

# %%
pl.ensure_until("audit")
for layer in country.pipe.LAYER_NAMES:
    if not len(pl.q(f"select * from main._pipeline_tests where layer = '{layer}'")):
        pl.run_tests(layer)
allt = pl.tests()
show(allt.groupby(["layer", "status"]).size().unstack(fill_value=0), paging=False)
show(allt[allt.status != "pass"][["layer", "test", "failures", "status"]], paging=False)

# %% [markdown]
# ## Findings for Colombia and what to do
# The computed statements above. The production design that follows: contracts and SLOs keyed by (table, country),
# zero-tolerance policies shared, and the gate evaluated per country so one country's data cannot block another's run.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
