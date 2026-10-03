"""PII guardrail for free text: detect, redact or block personal data before it is stored or indexed.

Choke points (platform/policies/data_classification.yaml):
  1. knowledge-base ingestion  -> block any document with PII (`scan(...).has_pii`)
  2. GenAI audit logging       -> store `redact(...)` output only; the exact text is kept as a hash
  3. text columns leaving silver (complaints, transcripts, surveys) -> redact
  4. serving publication       -> column-level checks (dbt tests) + sampling scan of text columns

Recognizers are deterministic and validated with check digits where the identifier has one, which keeps
false positives low on numeric banking text (amounts, references). If Microsoft Presidio is installed
(Airflow platform-venv) its NER adds person-name detection on top; nothing here depends on it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# ------------------------------------------------------------------------------------------ validators


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _cpf_ok(raw: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", raw)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(d[i] * (n + 1 - i) for i in range(n))
        if d[n] != (s * 10 % 11) % 10:
            return False
    return True


def _cnpj_ok(raw: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", raw)]
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for n, weights in (
        (12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
        (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
    ):
        r = sum(a * b for a, b in zip(d[:n], weights)) % 11
        if d[n] != (0 if r < 2 else 11 - r):
            return False
    return True


def _clabe_ok(raw: str) -> bool:
    d = [int(c) for c in raw]
    if len(d) != 18:
        return False
    s = sum((d[i] * (3, 7, 1)[i % 3]) % 10 for i in range(17))
    return d[17] == (10 - s % 10) % 10


def _cuit_ok(raw: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", raw)]
    if len(d) != 11:
        return False
    s = sum(a * b for a, b in zip(d[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    v = 11 - s % 11
    v = 0 if v == 11 else (9 if v == 10 else v)
    return d[10] == v


def _nit_ok(raw: str) -> bool:
    """Colombian NIT: digits + verification digit (primes 3,7,13,...,71 weights)."""
    digits = re.sub(r"\D", "", raw)
    if not 9 <= len(digits) <= 16:
        return False
    body, dv = digits[:-1], int(digits[-1])
    primes = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]
    s = sum(int(c) * primes[i] for i, c in enumerate(reversed(body)))
    r = s % 11
    return dv == (r if r < 2 else 11 - r)


# ----------------------------------------------------------------------------------------- recognizers


@dataclass(frozen=True)
class Recognizer:
    entity: str
    pattern: re.Pattern
    validate: callable = None  # optional check-digit validator
    country: str | None = None


RECOGNIZERS: list[Recognizer] = [
    Recognizer("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    Recognizer(
        "CREDIT_CARD",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        lambda m: _luhn_ok(re.sub(r"\D", "", m)),
    ),
    Recognizer(
        "MX_CURP", re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z\d]\d\b"), country="MX"
    ),
    Recognizer("MX_RFC", re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z\d]{3}\b"), country="MX"),
    Recognizer("MX_CLABE", re.compile(r"\b\d{18}\b"), _clabe_ok, country="MX"),
    Recognizer("BR_CPF", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), _cpf_ok, country="BR"),
    Recognizer(
        "BR_CNPJ", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), _cnpj_ok, country="BR"
    ),
    Recognizer(
        "AR_CUIT", re.compile(r"\b(?:20|23|24|27|30|33|34)-?\d{8}-?\d\b"), _cuit_ok, country="AR"
    ),
    Recognizer("CO_NIT", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-\d\b"), _nit_ok, country="CO"),
    Recognizer(
        "NATIONAL_ID_LABELED",  # CC/DNI/cédula numbers next to their label
        re.compile(
            r"(?i)\b(?:c\.?c\.?|c[ée]dula|dni|documento|rg)\s*(?:n[°º.o]*\s*)?:?\s*\d[\d.\s]{6,12}\d\b"
        ),
    ),
    Recognizer(
        "PHONE",
        re.compile(
            r"(?<![\w.])\+?(?:52|55|57|54)?[\s-]?\(?\d{2,3}\)?[\s-]?\d{3,4}[\s-]?\d{4}(?![\w.])"
        ),
    ),
    Recognizer(
        "IP_ADDRESS",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    ),
    Recognizer(
        "PIX_KEY_EVP",
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"),
        country="BR",
    ),
]


@dataclass
class Finding:
    entity: str
    start: int
    end: int
    text_sha256: str  # never the value itself


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def has_pii(self) -> bool:
        return bool(self.findings)

    @property
    def entities(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.entity] = out.get(f.entity, 0) + 1
        return out


def _presidio_findings(text: str, language: str) -> list[Finding]:
    try:
        from presidio_analyzer import AnalyzerEngine
    except ImportError:
        return []
    engine = _presidio_findings.__dict__.setdefault(
        "engine", AnalyzerEngine(supported_languages=["en", "es"])
    )
    lang = language if language in ("en", "es") else "es"
    return [
        Finding(
            r.entity_type,
            r.start,
            r.end,
            hashlib.sha256(text[r.start : r.end].encode()).hexdigest(),
        )
        for r in engine.analyze(text=text, language=lang, entities=["PERSON"])
        if r.score >= 0.85
    ]


def scan(text: str, language: str = "es", use_ner: bool = True) -> ScanResult:
    res = ScanResult()
    taken: list[tuple[int, int]] = []
    for rec in RECOGNIZERS:
        for m in rec.pattern.finditer(text):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue  # an earlier, more specific recognizer already claimed this span
            if rec.validate and not rec.validate(m.group()):
                continue
            taken.append((s, e))
            res.findings.append(
                Finding(rec.entity, s, e, hashlib.sha256(m.group().encode()).hexdigest())
            )
    if use_ner:
        for f in _presidio_findings(text, language):
            if not any(f.start < te and ts < f.end for ts, te in taken):
                res.findings.append(f)
    res.findings.sort(key=lambda f: f.start)
    return res


def redact(text: str, language: str = "es", use_ner: bool = True) -> tuple[str, ScanResult]:
    """Replace every finding with <ENTITY>; returns the redacted text and the scan (hashes only)."""
    res = scan(text, language, use_ner)
    out, last = [], 0
    for f in res.findings:
        out.append(text[last : f.start])
        out.append(f"<{f.entity}>")
        last = f.end
    out.append(text[last:])
    return "".join(out), res
