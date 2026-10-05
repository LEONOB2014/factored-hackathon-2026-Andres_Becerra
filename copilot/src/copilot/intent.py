"""Intent recognition: a learned classifier (character n-grams and logistic regression), a keyword baseline, and the
corpus they share.

The classifier is small enough to train at start-up from the committed corpus with the committed hyper-parameters
(corpus/intent_params.json, chosen by scripts/tune_intent.py), so no binary model is kept in git.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from copilot.config import PROJECT
from copilot.gateway import fold

CORPUS = PROJECT / "corpus"
TRAIN_FILE = CORPUS / "train.yaml"
PARAMS_FILE = CORPUS / "intent_params.json"
TEST_FILE = PROJECT / "eval" / "intent_test.yaml"
DEFAULT_PARAMS = {
    "C": 10.0,
    "ngram_max": 5,
    "ngram_min": 2,
    "sublinear_tf": True,
    "class_weight": None,
}

PREFIX = {
    "es": ["", "hola, ", "buenos días, ", "oye, ", "por favor, "],
    "pt": ["", "oi, ", "bom dia, ", "olha, ", "por favor, "],
}
SUFFIX = {"es": ["", " por favor", " gracias", "?"], "pt": ["", " por favor", " obrigado", "?"]}


@dataclass(frozen=True)
class Example:
    text: str
    intent: str
    lang: str
    group: str  # the base phrasing it came from
    source: str  # "team" | "transcripts" | "test"


def load_yaml(path: Path, source: str) -> list[Example]:
    spec = yaml.safe_load(path.read_text())
    out = []
    for intent, by_lang in spec["intents"].items():
        for lang, phrases in by_lang.items():
            for i, p in enumerate(phrases):
                out.append(Example(str(p), intent, lang, f"{intent}:{lang}:{i}", source))
    for intent, phrases in (spec.get("transcripts") or {}).items():
        for i, p in enumerate(phrases):
            out.append(Example(str(p), intent, "es", f"{intent}:transcript:{i}", "transcripts"))
    return out


def augment(base: list[Example], per_base: int = 6) -> list[Example]:
    """Deterministic variants of each phrasing, kept in its group."""
    out = []
    for k, ex in enumerate(base):
        lang = ex.lang
        variants = {ex.text}
        for j in range(per_base):
            p = PREFIX[lang][(k + j) % len(PREFIX[lang])]
            s = SUFFIX[lang][(k * 3 + j) % len(SUFFIX[lang])]
            v = f"{p}{ex.text}{s}"
            if j % 3 == 1:
                v = fold(v)
            if j % 3 == 2:
                v = v.capitalize()
            variants.add(v)
        out.extend(Example(v, ex.intent, lang, ex.group, ex.source) for v in sorted(variants))
    return out


def training_set() -> list[Example]:
    return augment(load_yaml(TRAIN_FILE, "team"))


def test_set() -> list[Example]:
    return load_yaml(TEST_FILE, "test")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text)).strip()


def build(params: dict | None = None) -> Pipeline:
    p = {**DEFAULT_PARAMS, **(params or {})}
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(int(p["ngram_min"]), int(p["ngram_max"])),
                    sublinear_tf=bool(p["sublinear_tf"]),
                    preprocessor=normalize,
                ),
            ),
            (
                "lr",
                LogisticRegression(C=float(p["C"]), max_iter=4000, class_weight=p["class_weight"]),
            ),
        ]
    )


def load_params() -> dict:
    if PARAMS_FILE.is_file():
        return {**DEFAULT_PARAMS, **json.loads(PARAMS_FILE.read_text())["params"]}
    return dict(DEFAULT_PARAMS)


@dataclass(frozen=True)
class Prediction:
    intent: str
    confidence: float
    source: str  # "model" | "keyword" | "llm"
    ms: float
    top: tuple[tuple[str, float], ...] = ()


class IntentModel:
    """The learned classifier, trained at start-up (about a second)."""

    def __init__(self, params: dict | None = None, examples: list[Example] | None = None):
        self.params = params or load_params()
        ex = examples or training_set()
        self.pipe = build(self.params)
        self.pipe.fit([e.text for e in ex], [e.intent for e in ex])
        self.labels = list(self.pipe.classes_)

    def predict(self, text: str) -> Prediction:
        t0 = time.perf_counter()
        probs = self.pipe.predict_proba([text])[0]
        order = probs.argsort()[::-1]
        top = tuple((self.labels[i], float(probs[i])) for i in order[:3])
        return Prediction(top[0][0], top[0][1], "model", (time.perf_counter() - t0) * 1000, top)


# The baseline: first matching keyword in a fixed priority order (safety intents first), else out of scope.
KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "fraud_report",
        [
            "no reconozco",
            "nao reconheco",
            "fraude",
            "clonaron",
            "clonaram",
            "no hice",
            "nao fiz",
            "desconocid",
            "desconhecid",
        ],
    ),
    (
        "dispute",
        [
            "disputa",
            "contest",
            "dos veces",
            "duas vezes",
            "duplicad",
            "reembols",
            "estorno",
            "devoluc",
            "devoluç",
            "chargeback",
            "contracargo",
        ],
    ),
    (
        "complaint",
        [
            "queja",
            "reclamo",
            "reclamac",
            "reclamar",
            "pesim",
            "pessim",
            "ouvidoria",
            "superintendencia",
        ],
    ),
    ("human_agent", ["asesor", "atendente", "humano", "persona", "pessoa", "agente", "operador"]),
    ("unblock_card", ["desbloque", "reactiv", "reativ", "quitar el bloqueo", "tira o bloqueio"]),
    (
        "block_card",
        ["bloque", "perdi", "robaron", "roubaram", "extravi", "congela", "hurt", "furt"],
    ),
    (
        "reissue_card",
        [
            "reposic",
            "segunda via",
            "nueva tarjeta",
            "tarjeta nueva",
            "cartao novo",
            "novo cartao",
            "reemplazo",
            "duplicado",
            "reexpedi",
            "reemiss",
            "reemit",
        ],
    ),
    (
        "limit_increase",
        [
            "aumentar",
            "aumento",
            "subir",
            "ampliar",
            "amplia",
            "mas cupo",
            "mais limite",
            "incremento",
        ],
    ),
    (
        "decline_reason",
        [
            "rechaz",
            "recus",
            "declin",
            "negad",
            "no pasa",
            "nao passa",
            "no me deja",
            "nao consigo pagar",
        ],
    ),
    ("expiry_renewal", ["vence", "vencid", "venci", "expira", "caduc", "validade", "vigencia"]),
    (
        "balance_limit",
        ["saldo", "cupo", "limite", "disponible", "disponivel", "debo", "devo", "deuda", "divida"],
    ),
    ("card_status", ["estado", "situac", "status", "activa", "ativo", "funciona", "habilitad"]),
    (
        "smalltalk",
        [
            "hola",
            "oi",
            "ola",
            "gracias",
            "obrigad",
            "buenos",
            "bom dia",
            "boa tarde",
            "chao",
            "tchau",
            "valeu",
        ],
    ),
]


class KeywordRouter:
    def predict(self, text: str) -> Prediction:
        t0 = time.perf_counter()
        t = normalize(text)
        for intent, words in KEYWORDS:
            if any(fold(w) in t for w in words):
                return Prediction(intent, 1.0, "keyword", (time.perf_counter() - t0) * 1000)
        return Prediction("out_of_scope", 1.0, "keyword", (time.perf_counter() - t0) * 1000)
