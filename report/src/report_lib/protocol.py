"""conf/protocol.toml: the registered specification, its freeze and its amendments.

Once `frozen = true`, every field must equal its value at `freeze_commit` unless an [[amendments]] entry records
the change (field, old, new, date, reason). `frozen` may never go back to false.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from report_lib.paths import CONF

PROTOCOL = CONF / "protocol.toml"
# Git exports these to hooks; inherited by a subprocess they override `git -C <dir>` and send every command to
# the repository being committed. All git calls here run without them.
GIT_REDIRECTS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_NAMESPACE",
)  # fmt: skip


def git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in GIT_REDIRECTS}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, env=git_env())


UNTRACKED = {"protocol.frozen", "protocol.freeze_commit"}


def load(path: Path = PROTOCOL) -> dict[str, Any]:
    return tomllib.loads(path.read_text())


def flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Dotted keys for every non-table value; arrays of tables (amendments, families) are left out."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            continue
        else:
            out[key] = v
    return out


def freeze_violations(path: Path = PROTOCOL, repo: Path | None = None) -> list[str]:
    """Differences between the frozen protocol and its freeze commit that no amendment explains."""
    now = load(path)
    p = now.get("protocol", {})
    repo = repo or path.parent
    found = _git("-C", str(repo), "rev-parse", "--show-toplevel")
    if found.returncode != 0:
        return [f"not a git repository: {repo}"]
    top = found.stdout.strip()
    relpath = path.resolve().relative_to(Path(top).resolve()).as_posix()
    if not p.get("frozen"):
        if _ever_frozen(top, relpath):
            return ["frozen went back to false after a committed freeze"]
        return []
    commit = p.get("freeze_commit", "")
    if not commit:
        return ["frozen = true but freeze_commit is empty"]
    shown = _git("-C", top, "show", f"{commit}:{relpath}")
    if shown.returncode != 0:
        return [f"cannot read {relpath} at freeze_commit {commit}: {shown.stderr.strip()}"]
    then = tomllib.loads(shown.stdout)
    a, b = flatten(then), flatten(now)
    amended = {
        (x.get("field"), repr(x.get("old")), repr(x.get("new"))) for x in now.get("amendments", [])
    }
    for x in now.get("amendments", []):
        for f in ("field", "old", "new", "date", "reason"):
            if f not in x:
                return [f"amendment {x} lacks {f}"]
    problems = []
    for key in sorted(set(a) | set(b)):
        if key in UNTRACKED or a.get(key) == b.get(key):
            continue
        if (key, repr(a.get(key)), repr(b.get(key))) not in amended:
            problems.append(f"{key}: {a.get(key)!r} -> {b.get(key)!r} without an amendment")
    if then.get("protocol", {}).get("frozen") is not True:
        problems.append("freeze_commit does not hold a frozen protocol")
    return problems


def _ever_frozen(top: str, relpath: str) -> bool:
    """True when any committed version of the protocol had frozen = true."""
    log = _git("-C", top, "log", "--format=%H", "--", relpath).stdout.split()
    for commit in log:
        shown = _git("-C", top, "show", f"{commit}:{relpath}")
        if shown.returncode == 0:
            try:
                if tomllib.loads(shown.stdout).get("protocol", {}).get("frozen") is True:
                    return True
            except tomllib.TOMLDecodeError:
                continue
    return False
