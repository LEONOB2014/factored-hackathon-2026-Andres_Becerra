# 13 · Data readiness: an audit of the data collection process

[← 12 from evidence to build plan](12_development_path.md) · [index](README.md) · next: [sources →](appendix_sources.md)

Chapter 12 decided that every model is gated by evidence ([ADR-012](../platform/adr/ADR-012.md)). The hour-grain
series (`eda/notebooks/granularity_hour/`) applied that rule to the finest grain the data has.

**What the series did:**
- re-grained every fact table to the hour of its own delivery clock;
- redesigned the dimensions the hour needs;
- trained every candidate model of every scenario, **whether or not the data could support it**.

**The result:**
- 11 models: **0 green, 2 amber, 9 red**;
- 52 hypothesis tests: 9 survive the false-discovery correction, and only 1 is material (and it is mechanical).

A red model is not a failed experiment. It is a precise statement of what the data collection process must change.
This chapter turns the scorecard into that audit.

## 13.1 Why the models are red

| root cause | meaning | models |
|---|---|---|
| generator independence | the source draws each process independently and at uniform times, so features cannot explain targets | dormancy from the time-of-day profile; daypart of the next transaction; hourly volume per market × channel; branch-hour ATM cash; hourly contact arrivals; time to first response; SLA breach at creation; open within 24 h by send hour |
| data defect | a collected field contradicts the activity it describes | teller transaction outside opening hours (59 % of teller activity falls outside the branch's own hours, exactly what schedule-blind activity gives) |
| missing field (amber today) | the measure a model needs is not collected | handle time per agent-hour (no rosters or agent states) |
| significant but not material (amber) | the method detects a real but negligible effect | session purchase from the event sequence (+0.005 AUC over length); handle time (+0.1 % of the error) |

The two amber models matter: they show that the pipeline detects small effects when they exist. The reds are the
data's limit, not the method's.

### Facts the hour grain established (notebooks 01–07)

**Behaviour (from the tests):**
- no customer has a preferred hour: 1.05 % reject at 1 %, against 1 % by chance;
- no channel has an intraday rhythm: Cohen's w at most 0.04;
- no decline rate depends on the hour;
- send-to-open delays are uniform over 7 days;
- events inside a session are in random order: Cramér's V 0.001.

**Workforce:**
- the agent `work_shift` label is unrelated to the hours worked: Morning agents handle 33.4 % of contacts in the
  morning, against 33.3 % by chance;
- 1,200 agents share about 625 contacts a day.

**Complaints:**
- the bank's SLA flag does not follow the regulatory clock: Cohen's κ ≈ 0 in every country;
- priority does not change the time to first response.

## 13.2 What the source must collect

| requirement | owner | unlocks | acceptance test on a new feed |
|---|---|---|---|
| declared clock and delivery window per timestamp ([ADR-014](../platform/adr/ADR-014.md)); true local timestamps | data platform (source contract) | customer time-of-day profiles, hourly forecasts, every calendar feature | clock scan: hour × weekday χ²/dof ≈ 1 at the declared offset; a daily rhythm with Cohen's w > 0.1 |
| branch opening days and hours, holiday closures; a teller or terminal id per transaction | branch network operations | the teller-outside-hours control; branch staffing | teller transactions outside the declared schedule < 0.5 % |
| ATM terminal events (dispense, replenishment, out-of-service) | cash logistics | intraday cash and replenishment timing | terminal dispenses reconcile to the ledger; an intraday dispense profile with w > 0.1 |
| rostered shifts per agent and day; agent state logs (logged in, available, on call, break) | workforce management | occupancy, adherence, required against rostered agents, handle-time models | ≥ 95 % of contacts inside the agent's rostered hours; state logs cover every contact |
| telephony queue events (offered, answered, abandoned per interval) | contact-centre telephony | queue arrival forecasts, abandonment, Erlang staffing | queue events reconcile to interactions per interval |
| case assignment events, queue capacity, the regulatory deadline per case type and country | complaints management, compliance | time-to-response models; a reportable breach KPI | the SLA flag agrees with the business-day clock (κ > 0.9); `origin_interaction_id` populated |
| clickstream in true order, with page, product and funnel step per event | digital analytics | session funnel and drop-off models | transitions between event types depart from independence (Cramér's V > 0.1) |
| open tracking for every channel; randomised send times and holdouts | marketing technology | send-time optimisation; uplift | send-to-open delay departs from uniform (KS); a randomised send-time arm per campaign |

## 13.3 The re-evaluation loop

1. **Delivery.** A source owner delivers a requirement, which lands in bronze under its contract.
2. **Acceptance.** The acceptance test above runs on the first weeks of the feed. If it fails, the requirement has not
   arrived, whatever the ticket says.
3. **Re-scoring.** `eda/scripts/readiness_check.py --dataset <d> --scope <s>` re-runs the scorecard. It reproduces
   `granularity_hour_readiness.csv` byte for byte on the same data. A gate turns green only when the out-of-time gain
   over the benchmark has an interval above zero and reaches the materiality threshold.
4. **Promotion.** A green gate opens the ADR-012 path: model card, one-feature benchmark, out-of-time evaluation with
   intervals, and a monitoring plan. An amber gate stays a KPI or a rule.
5. **Reporting.** The share of green gates is a data-office KPI, reported each quarter. It measures the data collection
   process, not the data science team.

## 13.4 What is deterministic, and ships now

Some hour-grain products need no model, so they do not wait for the audit:
- the declared clocks (`dim_process_clock`, `dim_time_of_day`);
- the regulatory case clock (`fct_case_clock` with business hours and a deadline seed per country);
- the teller-outside-hours integrity rule;
- hourly monitors in the streaming layer (Poisson limits for small channels, negative-binomial for market totals).

They are listed in [12 §12.7](12_development_path.md).
