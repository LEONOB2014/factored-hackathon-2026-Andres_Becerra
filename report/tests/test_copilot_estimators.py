"""The item-level estimators of the copilot evaluation report agree with reference implementations."""

import numpy as np
import pytest
from statsmodels.stats.contingency_tables import mcnemar

from report_lib.build import Chapter
from report_lib.estimators.resampling import bootstrap, mcnemar_exact, zero_events_upper
from report_lib.paths import REPO

SRC = REPO / "report" / "pyproject.toml"


@pytest.mark.parametrize("b, c", [(0, 0), (1, 0), (3, 9), (12, 0), (7, 7), (20, 31)])
def test_exact_mcnemar_matches_statsmodels(b, c):
    first = [True] * b + [False] * c + [True] * 40 + [False] * 5
    second = [False] * b + [True] * c + [True] * 40 + [False] * 5
    r = mcnemar_exact(first, second)
    assert (r.b, r.c) == (b, c)
    ref = 1.0 if b + c == 0 else mcnemar([[40, b], [c, 5]], exact=True).pvalue
    assert r.p == pytest.approx(ref)


def test_mcnemar_needs_the_same_items():
    with pytest.raises(ValueError):
        mcnemar_exact([True, False], [True])


def test_bootstrap_brackets_the_estimate_and_is_reproducible():
    x = np.random.default_rng(1).lognormal(6.5, 0.4, 200)
    a = bootstrap(x, np.median, 2000, seed=7)
    b = bootstrap(x, np.median, 2000, seed=7)
    assert a == b and a.lo < a.estimate < a.hi and a.method == "bootstrap-iid"


def test_zero_events_upper_bound_is_the_exact_one_sided_bound():
    assert zero_events_upper(85) == pytest.approx(
        0.0346, abs=1e-4
    )  # close to the rule of three, 3/85


def test_test_claims_carry_their_family():
    ch = Chapter(99, "chxx")
    ch.test("mcnemar", 3, 0.25, 0.5, "fam", 4, SRC, null="equal accuracy", method="exact McNemar")
    c = ch.claims[0]
    assert c.kind == "test" and c.family_size == 4 and c.q == 0.5
