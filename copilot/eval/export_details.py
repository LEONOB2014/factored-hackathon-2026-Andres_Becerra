"""Per-item detail of the intent model, for the evaluation report's confusion matrix, reliability diagram and
coverage curves. No network, nothing tuned: the stored parameters (corpus/intent_params.json) are refitted.

* held_out_intent.csv: every phrasing of eval/intent_test.yaml (written before tuning) with the learned model's label,
  confidence and runner-up, and the keyword baseline's label;
* oof_intent.csv: the out-of-fold label and confidence of every training phrasing under the grouped 5-fold split the
  threshold was chosen on (a group is one base phrasing and all its variants);
* training_summary.json: the training set's size by intent, language and source.

Fails if the refitted model does not reproduce the stored held-out accuracy (eval/reports/intent_model.json).

    cd copilot && uv run python eval/export_details.py
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

from copilot.intent import TRAIN_FILE as TRAIN
from copilot.intent import (
    IntentModel,
    KeywordRouter,
    build,
    load_params,
    load_yaml,
    test_set,
    training_set,
)

REPORTS = Path(__file__).resolve().parent / "reports"
OUT = REPORTS / "details"
FOLDS = 5


def held_out(model: IntentModel) -> list[dict]:
    kw = KeywordRouter()
    rows = []
    for i, e in enumerate(test_set()):
        p = model.predict(e.text)
        rows.append({"item": i, "lang": e.lang, "expected": e.intent, "learned": p.intent,
                     "confidence": round(p.confidence, 6), "runner_up": p.top[1][0],
                     "runner_up_confidence": round(p.top[1][1], 6), "keyword": kw.predict(e.text).intent})  # fmt: skip
    return rows


def out_of_fold(params: dict) -> list[dict]:
    ex = training_set()
    texts, labels, groups = [e.text for e in ex], [e.intent for e in ex], [e.group for e in ex]
    pred = np.empty(len(ex), dtype=object)
    conf = np.zeros(len(ex))
    for tr, te in GroupKFold(n_splits=FOLDS).split(texts, labels, groups):
        pipe = build(params).fit([texts[i] for i in tr], [labels[i] for i in tr])
        proba = pipe.predict_proba([texts[i] for i in te])
        pred[te] = pipe.classes_[proba.argmax(1)]
        conf[te] = proba.max(1)
    return [{"item": i, "lang": e.lang, "group": e.group, "source": e.source, "expected": e.intent,
             "learned": pred[i], "confidence": round(float(conf[i]), 6)} for i, e in enumerate(ex)]  # fmt: skip


def summary() -> dict:
    base, ex = load_yaml(TRAIN, "team"), training_set()
    return {
        "base_phrasings": len(base),
        "augmented_phrasings": len(ex),
        "intents": len({e.intent for e in ex}),
        "base_by_intent": dict(sorted(Counter(e.intent for e in base).items())),
        "base_by_language": dict(sorted(Counter(e.lang for e in base).items())),
        "base_by_source": dict(sorted(Counter(e.source for e in base).items())),
        "held_out_phrasings": len(test_set()),
        "folds": FOLDS,
    }


def write(name: str, rows: list[dict]) -> None:
    with (OUT / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    params = load_params()
    model = IntentModel(params)
    rows = held_out(model)
    stored = json.loads((REPORTS / "intent_model.json").read_text())["held_out"][0]["accuracy"]
    acc = sum(r["learned"] == r["expected"] for r in rows) / len(rows)
    if round(acc, 4) != stored:
        raise SystemExit(f"refitted held-out accuracy {acc:.4f} differs from the stored {stored}")
    OUT.mkdir(parents=True, exist_ok=True)
    write("held_out_intent.csv", rows)
    write("oof_intent.csv", out_of_fold(params))
    (OUT / "training_summary.json").write_text(json.dumps(summary(), indent=1) + "\n")
    print(f"held-out accuracy {acc:.4f} reproduced; wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
