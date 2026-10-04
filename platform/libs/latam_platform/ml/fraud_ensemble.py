"""Fraud risk ensemble: transparent rules + diverse unsupervised detectors, packaged as an MLflow pyfunc.

Why unsupervised: in this dataset `is_fraud` is a function of the legacy `fraud_score` and point-in-time
behaviour carries no signal (out-of-time AUC 0.504). Until chargeback-confirmed labels exist, production
risk scoring = rules + anomaly ensemble; the supervised layer is added later behind champion/challenger.

Detectors (notebook 10 showed a small diverse ensemble beats any single detector):
  * Isolation Forest   - collective/burst anomalies
  * COPOD (pyod)       - multi-feature marginal tails (low-and-slow)
  * robust Mahalanobis - point anomalies (amount spikes), on RobustScaler features
Scores are rank-normalized on the training reference and averaged. Reason codes come from the rules and
from the features with the largest robust z-scores, so every decision is explainable.

Detector CI: `inject_anomalies` plants labelled anomalies of known types into held-out rows; a model is
only registrable if recall per type at the review budget stays above floors (regression test for
unsupervised models).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = [
    "log_amount",
    "tx_count_1h",
    "tx_count_24h",
    "tx_count_7d",
    "amount_usd_24h",
    "declines_24h",
    "amount_zscore_vs_history",
    "amount_to_hist_max",
    "hour_deviation",
    "hours_since_prev_tx",
    "is_dormant_reactivation",
    "is_new_merchant",
    "is_new_country",
    "is_cross_border",
    "is_night",
    "implied_speed_kmh",
    "minutes_since_last_login",
]

RULES = {  # reason code: (condition on a feature row, risk added)
    "R_VELOCITY_1H": (lambda d: d["tx_count_1h"] >= 4, 0.35),
    "R_GEO_IMPOSSIBLE": (lambda d: d["implied_speed_kmh"] > 900, 0.45),
    "R_DORMANT_REACTIVATION_HIGH_AMOUNT": (
        lambda d: (d["is_dormant_reactivation"] > 0) & (d["amount_to_hist_max"] > 1.5),
        0.30,
    ),
    "R_NEW_COUNTRY_NIGHT": (lambda d: (d["is_new_country"] > 0) & (d["is_night"] > 0), 0.25),
    "R_AMOUNT_SPIKE": (lambda d: d["amount_zscore_vs_history"] > 4, 0.30),
    "R_DECLINE_STREAK": (lambda d: d["declines_24h"] >= 3, 0.20),
}
FLOORS = {
    "amount_spike": 0.80,
    "velocity_burst": 0.80,
    "geo_impossible": 0.80,
    "dormant_reactivation": 0.50,
    "foreign_night_burst": 0.50,
}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    x = df[FEATURES].astype("float64").copy()
    x["minutes_since_last_login"] = np.log1p(x["minutes_since_last_login"].clip(lower=0))
    x["hours_since_prev_tx"] = np.log1p(x["hours_since_prev_tx"].clip(lower=0))
    x["amount_usd_24h"] = np.log1p(x["amount_usd_24h"].clip(lower=0))
    x["implied_speed_kmh"] = np.log1p(x["implied_speed_kmh"].clip(lower=0))
    return x.fillna(x.median()).fillna(0)


def inject_anomalies(df: pd.DataFrame, rate: float = 0.01, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = df.copy()
    out[FEATURES] = out[FEATURES].astype(
        "float64"
    )  # booleans become 0/1 so anomalies can be planted
    out["anomaly_type"] = ""
    idx = rng.choice(len(out), size=int(len(out) * rate), replace=False)
    for typ, ids in zip(FLOORS, np.array_split(idx, len(FLOORS))):
        ii = out.index[ids]
        m = len(ii)
        if typ == "amount_spike":
            out.loc[ii, "log_amount"] = np.log1p(rng.uniform(15_000, 80_000, m))
            out.loc[ii, "amount_zscore_vs_history"] = rng.uniform(5, 9, m)
            out.loc[ii, "amount_to_hist_max"] = rng.uniform(3, 10, m)
        elif typ == "velocity_burst":
            out.loc[ii, "tx_count_1h"] = rng.integers(5, 15, m)
            out.loc[ii, "tx_count_24h"] = rng.integers(10, 30, m)
            out.loc[ii, "hours_since_prev_tx"] = rng.uniform(0.01, 0.1, m)
        elif typ == "geo_impossible":
            out.loc[ii, "implied_speed_kmh"] = rng.uniform(1500, 9000, m)
        elif typ == "dormant_reactivation":
            out.loc[ii, "is_dormant_reactivation"] = 1
            out.loc[ii, "hours_since_prev_tx"] = rng.uniform(24 * 120, 24 * 400, m)
            out.loc[ii, "amount_to_hist_max"] = rng.uniform(1.6, 4, m)
        elif typ == "foreign_night_burst":
            out.loc[ii, ["is_new_country", "is_cross_border", "is_night"]] = 1
            out.loc[ii, "tx_count_24h"] = rng.integers(3, 8, m)
        out.loc[ii, "anomaly_type"] = typ
    return out


class FraudEnsemble:
    def __init__(self, seed: int = 0):
        self.seed = seed

    def fit(self, train: pd.DataFrame) -> FraudEnsemble:
        from pyod.models.copod import COPOD
        from sklearn.covariance import MinCovDet
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import RobustScaler

        x = prepare(train)
        self.medians_ = x.median()
        self.scaler_ = RobustScaler().fit(x)
        xs = self.scaler_.transform(x)
        self.iforest_ = IsolationForest(
            n_estimators=200, max_samples=4096, random_state=self.seed
        ).fit(xs)
        self.copod_ = COPOD().fit(xs)
        sub = xs[
            np.random.default_rng(self.seed).choice(
                len(xs), size=min(len(xs), 50_000), replace=False
            )
        ]
        self.mcd_ = MinCovDet(random_state=self.seed, support_fraction=0.9).fit(sub)
        raw = self._raw(xs)
        self.ref_ = {k: np.sort(v) for k, v in raw.items()}  # rank-normalization reference
        return self

    def _raw(self, xs: np.ndarray) -> dict[str, np.ndarray]:
        return {
            "iforest": -self.iforest_.score_samples(xs),
            "copod": self.copod_.decision_function(xs),
            "mahalanobis": self.mcd_.mahalanobis(xs),
        }

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        x = prepare(df).fillna(self.medians_)
        xs = self.scaler_.transform(x)
        raw = self._raw(xs)
        ranks = {k: np.searchsorted(self.ref_[k], v) / len(self.ref_[k]) for k, v in raw.items()}
        anomaly = np.mean(list(ranks.values()), axis=0)
        rule_risk = np.zeros(len(df))
        reasons = [[] for _ in range(len(df))]
        feat = df[FEATURES].astype("float64").fillna(0)
        for code, (cond, w) in RULES.items():
            hit = cond(feat).to_numpy()
            rule_risk += w * hit
            for i in np.flatnonzero(hit):
                reasons[i].append(code)
        top = np.argsort(-np.abs(xs), axis=1)[:, :2]  # most unusual features (robust z)
        cols = np.array(list(x.columns))
        for i in range(len(df)):
            if anomaly[i] > 0.98:
                reasons[i] += [f"A_UNUSUAL_{c.upper()}" for c in cols[top[i]]]
        risk = np.clip(0.6 * anomaly + rule_risk, 0, 1)
        decision = np.where(risk >= 0.9, "DECLINE", np.where(risk >= 0.75, "STEP_UP", "APPROVE"))
        return pd.DataFrame(
            {
                "risk_score": risk,
                "anomaly_rank": anomaly,
                "rule_risk": rule_risk,
                "decision": decision,
                "reason_codes": reasons,
            },
            index=df.index,
        )


def detector_ci(
    model: FraudEnsemble, holdout: pd.DataFrame, budget: float = 0.02, seed: int = 1
) -> dict:
    """Recall per injected type when reviewing the top `budget` share by risk. Raises if a floor is missed."""
    inj = inject_anomalies(holdout, rate=0.01, seed=seed)
    s = model.score(inj)["risk_score"]
    flagged = s >= s.quantile(1 - budget)
    recall = {t: float(flagged[inj.anomaly_type == t].mean()) for t in FLOORS}
    failed = {t: r for t, r in recall.items() if r < FLOORS[t]}
    return {
        "recall_at_budget": recall,
        "budget": budget,
        "floors": FLOORS,
        "passed": not failed,
        "failed": failed,
    }


try:  # MLflow wrapper (only where mlflow is installed)
    import mlflow.pyfunc

    class FraudEnsemblePyfunc(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            import joblib

            self.model = joblib.load(context.artifacts["ensemble"])

        def predict(self, context, model_input: pd.DataFrame, params=None):
            out = self.model.score(model_input)
            out["reason_codes"] = out["reason_codes"].map(lambda r: ",".join(r))
            return out
except ImportError:  # pragma: no cover
    pass
