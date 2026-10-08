"""Chapter helpers: proportions carry their interval, constants are descriptive with their reason."""

from report_lib.build import CONSTANT, Chapter
from report_lib.estimators import intervals
from report_lib.paths import REPO

SRC = REPO / "report" / "pyproject.toml"


def test_proportion_carries_the_interval():
    ch = Chapter(99, "chxx")
    ch.proportion("recall", 10, 10, intervals.wilson(10, 10), SRC)
    c = ch.claims[0]
    assert c.kind == "proportion" and c.interval_method == "wilson-iid" and c.cluster_unit == "none"
    assert 0.7 < c.lo < 0.75 and c.hi == 1.0


def test_constant_is_descriptive():
    ch = Chapter(99, "chxx")
    ch.constant("band", 0.3, SRC)
    c = ch.claims[0]
    assert c.kind == "descriptive" and c.reason == CONSTANT and c.value == 0.3


def test_registered_claims_cite_the_protocol_commit():
    ch = Chapter(99, "chxx")
    ch.status, ch.protocol_commit = "registered", "a" * 40
    ch.constant("gate", 1.0, SRC)
    assert ch.claims[0].status == "registered" and ch.claims[0].protocol_commit == "a" * 40
