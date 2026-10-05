"""Assemble the Grain Atlas page from the Data Atlas modules, the EDA tables and src/.

Usage (from eda/): uv run python reports/dashboards/grain_atlas/build.py
Reads data_atlas.html, aggregates.json, ../../tables/*.csv and src/; writes grain_atlas.html.
"""

import csv
import json
from datetime import date
from pathlib import Path

from extract import extract

D = Path(__file__).parent
SRC = D / "src"
T = D.parents[1] / "tables"  # eda/reports/tables


def rows(name):
    with (T / f"{name}.csv").open() as f:
        return list(csv.DictReader(f))


def num(v, nd=4):
    if v in ("", None):
        return None
    try:
        f = float(v)
    except ValueError:
        return v
    if f != f:  # nan
        return None
    if f in (float("inf"), float("-inf")):
        return "inf"
    return round(f, nd)


def tests(name):
    return [
        [
            r["scenario"],
            r["test"],
            num(r["statistic"]),
            num(r["p_value"], 6),
            num(r["effect"], 5),
            num(r["n"], 0),
            r["reading"],
        ]
        for r in rows(name)
    ]


def extra():
    live = json.loads((D / "aggregates.json").read_text())
    X = {}

    # compact daily series: start date + counts
    def compact(pairs):
        d0 = date.fromisoformat(pairs[0][0])
        out, prev = [], d0
        for d, n in pairs:
            dd = date.fromisoformat(d)
            while (dd - prev).days > 1 and out:  # fill gaps with null
                out.append(None)
                prev = date.fromordinal(prev.toordinal() + 1)
            out.append(n)
            prev = dd
        return {"start": pairs[0][0], "v": out}

    X["daily"] = {k.replace("México", "Mexico"): compact(v) for k, v in live["daily_tx"].items()}
    X["daily_contacts"] = compact(live["daily_contacts"])
    for k in (
        "hour_profile",
        "hour_weekday",
        "teller_hour",
        "branch_open_frac",
        "shift_hour",
        "open_delay_6h",
        "case_assign_q",
        "case_first_response_q",
        "sla_by_days",
    ):
        X[k] = live[k]
    X["branch_open_frac"] = [round(x, 4) for x in X["branch_open_frac"]]
    # hour series tables
    X["h_channel"] = tests("granularity_hour_channel_hour")
    X["h_branch"] = tests("granularity_hour_branch_hours")
    X["h_shift"] = tests("granularity_hour_agent_shift")
    X["h_case"] = tests("granularity_hour_case_clock")
    X["h_customer"] = tests("granularity_hour_customer_profile")
    X["h_session"] = tests("granularity_hour_session_funnel")
    X["h_send"] = tests("granularity_hour_send_delay")
    X["h_signal"] = [
        [
            r["scenario"],
            r["test"],
            num(r["p_value"], 6),
            num(r["q_value"], 6),
            r["reject"] == "True",
            r["material"] == "True",
            r["signal"] == "True",
            num(r["effect"], 5),
            r["reading"],
        ]
        for r in rows("granularity_hour_signal")
    ]
    X["h_kpis"] = [
        [r["KPI"], r["definition"], r["grain"], r["owner"], r["target"], r["kind"]]
        for r in rows("granularity_hour_kpis")
    ]
    X["h_sparsity"] = [
        [
            r["grain"],
            num(r["cells"], 0),
            num(r["occupied %"], 4),
            num(r["events per occupied cell"], 4),
            num(r["Poisson empty %"], 4),
            num(r["events per cell"], 5),
            r["viable"],
        ]
        for r in rows("granularity_hour_sparsity")
    ]
    chk = {}
    for r in rows("granularity_hour_checks"):
        c = chk.setdefault(r["model"], [0, 0, []])
        c[0] += 1
        c[1] += r["ok"] == "True"
        c[2].append(r["check"])
    X["h_checks"] = [[k, v[0], v[1], sorted(set(v[2]))] for k, v in chk.items()]
    X["h_ready"] = [
        [
            r["scenario"],
            r["model"],
            r["metric"],
            num(r["value"], 6),
            r["benchmark"],
            num(r["benchmark_value"], 6),
            num(r["delta"], 6),
            num(r["delta_lo"], 6),
            num(r["delta_hi"], 6),
            num(r["material"], 4),
            num(r["mde"], 6),
            r["verdict"],
            r["root_cause"],
            r["requirement_to_green"],
            num(r["n_test"], 0),
            r["best_variant"],
        ]
        for r in rows("granularity_hour_readiness")
    ]
    # daily series tables
    X["fc"] = [
        [r["market"], r["series"], r["model"], num(r["MASE"]), num(r["DM p"], 5)]
        for r in rows("granularity_forecast_skill")
    ]
    X["surv_cases"] = [
        [
            r["group"],
            r["value"],
            num(r["cases"], 0),
            num(r["resolved %"], 2),
            r["median days to resolve (KM)"],
            num(r["naive mean of resolved cases (days)"], 2),
            num(r["P(resolved within 30 days)"], 4),
        ]
        for r in rows("granularity_survival_cases")
    ]
    X["surv_cust"] = [
        [
            r["group"],
            r["value"],
            num(r["customers"], 0),
            num(r["lapsed %"], 2),
            num(r["median months to lapse"], 1),
            num(r["S(12)"], 4),
            num(r["RMST 24 months"], 2),
            num(r["logrank_p"], 5),
        ]
        for r in rows("granularity_survival_customer")
    ]
    X["lifts"] = [
        [
            r["signal"],
            num(r["months with A"], 0),
            num(r["P(B | A) %"], 2),
            num(r["P(B | not A) %"], 2),
            num(r["relative risk"], 3),
            num(r["rr_low"], 3),
            num(r["rr_high"], 3),
            num(r["p_value"], 5),
            r["business use"],
        ]
        for r in rows("granularity_lifts")
    ]
    X["agent_rel"] = [
        [
            r["KPI"],
            num(r["agents"], 0),
            num(r["split-half r"], 4),
            num(r["Spearman–Brown reliability"], 4),
            num(r["ICC (random intercept)"], 6),
        ]
        for r in rows("granularity_agent_effects")
    ]
    X["granger"] = [
        [
            r["market"],
            r["cause"],
            r["effect"],
            num(r["best lag (days)"], 0),
            num(r["p_value"], 4),
            r["significant (FDR 5 %)"] == "True",
        ]
        for r in rows("granularity_granger")
    ]
    X["cats"] = [
        [
            r["market"],
            num(r["mean HHI"], 1),
            num(r["PSI first vs last 6 months"], 6),
            num(r["p_value"], 4),
        ]
        for r in rows("granularity_categories")
    ]
    X["t_signal"] = [
        [
            r["notebook"],
            r["test"],
            num(r["p_value"], 5),
            r["reject"] == "True",
            num(r["q_value"], 5),
        ]
        for r in rows("granularity_time_signal")
    ]
    cells = []
    for r in rows("granularity_time_cells"):
        s = num(r["sends_fit"], 0) or 0
        cells.append(
            [
                r["send_channel"],
                r["promoted_product"],
                r["campaign_objective"],
                r["segment"],
                r["country_code"],
                s,
                num(r["conversions_fit"], 0),
                num(r["rate_eb"], 6),
                num(r["ev_per_send"], 3),
                r["tracked"] == "True",
                num(r["cost_per_send"], 5),
                num(r["sends_ho"], 0),
                num(r["conversions_ho"], 0),
            ]
        )
    X["cells"] = cells
    X["alloc"] = [
        [
            r["policy"],
            num(r["sends"], 0),
            num(r["conversions"], 1),
            num(r["cost"], 1),
            num(r["conversions vs actual %"], 2),
            num(r["cost vs actual %"], 2),
            num(r["sends to SMS %"], 2),
        ]
        for r in rows("granularity_time_allocation")
    ]
    return X


def main():
    mods, atlas_js, decisions = extract()
    X = extra()
    css = (SRC / "app.css").read_text()
    shell = (SRC / "shell.html").read_text()
    app = "\n".join(
        (SRC / f).read_text() for f in ("core.js", "decisions.js", "renderers.js", "start.js")
    )
    pages = (SRC / "pages.js").read_text() + "\n" + (SRC / "views.js").read_text()
    import re as _re

    ctx = _re.search(r"const CTX=(\{.*?\});\s*\n\s*const STAGE", atlas_js, _re.S).group(1)
    data = (
        "const CTX_G=" + ctx + ";\n"
        "const MODS=" + json.dumps(mods, ensure_ascii=False, separators=(",", ":")) + ";\n"
        "const X=" + json.dumps(X, ensure_ascii=False, separators=(",", ":")) + ";\n"
    )
    html = (
        "<title>BETA AID · Grain Atlas</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,600;1,8..60,400&display=swap">\n'
        f"<style>\n{css}\n</style>\n{shell}\n"
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>\n'
        '<script>\n(function(){\n"use strict";\n'
        "const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>Array.from(r.querySelectorAll(s));\n"
        'const fmt=(v,d=0)=>Number(v).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});\n'
        'const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));\n'
        "const store={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};\n"
        f"{data}\n{atlas_js}\n{decisions}\n{pages}\n{app}\n"
        "})();\n</script>\n"
    )
    out = D / "grain_atlas.html"
    out.write_text(html)
    print("wrote", out, len(html))


if __name__ == "__main__":
    main()
