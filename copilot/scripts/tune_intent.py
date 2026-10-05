"""Tune the intent classifier with Optuna, track every trial in MLflow, and score the winner on the held-out set.

* search: C, character n-gram range, sublinear tf, class weights;
* objective: macro-F1 of grouped 5-fold cross-validation on the training corpus, where a group is one base phrasing
  and all its variants, so no fold trains on a variant of a sentence it scores;
* confidence threshold: the lowest out-of-fold confidence above which the model is at least 90 % accurate; below it
  the copilot asks Claude (or the customer) instead of guessing;
* held-out report (eval/intent_test.yaml, written before tuning and never used to choose anything): accuracy,
  macro-F1, expected calibration error and latency, against the keyword baseline and, with an API key, Claude
  zero-shot.

    cd copilot && uv sync --extra tune
    MLFLOW_TRACKING_URI=http://127.0.0.1:5001 uv run python scripts/tune_intent.py --trials 40
Writes corpus/intent_params.json (read at start-up) and eval/reports/intent_model.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import UTC, datetime

import mlflow
import numpy as np
import optuna
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold

from copilot.config import PROJECT, Settings
from copilot.intent import PARAMS_FILE, KeywordRouter, build, test_set, training_set

REPORTS = PROJECT / "eval" / "reports"
# 90 %: a wrong intent below this cannot act on its own (every A2 action needs an explicit confirmation, and A3
# only routes to a person), so the threshold trades clarifying questions against Claude calls, not safety.
TARGET_PRECISION = 0.90


def ece(conf: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def oof(params: dict, texts, labels, groups, folds: int = 5):
    """Out-of-fold predicted labels and confidences."""
    pred = np.empty(len(texts), dtype=object)
    conf = np.zeros(len(texts))
    for tr, te in GroupKFold(n_splits=folds).split(texts, labels, groups):
        pipe = build(params).fit([texts[i] for i in tr], [labels[i] for i in tr])
        proba = pipe.predict_proba([texts[i] for i in te])
        pred[te] = pipe.classes_[proba.argmax(1)]
        conf[te] = proba.max(1)
    return pred, conf


def pick_threshold(pred, conf, labels) -> float:
    correct = pred == np.array(labels)
    for t in np.arange(0.20, 0.96, 0.01):
        m = conf >= t
        if m.sum() and correct[m].mean() >= TARGET_PRECISION:
            return round(float(t), 2)
    return 0.95


def score(name: str, predict, examples) -> dict:
    y = [e.intent for e in examples]
    preds, confs, ms = [], [], []
    for e in examples:
        t0 = time.perf_counter()
        label, c = predict(e.text)
        ms.append((time.perf_counter() - t0) * 1000)
        preds.append(label)
        confs.append(c)
    correct = np.array([p == t for p, t in zip(preds, y, strict=True)])
    by_lang = {
        lang: round(
            f1_score(
                [t for t, e in zip(y, examples, strict=True) if e.lang == lang],
                [p for p, e in zip(preds, examples, strict=True) if e.lang == lang],
                average="macro",
                zero_division=0,
            ),
            4,
        )
        for lang in ("es", "pt")
    }
    return {
        "model": name,
        "n": len(y),
        "accuracy": round(accuracy_score(y, preds), 4),
        "macro_f1": round(f1_score(y, preds, average="macro", zero_division=0), 4),
        "macro_f1_by_language": by_lang,
        "ece": round(ece(np.array(confs), correct), 4) if name != "keyword_baseline" else None,
        "latency_ms_p50": round(statistics.median(ms), 3),
        "latency_ms_p95": round(float(np.percentile(ms, 95)), 3),
        "errors": [
            {"text": e.text, "lang": e.lang, "expected": t, "got": p}
            for e, t, p in zip(examples, y, preds, strict=True)
            if t != p
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument(
        "--claude", action="store_true", help="also score Claude zero-shot (needs an API key)"
    )
    args = ap.parse_args()

    train = training_set()
    texts, labels, groups = (
        [e.text for e in train],
        [e.intent for e in train],
        [e.group for e in train],
    )
    mlflow.set_experiment("copilot-intent")

    with mlflow.start_run(run_name=f"optuna-{datetime.now(UTC):%Y%m%dT%H%M}") as parent:
        mlflow.log_params(
            {
                "n_train": len(train),
                "n_groups": len(set(groups)),
                "trials": args.trials,
                "cv": "GroupKFold(5)",
            }
        )

        def objective(trial: optuna.Trial) -> float:
            p = {
                "C": trial.suggest_float("C", 0.1, 100.0, log=True),
                "ngram_min": trial.suggest_int("ngram_min", 1, 3),
                "ngram_max": trial.suggest_int("ngram_max", 3, 6),
                "sublinear_tf": trial.suggest_categorical("sublinear_tf", [True, False]),
                "class_weight": trial.suggest_categorical("class_weight", [None, "balanced"]),
            }
            pred, _ = oof(p, texts, labels, groups)
            f1 = f1_score(labels, list(pred), average="macro")
            with mlflow.start_run(run_name=f"trial-{trial.number}", nested=True):
                mlflow.log_params(p)
                mlflow.log_metric("cv_macro_f1", f1)
            return f1

        study = optuna.create_study(
            direction="maximize", sampler=optuna.samplers.TPESampler(seed=7)
        )
        study.optimize(objective, n_trials=args.trials)
        best = dict(study.best_params)
        pred, conf = oof(best, texts, labels, groups)
        threshold = pick_threshold(pred, conf, labels)
        covered = float((conf >= threshold).mean())
        mlflow.log_params({f"best_{k}": v for k, v in best.items()})
        mlflow.log_metrics(
            {
                "best_cv_macro_f1": study.best_value,
                "threshold": threshold,
                "oof_coverage_at_threshold": covered,
            }
        )

        model = build(best).fit(texts, labels)
        test = test_set()

        def learned(t):
            pr = model.predict_proba([t])[0]
            return model.classes_[pr.argmax()], float(pr.max())

        kw = KeywordRouter()
        results = [
            score("learned_char_ngram_lr", learned, test),
            score("keyword_baseline", lambda t: (kw.predict(t).intent, 1.0), test),
        ]
        # the copilot's actual policy: confident model answers, the rest go to Claude (or a clarifying question)
        confident = [e for e in test if learned(e.text)[1] >= threshold]
        results[0]["coverage_at_threshold"] = round(len(confident) / len(test), 4)
        results[0]["accuracy_when_confident"] = round(
            sum(learned(e.text)[0] == e.intent for e in confident) / max(1, len(confident)), 4
        )
        if args.claude and Settings().llm_available:
            from copilot.llm import LLM

            llm = LLM(Settings().llm_model)
            usage = {"in": 0, "out": 0, "cost": 0.0}

            def claude(t):
                label, u = llm.classify(t)
                usage["in"] += u.input_tokens
                usage["out"] += u.output_tokens
                usage["cost"] += u.cost_usd
                return label, 1.0

            r = score(f"claude_zero_shot:{llm.model}", claude, test)
            r["cost_usd_total"] = round(usage["cost"], 5)
            r["ece"] = None
            results.append(r)
        for r in results:
            for k in ("accuracy", "macro_f1", "ece", "latency_ms_p50", "latency_ms_p95"):
                if r.get(k) is not None:
                    mlflow.log_metric(f"test_{r['model'].split(':')[0]}_{k}", r[k])

        out = {
            "params": {**best, "threshold": threshold},
            "cv_macro_f1": round(study.best_value, 4),
            "oof_coverage_at_threshold": round(covered, 4),
            "target_precision": TARGET_PRECISION,
            "mlflow_run_id": parent.info.run_id,
            "tuned_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        PARAMS_FILE.write_text(json.dumps(out, indent=1) + "\n")
        REPORTS.mkdir(parents=True, exist_ok=True)
        report = {"tuning": out, "held_out": results}
        (REPORTS / "intent_model.json").write_text(
            json.dumps(report, indent=1, ensure_ascii=False) + "\n"
        )
        (REPORTS / "intent_model.md").write_text(render(report) + "\n")
        mlflow.log_artifact(str(REPORTS / "intent_model.md"))
        print(render(report))


def render(rep: dict) -> str:
    t = rep["tuning"]
    lines = [
        "# Intent model: held-out report",
        "",
        f"Tuned with Optuna on grouped 5-fold CV (cv macro-F1 {t['cv_macro_f1']}); confidence threshold "
        f"{t['params']['threshold']} chosen out-of-fold for {int(t['target_precision'] * 100)} % precision "
        f"(covers {t['oof_coverage_at_threshold']:.0%} of out-of-fold phrasings). MLflow run `{t['mlflow_run_id']}`.",
        "",
        "Held-out set: `eval/intent_test.yaml`, written before tuning, never used to choose parameters.",
        "",
        "| model | n | accuracy | macro-F1 | F1 es | F1 pt | ECE | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rep["held_out"]:
        ece_txt = "" if r["ece"] is None else f"{r['ece']:.3f}"
        lines.append(
            f"| {r['model']} | {r['n']} | {r['accuracy']:.3f} | {r['macro_f1']:.3f} | {r['macro_f1_by_language']['es']:.3f} | "
            f"{r['macro_f1_by_language']['pt']:.3f} | {ece_txt} | "
            f"{r['latency_ms_p50']} | {r['latency_ms_p95']} |"
        )
    lm = rep["held_out"][0]
    lines += [
        "",
        f"At the threshold the learned model answers {lm['coverage_at_threshold']:.0%} of held-out phrasings itself, "
        f"{lm['accuracy_when_confident']:.1%} of them correctly; the rest go to Claude, or to a clarifying question "
        "when no model key is configured.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    os.environ.setdefault("MLFLOW_TRACKING_URI", "http://127.0.0.1:5001")
    main()
