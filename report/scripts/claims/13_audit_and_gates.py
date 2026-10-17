"""Chapter 13 · Audit, service levels and gates.

Reads the rule summary of the built lakehouse (audit.dq_rule_summary, the gate's input) and the per-scope SLO tables of
country_template/12, and analyses the gate as a test:

* tolerance of each rule (maximum minus observed rate) and what it takes to breach it: the share of the table that
  would have to violate the rule, and, for daily fact tables, the number of days of fully corrupted deliveries;
* for R03 on transactions, the per-day alternative: the binomial dispersion of the daily rate and the smallest daily
  rise a per-day z rule would report;
* the zero-tolerance policy rules, which breach on every run; the country re-basing of the SLOs.

    uv run python scripts/claims/13_audit_and_gates.py
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from report_lib import db
from report_lib.build import Chapter
from report_lib.paths import BUILD, REPO, TABLES
from report_lib.texgen import render_table

LAKE = REPO / "data" / "lake" / "lakehouse.duckdb"
SEED = REPO / "platform" / "dbt" / "seeds" / "dq_rule_slo.csv"
COUNTRY = REPO / "eda" / "src" / "latam_eda" / "country.py"
MAIN = REPO / "data" / "parquet"
OUT = BUILD / "sources"
THIS = REPO / "report" / "scripts" / "claims" / "13_audit_and_gates.py"
FACTS = {
    "transactions",
    "call_center_interactions",
    "complaints",
    "digital_events",
    "campaign_sends",
    "call_transcripts",
}
Z = 4.0


def gate(ch: Chapter, con) -> None:
    s = con.sql("""select rule_id, severity, table_name, violations, table_rows, rate_pct, baseline_rate_pct, max_rate_pct,
                          enforce_in_dev, slo_breached
                   from audit.dq_rule_summary where rule_id like 'R%' order by rule_id""").df()  # fmt: skip
    m = duckdb.connect()
    days = {}
    for t in FACTS:
        days[t] = m.sql(
            f"select count(distinct process_date) from '{MAIN / (t + '.parquet')}'"
        ).fetchone()[0]
    s["tolerance_pp"] = s.max_rate_pct - s.rate_pct
    live = s[(s.max_rate_pct > 0) & (s.max_rate_pct < 100) & (s.tolerance_pp > 0)].copy()
    live["share_to_breach_pct"] = 100 * live.tolerance_pp / (100 - live.rate_pct)
    live["days_to_breach"] = [
        r.share_to_breach_pct / 100 * days[r.table_name] if r.table_name in FACTS else np.nan
        for r in live.itertuples()
    ]
    live[["rule_id", "severity", "table_name", "rate_pct", "max_rate_pct", "tolerance_pp", "share_to_breach_pct",
          "days_to_breach"]].to_csv(OUT / "ch13_tolerance.csv", index=False)  # fmt: skip
    ch.count("rules", len(s), LAKE)
    ch.count("rules-live", len(live), LAKE)
    ch.count("breached", int(s.slo_breached.sum()), LAKE)
    zero = s[(s.max_rate_pct == 0) & (s.rate_pct > 0)]
    ch.count("zero-policy", len(zero), LAKE)
    ch.count("zero-policy-enforced", int(zero.enforce_in_dev.sum()), LAKE)
    for r in zero.itertuples():
        ch.census(f"rate-{r.rule_id.lower()}", float(r.rate_pct), LAKE, unit="percent", digits=3)
    facts = live[live.table_name.isin(FACTS)]
    ch.census("days-min", float(facts.days_to_breach.min()), LAKE, digits=2)
    ch.census("days-max", float(facts.days_to_breach.max()), LAKE, digits=2)
    ch.census("days-median", float(facts.days_to_breach.median()), LAKE, digits=2)
    r03 = live.set_index("rule_id").loc["R03"]
    ch.census("r03-rate", float(r03.rate_pct), LAKE, unit="percent", digits=3)
    ch.census("r03-max", float(r03.max_rate_pct), LAKE, unit="percent", digits=3)
    ch.census("r03-days", float(r03.days_to_breach), LAKE, digits=2)
    ch.count("tx-days", int(days["transactions"]), MAIN / "transactions.parquet")
    pinned = s[(s.max_rate_pct == 100) & (s.rate_pct > 0)]
    ch.count("pinned-max", len(pinned), LAKE)
    render_table(OUT / "ch13_tolerance.csv", "ch13-tolerance", "Integrity rules with a finite tolerance, from the "
                 "rule summary the gate reads: the observed rate, the maximum, the tolerance between them, the share of "
                 "the table that would have to violate the rule for the gate to breach and, for daily fact tables, the "
                 "equivalent number of days of fully corrupted deliveries.", digits=3)  # fmt: skip


def per_day(ch: Chapter, con) -> None:
    d = con.sql("""select process_date, count(*) n,
                          count(*) filter (where transaction_status = 'Approved' and response_code is null) k
                   from m_transactions group by 1 order by 1""").df()  # fmt: skip
    p = d.k.sum() / d.n.sum()
    s = d.k / d.n
    phi = float((d.n * (s - p) ** 2 / (p * (1 - p))).sum() / (len(d) - 1))
    mde = Z * np.sqrt(p * (1 - p) / d.n)
    src = MAIN / "transactions.parquet"
    ch.census("r03-dispersion", phi, src, digits=3)
    ch.census("r03-day-mde", 100 * float(np.median(mde)), src, unit="percentage points", digits=2)
    ch.census("r03-day-rows", float(d.n.median()), src)
    ch.constant("z-rule", Z, THIS)


def countries(ch: Chapter) -> None:
    rows = []
    for prefix in ("country", "backup"):
        for code in ("all", "mx", "co", "ar"):
            p = TABLES / f"{prefix}_{code}_rule_slo.csv"
            t = pd.read_csv(p)
            over = t[(t.global_max_pct > 0) & (t.country_rate_pct > t.country_max_pct)]
            rows.append({"dataset": prefix.replace("country", "main"), "scope": code.upper(), "rules": len(t),
                         "breach global maximum": int(t.breaches_global_slo.sum()),
                         "breach own maximum": len(over)})  # fmt: skip
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "ch13_countries.csv", index=False)
    main = t[t.dataset == "main"].set_index("scope")
    for sc in ("MX", "CO", "AR"):
        ch.count(f"global-breach-{sc.lower()}", int(main.loc[sc, "breach global maximum"]), TABLES / f"country_{sc.lower()}_rule_slo.csv",
                 source_type="table")  # fmt: skip
    ch.count("backup-global-breach", int(t[(t.dataset == "backup") & (t.scope == "ALL")]["breach global maximum"].iloc[0]),
             TABLES / "backup_all_rule_slo.csv", source_type="table")  # fmt: skip
    ch.constant("floor-pp", 0.1, COUNTRY)
    render_table(OUT / "ch13_countries.csv", "ch13-countries", "Integrity rules per scope and copy: rules evaluated, "
                 "rules whose rate exceeds the bank-wide maximum, and rules whose rate exceeds the scope's own re-based "
                 "maximum (country template, notebook 12).")  # fmt: skip


def main() -> None:
    con = duckdb.connect(str(LAKE), read_only=True)
    ch = Chapter(13, "ch13")
    OUT.mkdir(parents=True, exist_ok=True)
    gate(ch, con)
    per_day(ch, db.connect())
    countries(ch)
    print(f"{len(ch.claims)} claims -> {ch.write()}")


if __name__ == "__main__":
    main()
