"""The protocol and its git-backed freeze (eng review Q3)."""

import csv
import re
import subprocess

import pytest

from report_lib import protocol
from report_lib.paths import TABLES


def test_protocol_has_the_required_sections():
    p = protocol.load()
    for section in ("protocol", "dataset", "clock", "privacy", "gates", "disk"):
        assert section in p, section
    assert p["privacy"]["min_cell"] >= 1
    assert 0 < p["gates"]["nan_share_max"] < 1


def test_gate_ids_are_the_eleven_scorecard_rows():
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")  # noqa: E731
    with (TABLES / "granularity_hour_readiness.csv").open() as f:
        rows = list(csv.DictReader(f))
    expected = {f"{slug(r['scenario'])}.{slug(r['model'])}" for r in rows}
    ids = protocol.load()["gates"]["ids"]
    assert len(ids) == len(set(ids)) == 11 and set(ids) == expected


def test_repository_protocol_respects_its_freeze():
    assert protocol.freeze_violations() == []


def _git(repo, *args):
    # protocol.git_env() drops GIT_DIR and friends: under a pre-commit hook they would otherwise send these
    # commands (init, config, commit) to the repository being committed instead of the temporary one.
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=protocol.git_env(),
    ).stdout


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def _commit(repo, path, text):
    path.write_text(text)
    _git(repo, "add", path.name)
    _git(repo, "commit", "-q", "--no-verify", "-m", "x")
    return _git(repo, "rev-parse", "HEAD").strip()


BASE = '[protocol]\nfrozen = {frozen}\nfreeze_commit = "{commit}"\n[privacy]\nmin_cell = {cell}\n{amend}'


def test_freeze_detects_unamended_edits_and_unfreezing(repo):
    p = repo / "protocol.toml"
    _commit(repo, p, BASE.format(frozen="false", commit="", cell=10, amend=""))
    frozen = _commit(repo, p, BASE.format(frozen="true", commit="", cell=10, amend=""))
    _commit(repo, p, BASE.format(frozen="true", commit=frozen, cell=10, amend=""))
    assert protocol.freeze_violations(p, repo) == []

    p.write_text(BASE.format(frozen="true", commit=frozen, cell=5, amend=""))
    assert any("privacy.min_cell" in v for v in protocol.freeze_violations(p, repo))

    amend = '[[amendments]]\nfield = "privacy.min_cell"\nold = 10\nnew = 5\ndate = "2026-10-08"\nreason = "r"\n'
    p.write_text(BASE.format(frozen="true", commit=frozen, cell=5, amend=amend))
    assert protocol.freeze_violations(p, repo) == []

    p.write_text(BASE.format(frozen="false", commit="", cell=10, amend=""))
    assert protocol.freeze_violations(p, repo) == [
        "frozen went back to false after a committed freeze"
    ]


def test_freeze_needs_a_commit(repo):
    p = repo / "protocol.toml"
    _commit(repo, p, BASE.format(frozen="false", commit="", cell=10, amend=""))
    p.write_text(BASE.format(frozen="true", commit="", cell=10, amend=""))
    assert protocol.freeze_violations(p, repo) == []  # the freezing commit itself, before it lands
    _commit(repo, p, BASE.format(frozen="true", commit="", cell=10, amend=""))
    assert protocol.freeze_violations(p, repo) == ["frozen = true but freeze_commit is empty"]


def test_git_calls_ignore_hook_redirects(tmp_path, monkeypatch):
    """Under a hook, GIT_DIR and GIT_INDEX_FILE point at the repository being committed; nothing may reach it."""
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    _git(decoy, "init", "-q")
    before = (decoy / ".git" / "config").read_text()
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    p = work / "protocol.toml"
    frozen = _commit(work, p, BASE.format(frozen="true", commit="", cell=10, amend=""))
    _commit(work, p, BASE.format(frozen="true", commit=frozen, cell=10, amend=""))
    assert protocol.freeze_violations(p, work) == []
    assert (decoy / ".git" / "config").read_text() == before
    head = subprocess.run(
        ["git", "-C", str(decoy), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        text=True,
        env=protocol.git_env(),
    )
    assert head.returncode != 0, "the decoy repository received a commit"


def _expand(pattern):
    m = re.search(r"\{([^}]+)\}", pattern)
    if not m:
        return [pattern]
    return [pattern[: m.start()] + opt + pattern[m.end() :] for opt in m.group(1).split(",")]


def test_family_sizes_equal_the_tests_in_their_sources():
    import pandas as pd

    from report_lib.paths import REPO

    for fam in protocol.load()["families"]:
        n = sum(
            int(pd.read_csv(REPO / p)[fam["column"]].notna().sum()) for p in _expand(fam["source"])
        )
        assert n == fam["size"], fam["id"]


def test_every_gate_has_one_unit_and_one_split():
    g = protocol.load()["gates"]
    assert set(g["units"]) == set(g["ids"]) == set(g["splits"])


@pytest.mark.data
def test_dataset_files_match_their_frozen_hashes():
    from report_lib import sources
    from report_lib.paths import REPO

    for rel, digest in protocol.load()["dataset"]["sha256"].items():
        assert sources.sha256(REPO / "data" / rel) == digest, rel
