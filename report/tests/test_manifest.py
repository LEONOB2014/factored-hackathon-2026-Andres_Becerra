"""Claim schema, per-chapter files with a strict merge, and reference resolution (eng review A1)."""

import pytest
from pydantic import ValidationError

from report_lib import claims, texgen
from report_lib.manifest import Claim

H = "a" * 64


def make(**kw):
    base = dict(id="ch03.share", kind="proportion", status="exploratory", source_type="table",
                source_path="eda/reports/tables/x.csv", source_sha256=H, chapter=3, num=42, den=100,
                lo=0.33, hi=0.52, interval_method="wilson-iid", cluster_unit="none")  # fmt: skip
    base.update(kw)
    return Claim(**base)


def test_valid_proportion_and_its_fields():
    f = texgen.claim_fields(make())
    assert f["pct"] == r"\num{42}" and f["share"] == r"\num{0.42}"
    assert f["ci"] == r"[\num{0.33}, \num{0.52}]"


def test_naive_interval_is_marked():
    f = texgen.claim_fields(make(interval_method="naive-iid"))
    assert f["ci"].endswith(r"\naivemark") and f["pct_ci"].endswith(r"\naivemark")


@pytest.mark.parametrize(
    "kw, msg",
    [
        (dict(den=None), "needs den"),
        (dict(den=0), "denominator"),
        (dict(lo=0.6, hi=0.5), "lower bound"),
        (dict(interval_method="cluster-bootstrap"), "cluster_unit none"),
        (dict(id="Ch03 share"), "claim id"),
        (dict(source_sha256="abc"), "SHA-256"),
        (dict(kind="test", statistic=2.0, p=1.5, family_id="f", q=0.1, family_size=3), "outside"),
        (dict(status="registered", source_type="scripted"), "protocol commit"),
        (dict(status="registered", protocol_commit="abc"), "must be exploratory"),
        (dict(source_path="eda/notebooks/08_anomaly_detection_ml.py"), "must be positive-control"),
        (dict(value=float("inf"), kind="count"), "not finite"),
    ],
)
def test_invalid_claims_are_rejected(kw, msg):
    with pytest.raises(ValidationError, match=msg):
        make(**kw)


def test_positive_control_is_derived_from_the_source():
    c = make(source_type="notebook", source_path="eda/notebooks/08_anomaly_detection_ml.py",
             status="positive-control")  # fmt: skip
    assert c.status == "positive-control"


def test_test_claims_need_a_family_and_q():
    with pytest.raises(ValidationError, match="family_id"):
        make(kind="test", statistic=2.0, p=0.01, num=None, den=None, lo=None, hi=None,
             interval_method=None, cluster_unit=None)  # fmt: skip


def test_rewriting_a_chapter_is_idempotent(tmp_path):
    claims.write_chapter(3, [make(), make(id="ch03.other")], tmp_path)
    claims.write_chapter(3, [make()], tmp_path)
    assert list(claims.load_all(tmp_path)) == ["ch03.share"]


def test_duplicates_fail_within_and_across_chapters(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        claims.write_chapter(3, [make(), make()], tmp_path)
    claims.write_chapter(3, [make()], tmp_path)
    claims.write_chapter(4, [make(chapter=4)], tmp_path)
    with pytest.raises(ValueError, match="more than one chapter"):
        claims.load_all(tmp_path)


def test_a_claim_must_be_written_by_its_own_chapter(tmp_path):
    with pytest.raises(ValueError, match="belongs to chapter"):
        claims.write_chapter(4, [make()], tmp_path)


def test_unresolved_references_are_reported(tmp_path):
    tex = tmp_path / "c.tex"
    tex.write_text(
        r"\est{ch03.share}{pct} \est{ch03.gone}{value} \est{ch03.share}{nope} \proto{x.y}"
    )
    _, defined = texgen.render_claims({"ch03.share": make()})
    probs = texgen.unresolved([tex], defined, {"privacy.min_cell"})
    assert (
        len(probs) == 3 and any("ch03.gone" in p for p in probs) and any("x.y" in p for p in probs)
    )


def test_repository_references_resolve(tmp_path):
    """Every \\proto key always resolves; \\est ids resolve whenever the claims have been built.

    Claims need the git-ignored dataset, so in CI (no build/claims) only the protocol references are checked.
    """
    from report_lib.paths import CLAIMS_DIR

    if any(CLAIMS_DIR.glob("*.parquet")):
        assert texgen.main(out_dir=tmp_path / "gen") == 0
    else:
        _, keys = texgen.render_protocol(__import__("report_lib.protocol").protocol.load())
        probs = texgen.unresolved(texgen.chapter_files(), {}, keys)
        assert [p for p in probs if "\\proto" in p] == []
    gen = tmp_path / "gen" / "protocol.tex"
    if gen.exists():
        assert gen.read_text().count(r"\csname proto@") > 10


def test_paths_through_the_data_symlink_stay_repository_relative(tmp_path, monkeypatch):
    """Worktrees symlink data/ to the main checkout; a claim must record data/..., never the machine's home path."""
    from report_lib import sources

    repo, shared = tmp_path / "worktree", tmp_path / "main" / "data"
    (shared / "parquet").mkdir(parents=True)
    (shared / "parquet" / "t.parquet").write_bytes(b"x")
    repo.mkdir()
    (repo / "data").symlink_to(shared)
    monkeypatch.setattr(sources, "REPO", repo)
    assert sources.rel(repo / "data" / "parquet" / "t.parquet") == "data/parquet/t.parquet"
    assert sources.rel(shared / "parquet" / "t.parquet") == "data/parquet/t.parquet"
    assert sources.rel(repo / "eda" / "x.csv") == "eda/x.csv"


def test_built_claims_record_no_absolute_paths():
    from report_lib.paths import CLAIMS_DIR

    absolute = [c.id for c in claims.load_all(CLAIMS_DIR).values() if c.source_path.startswith("/")]
    assert absolute == []
