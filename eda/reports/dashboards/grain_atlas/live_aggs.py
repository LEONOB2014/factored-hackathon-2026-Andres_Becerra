"""Aggregate counts for the Grain Atlas charts: no identifiers, only counts by hour, day and bucket.

Usage (from eda/, needs the git-ignored dataset):
  uv run python reports/dashboards/grain_atlas/live_aggs.py ../data/parquet \
      reports/dashboards/grain_atlas/aggregates.json

Every process is placed on its delivery-day clock (ADR-014): transactions, digital events and sends at -6 h,
contacts and complaints at -8 h.
"""

import json
import sys
from pathlib import Path

import duckdb

P = Path(sys.argv[1])  # data/parquet
OUT = Path(sys.argv[2])
c = duckdb.connect()
c.sql("set threads=8")


def q(sql):
    return c.sql(sql.replace("{P}", str(P))).fetchall()


out = {}
procs = {
    "transactions": ("transaction_date", 6),
    "digital_events": ("event_date", 6),
    "campaign_sends": ("send_date", 6),
    "call_center_interactions": ("interaction_date", 8),
    "complaints": ("creation_date", 8),
}
# hour-of-day profile per process: raw UTC hour and business-clock hour
out["hour_profile"] = {}
for t, (col, off) in procs.items():
    biz = q(
        f"select hour({col} - interval {off} hour) h, count(*) from '{{P}}/{t}.parquet' group by 1 order by 1"
    )
    raw = q(f"select hour({col}) h, count(*) from '{{P}}/{t}.parquet' group by 1 order by 1")
    out["hour_profile"][t] = {"biz": [n for _, n in biz], "raw": [n for _, n in raw]}

# hour x weekday on the business clock, and on raw UTC, for transactions and contacts
out["hour_weekday"] = {}
for t in ("transactions", "call_center_interactions"):
    col, off = procs[t]
    for clock, o in (("biz", off), ("raw", 0)):
        rows = q(
            f"select isodow({col} - interval {o} hour) d, hour({col} - interval {o} hour) h, count(*) "
            f"from '{{P}}/{t}.parquet' group by 1, 2 order by 1, 2"
        )
        m = [[0] * 24 for _ in range(7)]
        for d, h, n in rows:
            m[d - 1][h] = n
        out["hour_weekday"][f"{t}:{clock}"] = m

# transactions per business day and country (country of the customer)
rows = q(
    """select cu.country, cast(t.transaction_date - interval 6 hour as date) d, count(*)
       from '{P}/transactions.parquet' t join '{P}/customers.parquet' cu using (customer_id)
       group by 1, 2 order by 1, 2"""
)
daily = {}
for cty, d, n in rows:
    daily.setdefault(cty, []).append([d.isoformat(), n])
out["daily_tx"] = daily

# contacts per business day (bank-wide)
out["daily_contacts"] = [
    [d.isoformat(), n]
    for d, n in q(
        "select cast(interaction_date - interval 8 hour as date) d, count(*) "
        "from '{P}/call_center_interactions.parquet' group by 1 order by 1"
    )
]

# teller (Branch channel) transactions by business hour, Monday to Friday, and the share of branches open
out["teller_hour"] = [
    n
    for _, n in q(
        """select hour(transaction_date - interval 6 hour) h, count(*) from '{P}/transactions.parquet'
           where channel = 'Branch' and isodow(transaction_date - interval 6 hour) <= 5 group by 1 order by 1"""
    )
]
out["branch_open_frac"] = [
    v
    for _, v in q(
        """with h as (select range h from range(24))
           select h.h, avg(case when make_time(h.h, 30, 0) >= opening_time and make_time(h.h, 30, 0) < closing_time
                                 then 1 else 0 end)
           from h cross join '{P}/branches.parquet' b group by 1 order by 1"""
    )
]

# contacts by business hour per declared shift of the agent
rows = q(
    """select a.work_shift, hour(i.interaction_date - interval 8 hour) h, count(*)
       from '{P}/call_center_interactions.parquet' i join '{P}/service_agents.parquet' a using (agent_id)
       group by 1, 2 order by 1, 2"""
)
shift = {}
for s, h, n in rows:
    shift.setdefault(s, [0] * 24)[h] = n
out["shift_hour"] = shift

# send to open delay, 6-hour bins over 0..168 h
rows = q(
    """select floor(date_diff('minute', send_date, open_date) / 360.0) b, count(*)
       from '{P}/campaign_sends.parquet' where was_opened and open_date is not null and open_date >= send_date
       group by 1 order by 1"""
)
out["open_delay_6h"] = [[int(b), n] for b, n in rows if b is not None and b < 40]

# complaint milestones in hours: deciles of assignment and first response
for name, col in (("assign", "assignment_date"), ("first_response", "first_response_date")):
    r = q(
        f"""select quantile_cont(date_diff('minute', creation_date, {col}) / 60.0, [0.1,0.25,0.5,0.75,0.9])
            from '{{P}}/complaints.parquet' where {col} is not null and {col} >= creation_date"""
    )[0][0]
    out[f"case_{name}_q"] = [round(x, 1) for x in r]

# complaints: SLA flag by resolution days bucket (for the kappa story)
out["sla_by_days"] = [
    [int(b), n, k]
    for b, n, k in q(
        """select least(cast(floor(resolution_days) as int), 40) b, count(*), sum(case when sla_breached then 1 else 0 end)
           from '{P}/complaints.parquet' where resolution_days is not null group by 1 order by 1"""
    )
]

OUT.write_text(json.dumps(out, separators=(",", ":")))
print("wrote", OUT, OUT.stat().st_size)
