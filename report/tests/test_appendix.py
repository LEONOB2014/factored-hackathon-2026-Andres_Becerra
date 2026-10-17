"""The generated appendices: every heading and every claim appears exactly once, and no local path is printed."""

import re

import pandas as pd
import pytest

from report_lib import appendix, claims, texgen
from report_lib.manifest import Claim
from report_lib.paths import CLAIMS_DIR, CONF, TEX

H = "a" * 64


def make(**kw) -> Claim:
    base = dict(id="ch03.xx", kind="count", status="exploratory", source_type="scripted",
                source_path="eda/reports/tables/x.csv", source_sha256=H, chapter=3, value=7)  # fmt: skip
    return Claim(**{**base, **kw})


def test_traceability_lists_every_heading_once():
    text = appendix.traceability()
    rows = [line for line in text.splitlines() if re.match(r"^[12] & ", line)]
    assert len(rows) == len(pd.read_csv(CONF / "notebook_map.csv"))


def test_ledger_values_by_kind():
    prop = make(kind="proportion", value=None, num=42, den=100, lo=0.33, hi=0.52,
                interval_method="wilson-iid", cluster_unit="none")  # fmt: skip
    value, interval = appendix.claim_value(prop)
    assert value == r"\num{0.42} (\num{42}/\num{100})" and interval == r"[\num{0.33}, \num{0.52}]"
    test = make(
        kind="test", value=None, statistic=3.1, p=0.002, q=0.01, family_id="f", family_size=4
    )
    value, interval = appendix.claim_value(test)
    assert value == r"\num{3.1}" and interval == r"$p$ \num{0.002}, $q$ \num{0.01}"
    naive = make(
        kind="metric", value=None, estimate=0.6, n=50, lo=0.5, hi=0.7, interval_method="naive-iid"
    )
    assert appendix.claim_value(naive)[1].endswith(r"\naivemark")


def test_ledger_numbers_sources_and_lists_each_claim_once():
    cs = {"ch03.aa": make(id="ch03.aa"), "ch03.bb": make(id="ch03.bb", source_path="data/parquet/t.parquet"),
          "ch04.cc": make(id="ch04.cc", chapter=4)}  # fmt: skip
    text = appendix.claims_ledger(cs)
    for cid in cs:
        assert text.count(f"\\nolinkurl{{{cid}}} &") == 1
    assert appendix.source_index(cs) == {
        ("data/parquet/t.parquet", H): 1,
        ("eda/reports/tables/x.csv", H): 2,
    }
    assert r"\Cref{ch:inventory-keys}" in text and r"\nolinkurl{data/parquet/t.parquet}" in text


def test_built_ledger_has_every_claim_and_no_local_path():
    built = claims.load_all(CLAIMS_DIR)
    if not built:
        pytest.skip("claims not built")
    text = appendix.claims_ledger(built)
    assert all(text.count(f"\\nolinkurl{{{cid}}} &") == 1 for cid in built)
    assert "/Users/" not in text and "{/" not in text


def test_per_country_tables_cover_every_market(tmp_path):
    labels = appendix.per_country(out_dir=tmp_path)
    assert len(labels) == 7
    profile = pd.read_csv(tmp_path / "sources" / "appc-profile.csv")
    assert list(profile.columns) == ["measure", "ALL", "AR", "CO", "MX"]
    for label in labels:
        assert (tmp_path / "tables" / f"{label}.tex").exists()


def test_software_reports_locked_versions_and_the_freeze():
    parts = appendix.software()
    locked = appendix.locked_versions(CONF.parent / "uv.lock")
    assert f"\\texttt{{scipy}} & {locked['scipy']}" in parts["software-toolchain"]
    assert "Protocol frozen at commit" in parts["software-provenance"]


def test_locked_versions_follow_the_platform_fork(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname = "numpy"\nversion = "1.0"\nresolution-markers = ["sys_platform == \'nowhere\'"]\n'
        '[[package]]\nname = "numpy"\nversion = "2.0"\nresolution-markers = ["sys_platform != \'nowhere\'"]\n'
        '[[package]]\nname = "scipy"\nversion = "3.0"\n'
    )
    assert appendix.locked_versions(lock) == {"numpy": "2.0", "scipy": "3.0"}


def test_every_generated_appendix_is_input(tmp_path):
    written = appendix.render_all({"ch03.aa": make(id="ch03.aa")}, tmp_path)
    inputs = "".join(p.read_text() for p in (TEX / "appendices").glob("*.tex"))
    for path in written:
        assert f"appendices/{path.stem}" in inputs, path.name


def test_arrow_is_typeset():
    assert texgen.tex_escape("a → b") == r"a \ensuremath{\rightarrow} b"
