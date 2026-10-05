"""The gateway: what happens to a message before anything reads it.

* card numbers (13-19 digits passing the Luhn check) are masked to their last four digits;
* prompt-injection and cross-customer probes are flagged, and the message never reaches the model;
* the language is detected (Spanish or Portuguese) from lexical markers.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

PAN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask_pans(text: str) -> tuple[str, list[str]]:
    """Replace every Luhn-valid card number with ``****1234``; return the text and the suffixes seen."""
    seen: list[str] = []

    def repl(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            seen.append(digits[-4:])
            return f"****{digits[-4:]}"
        return m.group(0)

    return PAN.sub(repl, text), seen


def fold(text: str) -> str:
    """Lowercase without accents, for matching."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


INJECTION = [
    r"ignor\w*\s+(?:\w+\s+){0,3}(?:instruc|regla|indicac|prompt|instructions|rules)",
    r"(?:system|sistema)\s*prompt",
    r"(?:olvida|esquece|forget)\w*\s+(?:\w+\s+){0,3}(?:instruc|regla|regra|rules)",
    r"(?:ahora eres|agora voce e|you are now|act[uú]a como|aja como|finge|pretend)",
    r"(?:modo|mode)\s+(?:desarrollador|desenvolvedor|developer|admin|dios|deus|god)",
    r"(?:jailbreak|dan mode|sudo)",
    r"(?:revela|muestra|mostra|show|dime|me diga)\s+(?:\w+\s+){0,3}(?:prompt|instruc|politica|policy|configuraci)",
]
CROSS_CUSTOMER = [
    r"\bcli-[a-z0-9]{6,}\b",
    r"(?:otro|outro|otra|outra)\s+(?:cliente|usuario|usuário|persona|pessoa)",
    r"(?:de|da|do)\s+(?:mi|minha|meu)\s+(?:espos[ao]|herman[ao]|irm[aã]o?|vecin[ao]|vizinh[ao]|amig[ao]|jefe|chefe|mae|madre|padre|pai)",
    r"(?:todos los|todos os|all)\s+(?:clientes|customers)",
]


@dataclass
class Screened:
    text: str  # masked
    language: str  # "es" | "pt"
    language_confidence: float
    injection: bool
    cross_customer: bool
    pan_suffixes: list[str] = field(default_factory=list)


PT_MARKERS = {
    "nao",
    "voce",
    "cartao",
    "cartoes",
    "obrigado",
    "obrigada",
    "meu",
    "minha",
    "esta",
    "estou",
    "quero",
    "preciso",
    "gostaria",
    "por que",
    "porque",
    "bloqueio",
    "desbloquear",
    "fatura",
    "limite",
    "vence",
    "venceu",
    "segunda via",
    "oi",
    "ola",
    "bom dia",
    "boa tarde",
    "boa noite",
    "tchau",
    "sim",
    "isso",
    "consigo",
    "posso",
    "falar",
    "atendente",
    "compra",
    "recusado",
    "recusada",
    "perdi",
    "roubaram",
    "roubado",
    "reclamacao",
    "ja",
    "tambem",
    "agora",
    "ainda",
    "um",
    "uma",
    "com",
    "pra",
    "para mim",
    "qual",
    "quanto",
    "tenho",
    "fiz",
    "nenhum",
    "aumentar",
    "credito do",
    "num",
    "numa",
    "do",
    "da",
    "dos",
    "das",
    "pelo",
    "pela",
    "faco",
    "fazer",
    "voces",
    "seu",
    "sua",
    "golpe",
    "ta",
    "essa",
    "esse",
    "mim",
    "vou",
    "vai",
}
ES_MARKERS = {
    "no",
    "usted",
    "tarjeta",
    "tarjetas",
    "gracias",
    "mi",
    "mis",
    "esta",
    "estoy",
    "quiero",
    "necesito",
    "quisiera",
    "por que",
    "porque",
    "bloqueo",
    "desbloquear",
    "factura",
    "limite",
    "cupo",
    "vence",
    "vencio",
    "reposicion",
    "hola",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "adios",
    "si",
    "eso",
    "puedo",
    "hablar",
    "asesor",
    "compra",
    "rechazada",
    "rechazaron",
    "perdi",
    "robaron",
    "robada",
    "queja",
    "ya",
    "tambien",
    "ahora",
    "todavia",
    "un",
    "una",
    "con",
    "para mi",
    "cual",
    "cuanto",
    "tengo",
    "hice",
    "ningun",
    "aumentar",
    "el",
    "la",
    "los",
    "las",
    "del",
    "al",
    "lo",
    "hago",
    "hacer",
    "ustedes",
    "su",
    "esa",
    "ese",
    "voy",
    "va",
}


def detect_language(text: str, prior: str | None = None) -> tuple[str, float]:
    t = fold(text)
    words = re.findall(r"[a-z]+", t)
    joined = " " + " ".join(words) + " "
    pt = sum(1 for m in PT_MARKERS if f" {m} " in joined)
    es = sum(1 for m in ES_MARKERS if f" {m} " in joined)
    pt += 2 * len(re.findall(r"(?:ção|ções|ão|ões|nh|lh)", text.lower()))
    es += 2 * len(re.findall(r"(?:ñ|¿|¡|ción|ciones)", text.lower()))
    if pt == es:
        return (prior or "es"), 0.5
    lang = "pt" if pt > es else "es"
    return lang, max(pt, es) / (pt + es)


def screen(text: str, prior_language: str | None = None) -> Screened:
    masked, suffixes = mask_pans(text)
    t = fold(masked)
    injection = any(re.search(p, t) for p in INJECTION)
    cross = any(re.search(p, t) for p in CROSS_CUSTOMER)
    lang, conf = detect_language(masked, prior_language)
    return Screened(masked, lang, conf, injection, cross, suffixes)
