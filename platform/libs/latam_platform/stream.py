"""Streaming demo helpers: holdout export, topic setup, event-time replay, Flink SQL Gateway submission and
the stream/batch parity check."""

from __future__ import annotations

import json
import re
import time

from latam_platform import config

TX_FIELDS = [
    "transaction_id",
    "customer_id",
    "product_id",
    "transaction_ts_utc",
    "amount_usd",
    "transaction_type",
    "channel",
    "transaction_category",
    "merchant_name",
    "transaction_country_code",
    "customer_country_code",
    "transaction_status",
    "local_hour",
    "is_weekend",
    "product_family",
    "latitude",
    "longitude",
    "is_warmup",
]
WARMUP_DAYS = 7  # longest feature window: Flink must see the week before the cutoff to match batch
STREAM_DIR = config.LAKE / "stream"


def export_holdout(con, days: int | None = None) -> dict:
    """Write the enriched holdout transactions and logins (event-time ordered) for the replayer."""
    STREAM_DIR.mkdir(parents=True, exist_ok=True)
    window = (
        f"and transaction_ts_utc < timestamp '{config.STREAM_CUTOFF}' + interval {days} day"
        if days
        else ""
    )
    cols = ", ".join(c for c in TX_FIELDS if c != "is_warmup")
    # warm-up rows (last WARMUP_DAYS of history) fill Flink's windows; they are never scored
    con.sql(f"""copy (select {cols}, _zone = 'bronze' as is_warmup from silver.int_transactions_enriched_with_holdout
                      where (_zone = 'holdout' {window})
                         or (_zone = 'bronze' and transaction_ts_utc >= timestamp '{config.STREAM_CUTOFF}' - interval {WARMUP_DAYS} day)
                      order by transaction_ts_utc)
                to '{STREAM_DIR}/holdout_transactions.parquet' (format parquet)""")
    lwin = window.replace("transaction_ts_utc", "event_ts_utc")
    con.sql(f"""copy (select customer_id, event_ts_utc from silver.stg_digital_events_holdout
                      where event_type = 'Login' and customer_id is not null {lwin} order by event_ts_utc)
                to '{STREAM_DIR}/holdout_logins.parquet' (format parquet)""")
    n_tx = con.sql(
        f"select count(*) filter (where not is_warmup) from '{STREAM_DIR}/holdout_transactions.parquet'"
    ).fetchone()[0]
    n_lg = con.sql(f"select count(*) from '{STREAM_DIR}/holdout_logins.parquet'").fetchone()[0]
    return {"transactions": n_tx, "logins": n_lg}


def ensure_topics(bootstrap: str, recreate: bool = True) -> list[str]:
    """Each demo run starts from empty topics so Flink windows never mix events from a previous replay."""
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap})
    wanted = {"tx.raw": 3, "tx.logins": 1, "tx.features": 3, "tx.decisions": 3}
    existing = set(admin.list_topics(timeout=10).topics)
    if recreate and existing & set(wanted):
        for f in admin.delete_topics(sorted(existing & set(wanted))).values():
            f.result()
        time.sleep(3)
        existing = set(admin.list_topics(timeout=10).topics)
    new = [
        NewTopic(t, num_partitions=p, replication_factor=1)
        for t, p in wanted.items()
        if t not in existing
    ]
    for f in admin.create_topics(new).values() if new else []:
        f.result()
    return sorted(wanted)


def replay(bootstrap: str, seconds_per_day: float = 30.0, max_events: int | None = None) -> dict:
    """Publish logins and transactions merged in event-time order, paced at `seconds_per_day` per data day."""
    import duckdb
    from confluent_kafka import Producer

    tx = duckdb.sql(
        f"select *, transaction_ts_utc as ts, 'tx' as kind from '{STREAM_DIR}/holdout_transactions.parquet'"
    ).df()
    lg = duckdb.sql(
        f"select customer_id, event_ts_utc as ts, 'login' as kind from '{STREAM_DIR}/holdout_logins.parquet'"
    ).df()
    import pandas as pd

    ev = pd.concat([lg, tx], ignore_index=True).sort_values(["ts", "kind"]).reset_index(drop=True)
    if max_events:
        ev = ev.head(max_events)
    p = Producer(
        {"bootstrap.servers": bootstrap, "linger.ms": 20, "acks": "all", "enable.idempotence": True}
    )
    t0, data_t0 = time.time(), ev.ts.iloc[0]
    sent = {"tx": 0, "login": 0}
    for row in ev.itertuples(index=False):
        due = t0 + (row.ts - data_t0).total_seconds() / 86400.0 * seconds_per_day
        delay = due - time.time()
        if delay > 0:
            time.sleep(min(delay, 1.0))
        if row.kind == "login":
            p.produce(
                "tx.logins",
                key=row.customer_id,
                value=json.dumps(
                    {"customer_id": row.customer_id, "event_ts_utc": row.ts.isoformat()}
                ),
            )
        else:
            rec = {k: getattr(row, k) for k in TX_FIELDS}
            rec["transaction_ts_utc"] = row.ts.isoformat(timespec="milliseconds")
            rec = {k: (None if isinstance(v, float) and v != v else v) for k, v in rec.items()}
            p.produce("tx.raw", key=row.customer_id, value=json.dumps(rec, default=str))
        sent[row.kind] += 1
        p.poll(0)
    flush_watermark(p, ev.ts.max())
    p.flush(30)
    return {
        **sent,
        "wall_seconds": round(time.time() - t0, 1),
        "data_span": [str(ev.ts.min()), str(ev.ts.max())],
    }


def flush_watermark(producer, last_ts, partitions: int = 3) -> None:
    """Event-time windows close only when the watermark passes them. After a finite replay the source goes idle, so
    one sentinel per partition, timestamped beyond the longest window and marked warm-up (never stored or scored),
    advances the watermark and makes Flink emit the last real transactions."""
    import pandas as pd

    ts = (pd.Timestamp(last_ts) + pd.Timedelta(days=8)).isoformat(timespec="milliseconds")
    for part in range(partitions):
        rec = dict.fromkeys(TX_FIELDS)
        rec.update(
            {
                "transaction_id": f"__watermark_{part}_{ts}",
                "customer_id": f"__watermark_{part}",
                "transaction_ts_utc": ts,
                "amount_usd": 0.0,
                "transaction_status": "Approved",
                "local_hour": 0,
                "transaction_country_code": "XX",
                "customer_country_code": "XX",
                "is_warmup": True,
            }
        )
        producer.produce("tx.raw", key=rec["customer_id"], value=json.dumps(rec), partition=part)


def _split_statements(sql: str) -> list[str]:
    sql = re.sub(r"(?m)^\s*--.*$", "", sql)
    out, buf, in_set = [], [], False
    for line in sql.splitlines():
        if line.strip().upper().startswith("EXECUTE STATEMENT SET"):
            in_set = True
        buf.append(line)
        if line.strip().endswith(";") and (not in_set or line.strip().upper() == "END;"):
            stmt = "\n".join(buf).strip().rstrip(";")
            if stmt:
                out.append(stmt)
            buf, in_set = [], False
    return out


def submit_flink_sql(gateway: str, sql_path: str, secrets: dict) -> list[dict]:
    """Submit a SQL script to the Flink SQL Gateway REST API (one session, statements in order)."""
    import requests

    sql = open(sql_path).read()
    for k, v in secrets.items():
        sql = sql.replace("${" + k + "}", v)
    sess = requests.post(
        f"{gateway}/v1/sessions", json={"sessionName": "fraud-features"}, timeout=30
    ).json()["sessionHandle"]
    results = []
    for stmt in _split_statements(sql):
        op = requests.post(
            f"{gateway}/v1/sessions/{sess}/statements", json={"statement": stmt}, timeout=60
        ).json()
        handle = op["operationHandle"]
        for _ in range(60):
            st = requests.get(
                f"{gateway}/v1/sessions/{sess}/operations/{handle}/status", timeout=30
            ).json()["status"]
            if st in ("FINISHED", "ERROR"):
                break
            time.sleep(1)
        if st == "ERROR":
            err = requests.get(
                f"{gateway}/v1/sessions/{sess}/operations/{handle}/result/0", timeout=30
            ).json()
            raise RuntimeError(f"Flink statement failed: {stmt[:80]}... -> {json.dumps(err)[:800]}")
        results.append({"statement": stmt.split("\n")[0][:80], "status": st})
    return results


def parity(con_lake, pg_conn, tol: float = 1e-6) -> dict:
    """Compare Flink window features (Postgres) with the dbt batch reference for every replayed transaction."""
    rows = pg_conn.execute("""select transaction_id, tx_count_1h, tx_count_24h, tx_count_7d, amount_usd_24h, declines_24h
                              from online_features.tx_window_features""").fetchall()
    import pandas as pd

    flink = pd.DataFrame(
        rows,
        columns=[
            "transaction_id",
            "tx_count_1h",
            "tx_count_24h",
            "tx_count_7d",
            "amount_usd_24h",
            "declines_24h",
        ],
    )
    con_lake.register("flink", flink)
    res = (
        con_lake.sql(f"""
        select count(*) as compared,
               count(*) filter (where f.tx_count_1h <> b.tx_count_1h) as diff_1h,
               count(*) filter (where f.tx_count_24h <> b.tx_count_24h) as diff_24h,
               count(*) filter (where f.tx_count_7d <> b.tx_count_7d) as diff_7d,
               count(*) filter (where abs(f.amount_usd_24h - b.amount_usd_24h) > {tol} * greatest(1, b.amount_usd_24h)) as diff_amount_24h,
               count(*) filter (where f.declines_24h <> b.declines_24h) as diff_declines_24h
        from flink f join features.feat_fraud_stream_parity b using (transaction_id)""")
        .df()
        .iloc[0]
        .to_dict()
    )
    res = {k: int(v) for k, v in res.items()}
    res["mismatches"] = sum(v for k, v in res.items() if k.startswith("diff"))
    return res
