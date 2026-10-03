"""Real-time fraud scorer.

Consumes `tx.features` (Flink window features) and `tx.logins`, completes the point-in-time feature vector
with per-customer history state (warm-started from online_features.customer_state, built by batch), scores
with the MLflow model `fraud_ensemble@champion`, and appends every decision (inputs, model version, reason
codes, latency) to the append-only decisions.fraud_decision_log and to the `tx.decisions` topic.

Feature definitions mirror dbt macro fraud_features(): expanding history uses rows strictly before the
current one; novelty flags compare against everything seen before; geo-velocity uses the previous point.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import UTC, datetime

import pandas as pd
import psycopg
from confluent_kafka import Consumer, Producer
from fastapi import FastAPI, Header, HTTPException
from prometheus_client import Counter, Histogram, start_http_server

DECISIONS = Counter("fraud_decisions_total", "Decisions by outcome", ["decision"])
LATENCY = Histogram(
    "fraud_scoring_latency_seconds",
    "Feature completion + scoring latency",
    buckets=(0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0),
)
LAG = Histogram(
    "fraud_event_to_decision_seconds", "Wall-clock delay from Kafka receipt to decision"
)

PG_DSN = (
    f"postgresql://scorer:{os.environ['SCORER_DB_PASSWORD']}@{os.environ.get('LATAM_PG_CORE_HOST', 'pg-core')}"
    f":5432/bank_serving"
)
KAFKA = os.environ.get("LATAM_KAFKA_BOOTSTRAP", "redpanda:9092")
MLFLOW_URI = os.environ.get("LATAM_MLFLOW_URI", "http://mlflow:5000")


def haversine_km(lat1, lon1, lat2, lon2) -> float | None:
    if None in (lat1, lon1, lat2, lon2) or any(
        isinstance(v, float) and math.isnan(v) for v in (lat1, lon1, lat2, lon2)
    ):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(a))


class State:
    """Per-customer expanding history (same quantities as serving_online_fraud_state)."""

    def __init__(self, conn):
        self.s: dict[str, dict] = {}
        for r in conn.execute(
            "SELECT customer_id, hist_tx_count, hist_sum_log_amount, hist_sumsq_log_amount, "
            "hist_max_amount_usd, hist_sum_hour, seen_merchants, seen_countries, seen_channels, "
            "last_tx_ts, last_lat, last_lon FROM online_features.customer_state"
        ):
            self.s[r[0]] = {
                "n": r[1] or 0,
                "sum": r[2] or 0.0,
                "sumsq": r[3] or 0.0,
                "max": r[4],
                "sum_hour": r[5] or 0.0,
                "merchants": set(r[6] or []),
                "countries": set(r[7] or []),
                "channels": set(r[8] or []),
                "last_ts": r[9],
                "last_lat": r[10],
                "last_lon": r[11],
                "last_login": None,
            }

    def features(self, f: dict) -> dict:
        st = self.s.setdefault(
            f["customer_id"],
            {
                "n": 0,
                "sum": 0.0,
                "sumsq": 0.0,
                "max": None,
                "sum_hour": 0.0,
                "merchants": set(),
                "countries": set(),
                "channels": set(),
                "last_ts": None,
                "last_lat": None,
                "last_lon": None,
                "last_login": None,
            },
        )
        ts = datetime.fromisoformat(f["anchor_ts"].replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        amt = float(f["amount_usd"] or 0.0)
        log_amount = math.log1p(amt)
        n = st["n"]
        mean = st["sum"] / n if n else None
        std = math.sqrt(max((st["sumsq"] - n * mean * mean) / (n - 1), 0.0)) if n > 1 else None
        last_ts = st["last_ts"]
        if last_ts is not None and last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=UTC)
        hours_prev = (ts - last_ts).total_seconds() / 3600.0 if last_ts else None
        km = haversine_km(st["last_lat"], st["last_lon"], f.get("latitude"), f.get("longitude"))
        login = st["last_login"]
        feats = {
            "log_amount": log_amount,
            "tx_count_1h": f["tx_count_1h"],
            "tx_count_24h": f["tx_count_24h"],
            "tx_count_7d": f["tx_count_7d"],
            "amount_usd_24h": f["amount_usd_24h"] or 0.0,
            "declines_24h": f["declines_24h"],
            "amount_zscore_vs_history": (log_amount - mean) / std if std else None,
            "amount_to_hist_max": amt / st["max"] if st["max"] else None,
            "hour_deviation": abs(f["local_hour"] - st["sum_hour"] / n) if n else None,
            "hours_since_prev_tx": hours_prev,
            "is_dormant_reactivation": float(hours_prev is not None and hours_prev >= 90 * 24),
            "is_new_merchant": float(
                n > 0
                and f.get("merchant_name") is not None
                and f["merchant_name"] not in st["merchants"]
            ),
            "is_new_country": float(n > 0 and f["transaction_country_code"] not in st["countries"]),
            "is_cross_border": float(f["transaction_country_code"] != f["customer_country_code"]),
            "is_night": float(0 <= f["local_hour"] <= 5),
            "implied_speed_kmh": km / max(hours_prev, 1 / 60)
            if km is not None and hours_prev is not None
            else None,
            "minutes_since_last_login": (ts - login).total_seconds() / 60
            if login and login <= ts
            else None,
        }
        # update state AFTER computing features (strictly-prior semantics)
        st["n"] += 1
        st["sum"] += log_amount
        st["sumsq"] += log_amount**2
        st["sum_hour"] += f["local_hour"]
        st["max"] = max(st["max"] or 0.0, amt)
        if f.get("merchant_name"):
            st["merchants"].add(f["merchant_name"])
        st["countries"].add(f["transaction_country_code"])
        st["channels"].add(f["channel"])
        st["last_ts"] = ts
        if f.get("latitude") is not None:
            st["last_lat"], st["last_lon"] = f["latitude"], f["longitude"]
        return feats


class Scorer:
    def __init__(self):
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_URI)
        while True:  # wait for an approved champion
            try:
                self.model = mlflow.pyfunc.load_model("models:/fraud_ensemble@champion")
                mv = mlflow.MlflowClient().get_model_version_by_alias("fraud_ensemble", "champion")
                self.model_version = mv.version
                break
            except Exception as exc:
                print(f"[scorer] waiting for fraud_ensemble@champion: {exc}", flush=True)
                time.sleep(15)
        self.conn = psycopg.connect(PG_DSN, autocommit=True)
        self.state = State(self.conn)
        self.producer = Producer({"bootstrap.servers": KAFKA})
        self.buffer: list[tuple] = []
        print(
            f"[scorer] model v{self.model_version} loaded, state for {len(self.state.s)} customers",
            flush=True,
        )

    def score_features(self, feats: dict) -> dict:
        out = self.model.predict(pd.DataFrame([feats]))
        row = out.iloc[0]
        return {
            "risk_score": float(row.risk_score),
            "decision": row.decision,
            "reason_codes": [c for c in str(row.reason_codes).split(",") if c],
        }

    def handle(self, f: dict, received: float) -> None:
        t0 = time.perf_counter()
        feats = self.state.features(f)
        res = self.score_features(feats)
        latency = time.perf_counter() - t0
        LATENCY.observe(latency)
        LAG.observe(time.time() - received)
        DECISIONS.labels(res["decision"]).inc()
        self.buffer.append(
            (
                f["transaction_id"],
                f["customer_id"],
                f["anchor_ts"],
                res["decision"],
                res["risk_score"],
                res["reason_codes"],
                f"models:/fraud_ensemble/{self.model_version}",
                str(self.model_version),
                json.dumps(
                    {
                        **feats,
                        "flink": {k: f[k] for k in ("tx_count_1h", "tx_count_24h", "tx_count_7d")},
                    }
                ),
                latency * 1000,
            )
        )
        self.producer.produce(
            "tx.decisions",
            key=f["transaction_id"],
            value=json.dumps({"transaction_id": f["transaction_id"], **res}),
        )
        if len(self.buffer) >= 200:
            self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO decisions.fraud_decision_log (transaction_id, customer_id, event_ts, decision, "
                "risk_score, reason_codes, model_uri, model_version, feature_snapshot, latency_ms) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                self.buffer,
            )
        self.buffer.clear()
        self.producer.flush(5)

    def run(self) -> None:
        c = Consumer(
            {
                "bootstrap.servers": KAFKA,
                "group.id": "fraud-scorer",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": True,
            }
        )
        c.subscribe(["tx.logins", "tx.features"])
        last_flush = time.time()
        while True:
            msg = c.poll(0.5)
            if msg is not None and not msg.error() and msg.value():
                v = json.loads(msg.value())
                if msg.topic() == "tx.logins":
                    ts = datetime.fromisoformat(v["event_ts_utc"].replace("Z", "+00:00"))
                    st = self.state.s.get(v["customer_id"])
                    if st is not None:
                        st["last_login"] = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
                elif not v.get(
                    "is_warmup"
                ):  # warm-up rows only fill Flink windows; state already has them
                    self.handle(v, time.time())
            if time.time() - last_flush > 1:
                self.flush()
                last_flush = time.time()


app = FastAPI(title="fraud-scorer")
SCORER: Scorer | None = None


@app.get("/health")
def health():
    return {"ok": SCORER is not None, "model_version": getattr(SCORER, "model_version", None)}


@app.post("/score")
def score(features: dict, x_request_id: str | None = Header(default=None)):
    """Synchronous scoring of a complete feature vector (behind Kong: key auth, rate limit, request id)."""
    if SCORER is None:
        raise HTTPException(503, "model not loaded")
    res = SCORER.score_features(features)
    return {**res, "model_version": SCORER.model_version, "request_id": x_request_id}


def main() -> None:
    global SCORER
    import uvicorn

    start_http_server(9108)
    threading.Thread(
        target=lambda: uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning"), daemon=True
    ).start()
    SCORER = Scorer()
    SCORER.run()


if __name__ == "__main__":
    main()
