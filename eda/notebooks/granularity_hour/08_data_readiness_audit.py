# %% [markdown]
# # 08 · Data readiness and the collection audit
# **Granularity series III · the bank at the hour** · every hour-grain model of notebooks 02–07, executed and judged by
# one readiness gate
#
# **Why this notebook.** The synthetic source draws each process independently and at uniform times. Models trained on
# it do not fail because the methods are wrong; they fail because the data cannot carry the signal a real bank's data
# carries. Recording *why* each model is not trainable turns a set of red results into a **specification for the data
# collection process**: what the source must capture, who owns it, the test that proves a new feed has it, and the
# threshold at which the same pipeline turns the model green.
#
# **The gate (`granularity.readiness_verdict`, one rule for every model).** A model's gain over a transparent benchmark
# is measured out of time with a paired bootstrap (200 resamples):
# * **green**: the 95 % interval excludes zero and the gain reaches the materiality threshold;
# * **amber**: significant but below the threshold (or unstable across folds);
# * **red**: no evidence. The root cause is *insufficient volume* when even a material gain would be undetectable (the
#   minimum detectable effect, 2.8 bootstrap standard errors, exceeds the threshold); otherwise the scenario's own
#   diagnosis: *generator independence* (processes drawn without links), *missing field* (the key, schedule or measure
#   is not collected), or *data defect* (a collected field contradicts the activity).
#
# **Re-running it.** `uv run scripts/readiness_check.py --dataset main --scope ALL` recomputes this scorecard on any
# lake: when a new source is ingested, the same command says which gates turned green.

# %%
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, "../../src")
import plotly.graph_objects as go
from IPython.display import Markdown, display
from itables import show

from latam_eda import country, theme
from latam_eda import granularity as g
from latam_eda import hour_models as hm

warnings.filterwarnings("ignore")
OUT = Path("../../reports/tables")
theme.register()
t0 = time.time()
pl = country.session("ALL", "main")
country.prepare(pl, "gold")
star = g.open_star(pl, [g.SQL_DIR_TIME, g.SQL_DIR_HOUR])
star.build(verbose=False)

# %% [markdown]
# ## 1 · The scorecard

# %%
sc = hm.scorecard(star)
sc.to_csv(OUT / "granularity_hour_readiness.csv", index=False)
show(
    sc[
        [
            "scenario",
            "model",
            "metric",
            "value",
            "benchmark",
            "benchmark_value",
            "delta",
            "delta_lo",
            "delta_hi",
            "material",
            "mde",
            "verdict",
            "root_cause",
        ]
    ].round(4),
    paging=False,
)
sc["gain / material"] = sc.delta / sc.material
sc["lo / material"] = sc.delta_lo / sc.material
sc["hi / material"] = sc.delta_hi / sc.material
order = sc.sort_values("gain / material")
color = {"green": "#2e7d32", "amber": "#ef8f00", "red": "#c62828"}
fig = go.Figure()
for v, d in order.groupby("verdict", sort=False):
    fig.add_trace(
        go.Scatter(
            x=d["gain / material"],
            y=d.model,
            mode="markers",
            name=v,
            marker={"color": color[v], "size": 10},
            error_x={
                "type": "data",
                "symmetric": False,
                "array": d["hi / material"] - d["gain / material"],
                "arrayminus": d["gain / material"] - d["lo / material"],
            },
        )
    )
fig.add_vline(x=0, line_dash="dot")
fig.add_vline(x=1, line_dash="dash", annotation_text="material")
fig.update_layout(
    height=420,
    title="Out-of-time gain over the benchmark, in units of the materiality threshold (95 % intervals)",
    xaxis_title="gain / material (1 = the smallest gain worth deploying)",
)
fig.show()
counts = sc.verdict.value_counts()
causes = sc[sc.verdict == "red"].root_cause.value_counts()
display(
    Markdown(
        f"**{len(sc)} models executed: {counts.get('green', 0)} green, {counts.get('amber', 0)} amber, "
        f"{counts.get('red', 0)} red.** Red root causes: "
        + ", ".join(f"{k} ({v})" for k, v in causes.items())
        + ". "
        + (
            "No hour-grain model is trainable on this source. "
            if counts.get("green", 0) == 0
            else f"Trainable now: {', '.join(sc[sc.verdict == 'green'].model)}. "
        )
        + (
            f"The amber models ({', '.join(sc[sc.verdict == 'amber'].model)}) find real but immaterial gains: the "
            "methods work and detect small effects, which is the evidence that the reds are the data's limit, not the "
            "pipeline's."
            if counts.get("amber", 0)
            else ""
        )
    )
)

# %% [markdown]
# ## 2 · The audit: what the data collection must change
# For every model that is not green: the requirement, its owner, the acceptance test a new feed must pass, and how much
# test data the current noise level would need to detect a material gain.

# %%
aud = sc[sc.verdict != "green"].copy()
aud["owner"] = [hm.AUDIT[(s, m)][0] for s, m in zip(aud.scenario, aud.model, strict=True)]
aud["acceptance test on a new feed"] = [
    hm.AUDIT[(s, m)][1] for s, m in zip(aud.scenario, aud.model, strict=True)
]
show(
    aud[
        [
            "scenario",
            "model",
            "verdict",
            "root_cause",
            "requirement_to_green",
            "owner",
            "acceptance test on a new feed",
            "n_test",
            "n_test_needed",
        ]
    ],
    paging=False,
)
by_owner = aud.groupby("owner").model.apply(lambda x: "; ".join(x)).reset_index()
show(by_owner, paging=False)
display(
    Markdown(
        f"**The audit names {aud.owner.nunique()} owners.** The requirements fall into four kinds: "
        "(1) **clocks and schedules**: declared time zones (ADR-014), branch opening days and hours, rostered shifts; "
        "(2) **linking keys**: session, case and contact identifiers that tie one process to another; "
        "(3) **operational event logs**: agent states, queue events, ATM dispense events, real clickstream order; "
        "(4) **experiments**: randomised send times and holdouts, without which a send-time or uplift model learns "
        "the campaign's choices, not the customer's response. None of them is a modelling task: each is a change to "
        "what the source systems record, and each has a test that tells, on the first weeks of a new feed, whether it "
        "arrived."
    )
)

# %% [markdown]
# ## 3 · From red to green: the re-evaluation loop
# 1. A source owner delivers a requirement (for example rostered shifts from the workforce system).
# 2. The feed lands in bronze with its contract; the acceptance test of the table above runs on its first weeks.
# 3. `scripts/readiness_check.py` re-runs this scorecard; a gate turns green only when the out-of-time gain is
#    significant and material, on the same rule as here.
# 4. A green gate opens the ML path of strategy chapter 12 (§12.4: model card, benchmark, monitoring plan); an amber gate
#    stays a KPI or a rule.

# %%
pl.close()
print(f"notebook time {time.time() - t0:.0f}s")
