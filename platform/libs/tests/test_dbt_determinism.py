"""Static guard: dbt SQL must not use constructs whose result depends on execution order (runs in CI, no data).

A compliance rebuild has to reproduce the same bytes. Two builds of the same commit used to differ in 18 of 84
relations (docs/platform/evidence/reproducibility/). The order-dependent constructs found are banned here; the
macros in platform/dbt/macros/determinism.sql are the deterministic replacements. Floating-point sums cannot be
detected statically: the two-build check in the evidence covers them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DBT = Path(__file__).resolve().parents[2] / "dbt"
SQL = sorted(
    p for d in ("models", "macros") for p in (DBT / d).rglob("*.sql") if "bigquery" not in p.parts
)


def _code(path: Path) -> str:
    """SQL without comments (Jinja {# #} and -- lines), so documentation may name the banned functions."""
    text = re.sub(r"\{#.*?#\}", " ", path.read_text(), flags=re.S)
    return re.sub(r"--[^\n]*", " ", text)


def _calls(code: str, name: str, ordered_windows: bool = False):
    """Argument text of every call to `name(...)` (balanced parentheses). With `ordered_windows`, calls used as a
    window function with an ORDER BY are skipped: the window defines their order."""
    for m in re.finditer(rf"(?<![\w.]){name}\s*\(", code, flags=re.I):
        depth, i = 1, m.end()
        while depth and i < len(code):
            depth += {"(": 1, ")": -1}.get(code[i], 0)
            i += 1
        if ordered_windows and re.match(r"\s*over\s*\([^)]*\border\s+by\b", code[i:], flags=re.I):
            continue
        yield code[m.end() : i - 1]


@pytest.mark.parametrize("path", SQL, ids=lambda p: str(p.relative_to(DBT)))
def test_no_order_dependent_sql(path: Path):
    code = _code(path)
    problems = []
    for fn in ("mode", "any_value", "first", "last"):
        if list(_calls(code, fn)):
            problems.append(
                f"{fn}() picks an arbitrary row among ties: use stable_mode() or arg_min/arg_max with a key"
            )
    for fn in ("list", "array_agg", "string_agg", "group_concat"):
        for args in _calls(code, fn, ordered_windows=True):
            if not re.search(r"\border\s+by\b", args, flags=re.I):
                problems.append(
                    f"{fn}({args.strip()[:40]}...) without ORDER BY: element order varies between runs"
                )
    for args in _calls(code, "md5"):
        if "dbt_valid_from" in args or "dbt_updated_at" in args:
            problems.append(
                "a key hashed with snapshot system time changes on every rebuild: hash the version number"
            )
    assert not problems, "\n".join(problems)


def test_the_guard_sees_the_project():
    assert len(SQL) > 80
    assert list(_calls("select list(x) from t", "list")) == ["x"]
    assert list(_calls("select list_sort(list(x order by x)) from t", "list")) == ["x order by x"]
    assert (
        list(_calls("select string_agg(d, '|') over (order by k) from t", "string_agg", True)) == []
    )
