"""The typed-number lint: no data-derived number may be typed into a chapter.

Each chapter is parsed with pylatexenc. Digits are flagged in prose and in math unless they sit inside the
arguments of a skipped macro (\\est, \\proto, references, citations, labels, file includes) or match the closed
allowlist in conf/lint_allow.txt. In prose, number words from "two" upward are flagged as well, and so is any
sentence that says "significant" without citing a q-value through \\est{...}{q}.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexCommentNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexMathNode,
    LatexWalker,
    get_default_latex_context_db,
)
from pylatexenc.macrospec import MacroSpec

from report_lib.paths import CONF

# \model names a language model, whose name carries digits (versions, sizes) that are part of the name, not
# quantities the report measured; like \ident it is skipped.
SKIP_MACROS = {
    "est", "proto", "ident", "model", "ref", "eqref", "pageref", "cref", "Cref", "autoref", "label", "cite", "citet",
    "citep", "textcite", "parencite", "autocite", "citeauthor", "citeyear", "fullcite", "footcite",
    "include", "input", "includegraphics", "url", "href", "verb", "addbibresource", "bibliography",
    "setcounter", "addtocounter", "vspace", "hspace", "rule", "includeonly", "nocite",
}  # fmt: skip
MATH_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*", "eqnarray",
    "eqnarray*", "split", "aligned", "cases", "array", "matrix", "pmatrix", "bmatrix",
}  # fmt: skip
SKIP_ENVS = {"verbatim", "lstlisting", "comment"}
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
YEAR = re.compile(r"(19|20)\d\d")
WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|"
    r"thousands?|millions?|billions?|dozens?|half|halves|thirds?|quarters?|twice|thrice|double|triple)\b"
    r"(?!-)",  # a number word in a hyphenated term names a method ("two-sample", "two-sided"), not a count
    re.I,
)

_MACROS = [
    MacroSpec("est", "{{"),
    MacroSpec("proto", "{"),
    MacroSpec("ident", "{"),
    MacroSpec("model", "{"),
    MacroSpec("cref", "*{"),
    MacroSpec("Cref", "*{"),
    MacroSpec("textcite", "[[{"),
    MacroSpec("parencite", "[[{"),
    MacroSpec("autocite", "[[{"),
    MacroSpec("footcite", "[[{"),
    MacroSpec("SI", "[{{"),
    MacroSpec("num", "[{"),
    MacroSpec("includegraphics", "[{"),
]


def _context():
    db = get_default_latex_context_db()
    db.add_context_category("report", prepend=True, macros=_MACROS)
    return db


@dataclass(frozen=True)
class Violation:
    file: str
    token: str
    where: str  # "prose" or "math"
    rule: str

    def __str__(self) -> str:
        return f"{self.file}: {self.rule} {self.token!r} in {self.where}"


def load_allow(path: Path = CONF / "lint_allow.txt") -> dict[str, list[re.Pattern]]:
    """Lines `prose|math <regex>  # reason`; the reason is required."""
    allow: dict[str, list[re.Pattern]] = {"prose": [], "math": []}
    if not path.exists():
        return allow
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body, _, reason = line.partition("#")
        if not reason.strip():
            raise ValueError(f"{path.name}:{n}: every allowlist entry needs a reason after '#'")
        where, _, pattern = body.strip().partition(" ")
        if where not in allow or not pattern.strip():
            raise ValueError(f"{path.name}:{n}: expected 'prose <regex>' or 'math <regex>'")
        allow[where].append(re.compile(pattern.strip()))
    return allow


def lint_text(source: str, name: str = "<string>", allow=None) -> list[Violation]:
    allow = load_allow() if allow is None else allow
    nodes, _, _ = LatexWalker(
        source, latex_context=_context(), tolerant_parsing=False
    ).get_latex_nodes()
    out: list[Violation] = []
    _walk(nodes, False, name, allow, out)
    out.extend(_significance(source, name))
    return out


def lint_file(path: Path, allow=None) -> list[Violation]:
    return lint_text(path.read_text(), path.name, allow)


def _walk(nodes, math: bool, name: str, allow, out: list[Violation]) -> None:
    for node in nodes or []:
        if isinstance(node, LatexCommentNode):
            continue
        if isinstance(node, LatexCharsNode):
            _check_chars(node.chars, math, name, allow, out)
        elif isinstance(node, LatexMathNode):
            _walk(node.nodelist, True, name, allow, out)
        elif isinstance(node, LatexEnvironmentNode):
            if node.environmentname in SKIP_ENVS:
                continue
            inner = math or node.environmentname in MATH_ENVS
            if node.nodeargd is not None:
                _walk([a for a in node.nodeargd.argnlist if a is not None], inner, name, allow, out)
            _walk(node.nodelist, inner, name, allow, out)
        elif isinstance(node, LatexMacroNode):
            if node.macroname in SKIP_MACROS:
                continue
            if node.nodeargd is not None:
                _walk([a for a in node.nodeargd.argnlist if a is not None], math, name, allow, out)
        elif isinstance(node, LatexGroupNode):
            _walk(node.nodelist, math, name, allow, out)


def _check_chars(text: str, math: bool, name: str, allow, out: list[Violation]) -> None:
    where = "math" if math else "prose"
    for m in NUMBER.finditer(text):
        tok = m.group(0)
        if not math and YEAR.fullmatch(tok):
            continue
        if any(p.fullmatch(tok) for p in allow[where]):
            continue
        out.append(Violation(name, tok, where, "typed number"))
    if not math:
        for m in WORDS.finditer(text):
            tok = m.group(0)
            if any(p.fullmatch(tok) for p in allow["prose"]):
                continue
            out.append(Violation(name, tok, where, "number word"))


def _significance(source: str, name: str) -> list[Violation]:
    """A sentence that says 'significant' must cite a q-value with \\est{...}{q}."""
    text = re.sub(r"(?<!\\)%.*", "", source)
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"significan", sentence, re.I) and not re.search(
            r"\\est\{[^}]+\}\{q\}", sentence
        ):
            out.append(
                Violation(name, sentence.strip()[:60], "prose", "significance without a q-value")
            )
    return out
