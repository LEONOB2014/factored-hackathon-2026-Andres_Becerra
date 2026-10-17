"""The typed-number lint: chapters may not contain typed numbers, in prose or in math (eng review Q1)."""

import pytest

from report_lib import lint, texgen

ALLOW = {"prose": [], "math": [__import__("re").compile("[0-9]")]}


def test_chapters_contain_no_typed_numbers():
    found = [str(v) for p in texgen.chapter_files() for v in lint.lint_file(p)]
    assert found == []


@pytest.mark.parametrize(
    "snippet",
    [
        "The share was 0.42 of the rows.",
        r"We estimate $\hat p = 0.31$.",
        r"\begin{align} x &= 2.5 \end{align}",
        r"\[ n = 4.4\times 10^6 \]",
        r"About \SI{3.2}{\percent} of rows.",
        r"Nested {braces {17}} hide nothing.",
        r"\textbf{1234 customers}",
        "Twelve customers churned.",
        "The two copies differ.",
        "The effect is significant.",
        "It rose by 15 %.",
    ],
)
def test_typed_numbers_fail(snippet):
    assert lint.lint_text(snippet, allow=ALLOW), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        r"The share was \est{ch3.share}{pct} per cent.",
        r"See \cref{ch:time-and-clocks} and \eqref{eq:bh}.",
        "The data run from 2023 to 2026.",
        r"Indices $x_1 + 2 y_{3}$ are notation.",
        "% 9.9 in a comment is ignored",
        r"As \textcite[p.~12]{benjamini1995} show.",
        r"\verb|5.5| is verbatim.",
        "One of the copies differs.",
        "A classifier two-sample test and a two-sided interval.",
        r"The effect is significant (q = \est{ch19.gate}{q}).",
        r"\label{sec:x2} \includegraphics[width=0.5\textwidth]{fig-01}",
        r"The rule of \ident{ADR-018} and notebook \ident{granularity_hour/08}.",
        r"The model \model{Qwen3-30B-A3B-Instruct-2507} on the gateway.",
    ],
)
def test_allowed_forms_pass(snippet):
    assert lint.lint_text(snippet, allow=ALLOW) == []


def test_allowlist_entries_need_a_reason(tmp_path):
    p = tmp_path / "allow.txt"
    p.write_text("math [0-9]\n")
    with pytest.raises(ValueError, match="reason"):
        lint.load_allow(p)


def test_repository_allowlist_loads():
    allow = lint.load_allow()
    assert allow["math"] and not allow["prose"]


NAME_MACROS = {
    "shaname",
    "CRtwo",
    "HCthree",
    "logten",
    "reportdate",  # the report's date, fixed by the author: a date, not a quantity
}  # names with digits; every other macro body must be digit-free


def test_macros_cannot_smuggle_numbers():
    import re

    from report_lib.paths import SHARED_TEX

    for name, body in re.findall(
        r"\\newcommand\{\\(\w+)\}(?:\[\d\])?\{(.*)\}\s*$",
        (SHARED_TEX / "macros.tex").read_text(),
        re.M,
    ):
        body = re.sub(r"#\d", "", body)  # parameter references
        if re.search(r"\d", body):
            assert name in NAME_MACROS, f"macro \\{name} contains a digit"
